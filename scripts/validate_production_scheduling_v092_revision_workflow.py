#!/usr/bin/env python3
"""Validate the V092 immutable schedule publication workflow on a copied DB."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import sqlite3
import sys
from pathlib import Path

os.environ.setdefault("SECRET_KEY", "task4-v092-local-validation-only")

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from modules import config  # noqa: E402
from modules.domain.production_node_scheduling import NodeSchedulingError  # noqa: E402
from modules.migrations import LATEST_VERSION, run_migrations  # noqa: E402
from modules.repositories.schedule_capacity_repository import (  # noqa: E402
    ScheduleCapacityRepository,
)
from modules.services.schedule_capacity_service import ScheduleCapacityService  # noqa: E402


def _rows(db, sql, params=()):
    return [dict(row) for row in db.execute(sql, params).fetchall()]


def _digest(value):
    encoded = json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    )
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _formal_snapshot(db, order_id):
    return {
        "order": _rows(
            db,
            "SELECT id,plan_start,plan_end,current_schedule_revision_id,"
            "schedule_replan_required,schedule_replan_reason FROM orders WHERE id=?",
            (order_id,),
        ),
        "schedules": _rows(
            db,
            "SELECT * FROM order_process_schedules WHERE order_id=? ORDER BY id",
            (order_id,),
        ),
        "segments": _rows(
            db,
            "SELECT ss.* FROM order_process_schedule_segments ss "
            "JOIN order_process_schedules s ON s.id=ss.schedule_id "
            "WHERE s.order_id=? ORDER BY ss.id",
            (order_id,),
        ),
        "allocations": _rows(
            db,
            "SELECT a.* FROM production_node_schedule_allocations a "
            "JOIN order_process_schedules s ON s.id=a.schedule_id "
            "WHERE s.order_id=? ORDER BY a.id",
            (order_id,),
        ),
    }


def _user_id(db, login):
    row = db.execute(
        "SELECT id FROM users WHERE username=? OR employee_no=? ORDER BY id LIMIT 1",
        (login, login),
    ).fetchone()
    if row is None:
        raise RuntimeError(f"validation user not found: {login}")
    return int(row["id"])


def _candidate_orders(db, requested_order_id=None):
    params = []
    condition = ""
    if requested_order_id is not None:
        condition = "AND o.id=?"
        params.append(int(requested_order_id))
    return db.execute(
        "SELECT o.id,o.order_no,o.plan_start,o.current_schedule_revision_id "
        "FROM orders o WHERE o.deleted_at IS NULL "
        "AND o.status IN ('pending','producing') "
        "AND o.current_schedule_revision_id IS NOT NULL "
        f"{condition} ORDER BY o.order_no,o.id",
        params,
    ).fetchall()


def validate(source, output, operator_login, approver_login, order_id=None):
    source = Path(source).resolve()
    output = Path(output).resolve()
    if source == output:
        raise RuntimeError("source and output database paths must differ")
    output.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, output)

    db = sqlite3.connect(output)
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA foreign_keys=ON")
    try:
        before_version = int(db.execute("PRAGMA user_version").fetchone()[0])
        executed = run_migrations(db)
        after_version = int(db.execute("PRAGMA user_version").fetchone()[0])
        if after_version != LATEST_VERSION or after_version < 92:
            raise RuntimeError(f"unexpected migrated version: {after_version}")
        if db.execute("PRAGMA quick_check").fetchone()[0] != "ok":
            raise RuntimeError("database quick_check failed")
        foreign_keys = _rows(db, "PRAGMA foreign_key_check")
        if foreign_keys:
            raise RuntimeError("database foreign_key_check failed")

        operator_id = _user_id(db, operator_login)
        approver_id = _user_id(db, approver_login)
        if operator_id == approver_id:
            raise RuntimeError("operator and independent approver must differ")

        config.PRODUCTION_NODE_QUERY_ENABLED = True
        config.PRODUCTION_NODE_COMPAT_AUDIT_ENABLED = True
        config.PRODUCTION_NODE_WRITE_ENABLED = True
        config.PRODUCTION_NODE_ENGINE_ENABLED = True

        selected = None
        generated = None
        generation_errors = []
        formal_before = None
        work_records_before = _digest(_rows(db, "SELECT * FROM work_records ORDER BY id"))
        for order in _candidate_orders(db, requested_order_id=order_id):
            snapshot = _formal_snapshot(db, order["id"])
            try:
                generated = ScheduleCapacityService.generate_order_schedule(
                    order["id"],
                    start_date=order["plan_start"],
                    schedule_run_key=f"v092-validation-order-{order['id']}",
                    actor_id=operator_id,
                    db=db,
                    use_node_engine_override=True,
                )
            except Exception as exc:  # keep searching the disposable copy
                generation_errors.append(
                    {"order_id": order["id"], "order_no": order["order_no"], "error": str(exc)}
                )
                continue
            selected = dict(order)
            formal_before = snapshot
            break
        if selected is None or generated is None:
            raise RuntimeError(
                "no published active order could generate a V092 draft: "
                + json.dumps(generation_errors[:10], ensure_ascii=False)
            )

        revision_id = int(generated["schedule_revision_id"])
        formal_after_draft = _formal_snapshot(db, selected["id"])
        if _digest(formal_before) != _digest(formal_after_draft):
            raise RuntimeError("draft generation changed the formal schedule projection")
        revision = ScheduleCapacityRepository.find_revision(revision_id, db=db)
        if not revision or not revision["content_digest"]:
            raise RuntimeError("draft revision content digest was not frozen")
        ScheduleCapacityRepository.assert_revision_integrity(revision_id, db=db)

        ScheduleCapacityService.submit_revision(
            revision_id,
            "V092 disposable-copy submission validation",
            f"v092-validation-submit-{revision_id}",
            operator_id,
            db=db,
        )
        self_approval_blocked = False
        try:
            ScheduleCapacityService.approve_revision(
                revision_id,
                "self approval must fail",
                f"v092-validation-self-approve-{revision_id}",
                operator_id,
                db=db,
            )
        except NodeSchedulingError as exc:
            self_approval_blocked = exc.code == "INDEPENDENT_APPROVER_REQUIRED"
        if not self_approval_blocked:
            raise RuntimeError("independent approval guard did not block the creator")

        ScheduleCapacityService.approve_revision(
            revision_id,
            "V092 independent approval validation",
            f"v092-validation-approve-{revision_id}",
            approver_id,
            db=db,
        )
        publish_key = f"v092-validation-publish-{revision_id}"
        published = ScheduleCapacityService.publish_revision(
            revision_id,
            "V092 immutable publication validation",
            publish_key,
            operator_id,
            db=db,
        )
        replay = ScheduleCapacityService.publish_revision(
            revision_id,
            "V092 immutable publication validation",
            publish_key,
            operator_id,
            db=db,
        )
        if not replay.get("idempotent_replay"):
            raise RuntimeError("publication replay was not idempotent")

        current = db.execute(
            "SELECT current_schedule_revision_id FROM orders WHERE id=?",
            (selected["id"],),
        ).fetchone()[0]
        if int(current) != revision_id:
            raise RuntimeError("published revision did not become the current revision")
        published_count = db.execute(
            "SELECT COUNT(*) FROM schedule_revisions "
            "WHERE order_id=? AND status='published'",
            (selected["id"],),
        ).fetchone()[0]
        if published_count != 1:
            raise RuntimeError("order does not have exactly one published revision")
        projection_revisions = {
            int(row[0])
            for row in db.execute(
                "SELECT DISTINCT schedule_revision_id FROM order_process_schedules "
                "WHERE order_id=?",
                (selected["id"],),
            ).fetchall()
        }
        if projection_revisions != {revision_id}:
            raise RuntimeError("formal projection does not match the published revision")

        immutable_item_blocked = False
        try:
            db.execute(
                "UPDATE schedule_revision_items SET payload_digest='tampered' "
                "WHERE revision_id=?",
                (revision_id,),
            )
        except sqlite3.IntegrityError:
            immutable_item_blocked = True
        if not immutable_item_blocked:
            raise RuntimeError("published revision item mutation was not blocked")
        db.rollback()

        work_records_after = _digest(_rows(db, "SELECT * FROM work_records ORDER BY id"))
        if work_records_after != work_records_before:
            raise RuntimeError("schedule workflow changed work-reporting facts")

        return {
            "ok": True,
            "source_database": str(source),
            "validation_database": str(output),
            "before_user_version": before_version,
            "after_user_version": after_version,
            "migrations_executed": executed,
            "quick_check": "ok",
            "foreign_key_violations": 0,
            "order_id": selected["id"],
            "order_no": selected["order_no"],
            "previous_revision_id": selected["current_schedule_revision_id"],
            "published_revision_id": revision_id,
            "content_digest": revision["content_digest"],
            "formal_projection_unchanged_before_publish": True,
            "independent_approval_guard": True,
            "publication_event_id": published["event"]["id"],
            "publication_idempotent_replay": True,
            "single_published_revision": True,
            "formal_projection_matches_published_revision": True,
            "immutable_item_guard": True,
            "work_records_unchanged": True,
            "generation_errors_before_selected_order": generation_errors,
        }
    finally:
        db.close()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--db", required=True, help="source read-only production copy")
    parser.add_argument("--output-db", required=True, help="disposable V092 validation copy")
    parser.add_argument("--operator", default="1000")
    parser.add_argument("--approver", default="1004")
    parser.add_argument("--order-id", type=int)
    parser.add_argument("--json-output")
    args = parser.parse_args()
    report = validate(
        args.db,
        args.output_db,
        args.operator,
        args.approver,
        order_id=args.order_id,
    )
    encoded = json.dumps(report, ensure_ascii=False, indent=2)
    if args.json_output:
        Path(args.json_output).write_text(encoded + "\n", encoding="utf-8")
    print(encoded)


if __name__ == "__main__":
    main()
