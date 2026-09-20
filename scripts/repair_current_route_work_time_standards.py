#!/usr/bin/env python3
"""Controlled current-route work-time standard repair.

Production scope is intentionally fixed to route 46, source version 27 and
target version 83. Routes 78/version 85 and 79/version 86 are verification-only
dependencies and must already contain seven active exact standards.
"""

import argparse
import json
import os
import sqlite3
import sys
from datetime import datetime
from pathlib import Path


PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from scripts import repair_schedule_standard_bindings as controlled_copy


ROUTE_ID = 46
SOURCE_ROUTE_VERSION_ID = 27
TARGET_ROUTE_VERSION_ID = 83
EXPECTED_DATABASE_VERSION = 90
EXPECTED_PROCESS_COUNT = 7
EXPECTED_STANDARD_MINUTES = 60.0
EXPECTED_SETUP_MINUTES = 10.0
EXPECTED_DIFFICULTY_FACTOR = 1.0
CONFIRMED_EXISTING_ROUTES = (
    {"route_id": 78, "route_version_id": 85},
    {"route_id": 79, "route_version_id": 86},
)


def _row(row):
    return dict(row) if row is not None else None


def _version(db, version_id):
    return _row(
        db.execute(
            "SELECT id,process_route_id,version,name,status,effective_from,effective_to "
            "FROM process_route_versions WHERE id=?",
            (version_id,),
        ).fetchone()
    )


def _items(db, version_id):
    return [
        dict(row)
        for row in db.execute(
            "SELECT item.process_id,item.process_version_id,item.seq_order,"
            "process_version.name AS process_name "
            "FROM process_route_version_items item "
            "JOIN process_versions process_version "
            "ON process_version.id=item.process_version_id "
            "WHERE item.route_version_id=? ORDER BY item.seq_order,item.id",
            (version_id,),
        ).fetchall()
    ]


def _active_generic_standards(db, version_id):
    return [
        dict(row)
        for row in db.execute(
            "SELECT standard.* FROM work_time_standards standard "
            "WHERE standard.route_version_id=? AND standard.status='active' "
            "AND COALESCE(standard.product_id,0)=0 "
            "AND COALESCE(standard.product_code,'')='' "
            "ORDER BY standard.process_id,standard.id",
            (version_id,),
        ).fetchall()
    ]


def _supporting_route_check(db, route_id, route_version_id):
    current = db.execute(
        "SELECT current_effective_version_id FROM process_routes WHERE id=?",
        (route_id,),
    ).fetchone()
    items = _items(db, route_version_id)
    standards = _active_generic_standards(db, route_version_id)
    return {
        "route_id": route_id,
        "route_version_id": route_version_id,
        "is_current": bool(
            current
            and int(current["current_effective_version_id"] or 0) == route_version_id
        ),
        "item_count": len(items),
        "active_exact_standard_count": len(standards),
        "all_items_covered": {
            item["process_version_id"] for item in items
        }
        == {standard["process_version_id"] for standard in standards},
        "all_values_positive": all(
            float(standard["standard_minutes_per_unit"] or 0) > 0
            and float(standard["setup_minutes"] or 0) >= 0
            and float(standard["difficulty_factor"] or 0) > 0
            for standard in standards
        ),
    }


def build_preflight(
    db,
    *,
    route_id=ROUTE_ID,
    source_route_version_id=SOURCE_ROUTE_VERSION_ID,
    target_route_version_id=TARGET_ROUTE_VERSION_ID,
    supporting_routes=CONFIRMED_EXISTING_ROUTES,
    expected_database_version=EXPECTED_DATABASE_VERSION,
):
    source = _version(db, source_route_version_id)
    target = _version(db, target_route_version_id)
    root = db.execute(
        "SELECT id,current_effective_version_id FROM process_routes WHERE id=?",
        (route_id,),
    ).fetchone()
    source_items = _items(db, source_route_version_id)
    target_items = _items(db, target_route_version_id)
    source_standards = _active_generic_standards(db, source_route_version_id)
    target_standards = _active_generic_standards(db, target_route_version_id)
    source_by_process = {row["process_id"]: row for row in source_standards}
    support = [
        _supporting_route_check(
            db, int(item["route_id"]), int(item["route_version_id"])
        )
        for item in supporting_routes
    ]
    signature = lambda rows: [
        (row["process_id"], row["process_version_id"]) for row in rows
    ]
    checks = {
        "database_version": db.execute("PRAGMA user_version").fetchone()[0]
        == expected_database_version,
        "event_table_exists": db.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' "
            "AND name='work_time_standard_binding_events'"
        ).fetchone()
        is not None,
        "source_version_exists": source is not None,
        "target_version_exists": target is not None,
        "source_and_target_same_root": bool(
            source
            and target
            and source["process_route_id"] == route_id
            and target["process_route_id"] == route_id
        ),
        "source_is_superseded": bool(source and source["status"] == "superseded"),
        "target_is_current_published": bool(
            target
            and root
            and target["status"] == "published"
            and root["current_effective_version_id"] == target_route_version_id
        ),
        "seven_exact_revision_nodes": (
            len(source_items) == EXPECTED_PROCESS_COUNT
            and len(target_items) == EXPECTED_PROCESS_COUNT
            and signature(source_items) == signature(target_items)
        ),
        "seven_source_standards": len(source_standards) == EXPECTED_PROCESS_COUNT,
        "source_values_match_business_confirmation": all(
            float(row["standard_minutes_per_unit"] or 0)
            == EXPECTED_STANDARD_MINUTES
            and float(row["setup_minutes"] or 0) == EXPECTED_SETUP_MINUTES
            and float(row["difficulty_factor"] or 0)
            == EXPECTED_DIFFICULTY_FACTOR
            for row in source_standards
        ),
        "source_covers_target": (
            len(source_by_process) == EXPECTED_PROCESS_COUNT
            and {row["process_id"] for row in target_items}
            == set(source_by_process)
        ),
        "target_binding_cardinality_valid": (
            len(target_standards) in {0, EXPECTED_PROCESS_COUNT}
            and len({row["process_version_id"] for row in target_standards})
            == len(target_standards)
        ),
        "target_has_no_conflicting_values": all(
            float(row["standard_minutes_per_unit"] or 0)
            == EXPECTED_STANDARD_MINUTES
            and float(row["setup_minutes"] or 0) == EXPECTED_SETUP_MINUTES
            and float(row["difficulty_factor"] or 0)
            == EXPECTED_DIFFICULTY_FACTOR
            for row in target_standards
        ),
        "supporting_routes_complete": all(
            item["is_current"]
            and item["item_count"] == EXPECTED_PROCESS_COUNT
            and item["active_exact_standard_count"] == EXPECTED_PROCESS_COUNT
            and item["all_items_covered"]
            and item["all_values_positive"]
            for item in support
        ),
    }
    return {
        "ok": all(checks.values()),
        "checks": checks,
        "source": source,
        "target": target,
        "source_standard_ids": [row["id"] for row in source_standards],
        "existing_target_standard_ids": [row["id"] for row in target_standards],
        "supporting_routes": support,
    }


def run(
    db_path,
    *,
    apply=False,
    idempotency_key="",
    operator_id=None,
    approver_id=None,
    route_id=ROUTE_ID,
    source_route_version_id=SOURCE_ROUTE_VERSION_ID,
    target_route_version_id=TARGET_ROUTE_VERSION_ID,
    supporting_routes=CONFIRMED_EXISTING_ROUTES,
    expected_database_version=EXPECTED_DATABASE_VERSION,
):
    if not idempotency_key:
        raise ValueError("幂等键不能为空")
    if operator_id is None or approver_id is None:
        raise ValueError("必须提供操作人和独立批准人")
    if int(operator_id) == int(approver_id):
        raise ValueError("操作人和独立批准人不能相同")
    if apply:
        db = sqlite3.connect(db_path)
    else:
        db = sqlite3.connect(f"file:{Path(db_path).resolve()}?mode=ro", uri=True)
    db.row_factory = sqlite3.Row
    try:
        if apply:
            db.execute("PRAGMA foreign_keys=ON")
            db.execute("BEGIN IMMEDIATE")
        actors = db.execute(
            "SELECT id,status FROM users WHERE id IN (?,?)",
            (operator_id, approver_id),
        ).fetchall()
        if len(actors) != 2 or any(row["status"] != "active" for row in actors):
            raise ValueError("操作人或独立批准人不存在或未启用")
        preflight = build_preflight(
            db,
            route_id=route_id,
            source_route_version_id=source_route_version_id,
            target_route_version_id=target_route_version_id,
            supporting_routes=supporting_routes,
            expected_database_version=expected_database_version,
        )
        if not preflight["ok"]:
            if apply:
                db.rollback()
            return {
                "ok": False,
                "mode": "apply" if apply else "dry-run",
                "idempotency_key": idempotency_key,
                "preflight": preflight,
                "error": "预检未通过，禁止受控复制",
            }
        target = preflight["target"]
        bindings = (
            {
                "target_route_version_id": target_route_version_id,
                "source_standard_ids": tuple(preflight["source_standard_ids"]),
                "effective_from": target["effective_from"],
                "effective_to": target["effective_to"],
                "evidence_label": "当前路线标准工时受控继承",
            },
        )
        plan = controlled_copy.build_plan(
            db,
            idempotency_key,
            operator_id,
            approver_id,
            bindings=bindings,
        )
        planned_before_apply = sum(
            item["status"] == "planned" for item in plan
        )
        replayed = sum(
            item.get("reason") == "幂等重放" for item in plan
        )
        blocked = [item for item in plan if item["status"] == "blocked"]
        if blocked:
            if apply:
                db.rollback()
            return {
                "ok": False,
                "mode": "apply" if apply else "dry-run",
                "idempotency_key": idempotency_key,
                "preflight": preflight,
                "items": [
                    {
                        key: value
                        for key, value in item.items()
                        if key not in {"payload", "source"}
                    }
                    for item in plan
                ],
                "error": "目标存在冲突，禁止受控复制",
            }
        if apply:
            controlled_copy.apply_plan(db, plan)
            db.commit()
        postflight = (
            build_preflight(
                db,
                route_id=route_id,
                source_route_version_id=source_route_version_id,
                target_route_version_id=target_route_version_id,
                supporting_routes=supporting_routes,
                expected_database_version=expected_database_version,
            )
            if apply
            else None
        )
        target_count_ok = (
            len(postflight["existing_target_standard_ids"])
            == EXPECTED_PROCESS_COUNT
            if apply
            else True
        )
        return {
            "ok": not blocked and target_count_ok,
            "mode": "apply" if apply else "dry-run",
            "idempotency_key": idempotency_key,
            "operator_id": operator_id,
            "approver_id": approver_id,
            "preflight": preflight,
            "postflight": postflight,
            "total": len(plan),
            "planned": planned_before_apply,
            "applied": planned_before_apply if apply else 0,
            "replayed": replayed,
            "skipped": sum(item["status"] == "skipped" for item in plan),
            "blocked": len(blocked),
            "items": [
                {
                    key: value
                    for key, value in item.items()
                    if key not in {"payload", "source"}
                }
                for item in plan
            ],
            "generated_at": datetime.now().astimezone().isoformat(),
        }
    except Exception:
        if apply:
            db.rollback()
        raise
    finally:
        db.close()


def main(argv=None):
    parser = argparse.ArgumentParser(
        description="当前路线标准工时受控继承：路线46 V1 -> V2"
    )
    parser.add_argument("--db", required=True)
    parser.add_argument("--idempotency-key", required=True)
    parser.add_argument("--operator-id", required=True, type=int)
    parser.add_argument("--approver-id", required=True, type=int)
    parser.add_argument("--evidence-out")
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--dry-run", action="store_true")
    mode.add_argument("--apply", action="store_true")
    args = parser.parse_args(argv)
    report = run(
        args.db,
        apply=args.apply,
        idempotency_key=args.idempotency_key,
        operator_id=args.operator_id,
        approver_id=args.approver_id,
    )
    rendered = json.dumps(report, ensure_ascii=False, indent=2, default=str)
    if args.evidence_out:
        path = Path(args.evidence_out)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(rendered + "\n", encoding="utf-8")
    print(rendered)
    return 0 if report["ok"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
