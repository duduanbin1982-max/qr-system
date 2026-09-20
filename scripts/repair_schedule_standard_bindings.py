#!/usr/bin/env python3
"""Controlled, exact V085 historical standard binding repair.

Only the three approved historical route revisions are in scope.  The command
never chooses a row by similarity and never updates/deactivates source rows.
Use ``--dry-run`` first; ``--apply`` writes target standards and one immutable
evidence event per idempotency key.
"""

import argparse
import json
import os
import sqlite3
import sys
from datetime import datetime

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from modules.migrations import run_migrations


APPROVED_BINDINGS = (
    {"target_route_version_id": 53, "source_standard_ids": (31, 32, 33, 34, 35, 36)},
    {"target_route_version_id": 60, "source_standard_ids": (265, 266, 267, 268, 269, 270, 271)},
    {"target_route_version_id": 69, "source_standard_ids": (1, 2, 74, 75, 76, 77)},
)


def _row_dict(row):
    return dict(row) if row is not None else None


def _date_key(value):
    value = (value or "").strip()
    return value or None


def _overlaps(left_from, left_to, right_from, right_to):
    left_from = _date_key(left_from) or "0000-01-01"
    right_from = _date_key(right_from) or "0000-01-01"
    left_to = _date_key(left_to) or "9999-12-31"
    right_to = _date_key(right_to) or "9999-12-31"
    return left_from <= right_to and right_from <= left_to


def _route_process_binding(db, route_version_id, process_id):
    route = db.execute(
        "SELECT id,process_route_id,name,version,status FROM process_route_versions WHERE id=?",
        (route_version_id,),
    ).fetchone()
    if route is None:
        raise ValueError(f"目标路线版本不存在: {route_version_id}")
    item = db.execute(
        "SELECT process_version_id FROM process_route_version_items "
        "WHERE route_version_id=? AND process_id=?",
        (route_version_id, process_id),
    ).fetchone()
    if item is None:
        raise ValueError(f"目标路线版本未包含工序: route_version={route_version_id}, process={process_id}")
    process_version = db.execute(
        "SELECT id,process_id,version,name,process_code_snapshot,category FROM process_versions WHERE id=?",
        (item["process_version_id"],),
    ).fetchone()
    if process_version is None or process_version["process_id"] != process_id:
        raise ValueError(f"目标工序版本绑定无效: route_version={route_version_id}, process={process_id}")
    return route, process_version


def _existing_targets(db, route_version_id, process_version_id, source):
    product_clause = "product_id IS NULL" if source["product_id"] is None else "product_id=?"
    params = [route_version_id, process_version_id]
    if source["product_id"] is not None:
        params.append(source["product_id"])
    return db.execute(
        "SELECT * FROM work_time_standards WHERE route_version_id=? AND process_version_id=? "
        f"AND {product_clause} AND COALESCE(product_code,'')=COALESCE(?, '') "
        "AND status='active' ORDER BY id",
        params + [source["product_code"] or ""],
    ).fetchall()


def _target_payload(
    source,
    target_route,
    target_process,
    operator_id,
    evidence_label="V085受控历史绑定",
):
    remark = (source["remark"] or "").strip()
    suffix = f"{evidence_label}，源标准ID={source['id']}"
    return {
        "product_id": source["product_id"],
        "product_code": source["product_code"] or "",
        "product_name": source["product_name"] or "",
        "route_id": target_route["process_route_id"],
        "process_id": source["process_id"],
        "standard_minutes_per_unit": source["standard_minutes_per_unit"],
        "setup_minutes": source["setup_minutes"] or 0,
        "difficulty_factor": source["difficulty_factor"] or 1,
        "effective_from": source["effective_from"] or "",
        "effective_to": source["effective_to"] or "",
        "status": "active",
        "version": max(int(source["version"] or 1), 1),
        "remark": "; ".join(item for item in (remark, suffix) if item),
        "created_by": operator_id,
        "updated_by": operator_id,
        "process_version_id": target_process["id"],
        "process_code_snapshot": target_process["process_code_snapshot"] or "",
        "process_name_snapshot": target_process["name"] or "",
        "process_category_snapshot": target_process["category"] or "",
        "route_version_id": target_route["id"],
        "route_name_snapshot": target_route["name"] or "",
        "version_binding_source": "captured",
    }


def _insert_standard(db, payload):
    cur = db.execute(
        "INSERT INTO work_time_standards ("
        "product_id,product_code,product_name,route_id,process_id,"
        "standard_minutes_per_unit,setup_minutes,difficulty_factor,effective_from,effective_to,"
        "status,version,remark,created_by,updated_by,process_version_id,process_code_snapshot,"
        "process_name_snapshot,process_category_snapshot,route_version_id,route_name_snapshot,"
        "version_binding_source) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (
            payload["product_id"], payload["product_code"], payload["product_name"], payload["route_id"],
            payload["process_id"], payload["standard_minutes_per_unit"], payload["setup_minutes"],
            payload["difficulty_factor"], payload["effective_from"], payload["effective_to"],
            payload["status"], payload["version"], payload["remark"], payload["created_by"],
            payload["updated_by"], payload["process_version_id"], payload["process_code_snapshot"],
            payload["process_name_snapshot"], payload["process_category_snapshot"], payload["route_version_id"],
            payload["route_name_snapshot"], payload["version_binding_source"],
        ),
    )
    return cur.lastrowid


def _insert_event(db, event):
    db.execute(
        "INSERT INTO work_time_standard_binding_events ("
        "idempotency_key,source_standard_id,target_standard_id,source_route_version_id,"
        "source_process_version_id,target_route_version_id,target_process_version_id,product_id,product_code,"
        "standard_minutes_per_unit,setup_minutes,difficulty_factor,effective_from,effective_to,"
        "source_snapshot_json,target_snapshot_json,status,reason,operator_id,approver_id) "
        "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (
            event["idempotency_key"], event["source_standard_id"], event["target_standard_id"],
            event["source_route_version_id"], event["source_process_version_id"],
            event["target_route_version_id"], event["target_process_version_id"], event["product_id"],
            event["product_code"], event["standard_minutes_per_unit"], event["setup_minutes"],
            event["difficulty_factor"], event["effective_from"], event["effective_to"],
            event["source_snapshot_json"], event["target_snapshot_json"], event["status"],
            event["reason"], event["operator_id"], event["approver_id"],
        ),
    )


def build_plan(db, idempotency_key, operator_id, approver_id, bindings=None):
    plan = []
    for mapping in bindings or APPROVED_BINDINGS:
        target_route_version_id = mapping["target_route_version_id"]
        for source_id in mapping["source_standard_ids"]:
            source = db.execute("SELECT * FROM work_time_standards WHERE id=?", (source_id,)).fetchone()
            if source is None:
                plan.append({"source_standard_id": source_id, "target_route_version_id": target_route_version_id,
                             "status": "blocked", "reason": "源标准不存在"})
                continue
            source = _row_dict(source)
            target_route, target_process = _route_process_binding(
                db, target_route_version_id, source["process_id"],
            )
            payload = _target_payload(
                source,
                target_route,
                target_process,
                operator_id,
                mapping.get("evidence_label", "V085受控历史绑定"),
            )
            if mapping.get("effective_from"):
                payload["effective_from"] = mapping["effective_from"]
            if "effective_to" in mapping:
                payload["effective_to"] = mapping["effective_to"] or ""
            key = f"{idempotency_key}:route-{target_route_version_id}:source-{source_id}"
            prior = db.execute(
                "SELECT * FROM work_time_standard_binding_events WHERE idempotency_key=?", (key,)
            ).fetchone()
            if prior:
                plan.append({"source_standard_id": source_id, "target_route_version_id": target_route_version_id,
                             "target_process_id": source["process_id"], "status": prior["status"],
                             "target_standard_id": prior["target_standard_id"], "reason": "幂等重放"})
                continue

            targets = _existing_targets(db, target_route_version_id, target_process["id"], source)
            conflicting = []
            identical = []
            for target in targets:
                same_values = (
                    float(target["standard_minutes_per_unit"]) == float(payload["standard_minutes_per_unit"])
                    and float(target["setup_minutes"] or 0) == float(payload["setup_minutes"] or 0)
                    and float(target["difficulty_factor"] or 1) == float(payload["difficulty_factor"] or 1)
                )
                if _overlaps(target["effective_from"], target["effective_to"], payload["effective_from"], payload["effective_to"]):
                    (identical if same_values else conflicting).append(target)
            if conflicting:
                status, reason = "blocked", "目标版本已存在不同值且有效期重叠"
                target_id = conflicting[0]["id"]
            elif identical:
                status, reason = "skipped", "目标已存在相同精确标准"
                target_id = identical[0]["id"]
            else:
                status, reason, target_id = "planned", "待受控复制", None
            plan.append({
                "source_standard_id": source_id,
                "source_route_version_id": source["route_version_id"],
                "source_process_version_id": source["process_version_id"],
                "target_route_version_id": target_route_version_id,
                "target_process_version_id": target_process["id"],
                "process_id": source["process_id"],
                "process_name": target_process["name"],
                "status": status,
                "reason": reason,
                "target_standard_id": target_id,
                "idempotency_key": key,
                "payload": payload,
                "source": source,
                "operator_id": operator_id,
                "approver_id": approver_id,
            })
    return plan


def apply_plan(db, plan):
    applied = []
    for item in plan:
        if item["status"] not in {"planned", "skipped"}:
            continue
        if item["status"] == "planned":
            target_id = _insert_standard(db, item["payload"])
            item["target_standard_id"] = target_id
            status = "applied"
        else:
            target_id = item["target_standard_id"]
            status = "skipped"
        source = item["source"]
        payload = item["payload"]
        _insert_event(db, {
            "idempotency_key": item["idempotency_key"],
            "source_standard_id": source["id"],
            "target_standard_id": target_id,
            "source_route_version_id": source["route_version_id"],
            "source_process_version_id": source["process_version_id"],
            "target_route_version_id": payload["route_version_id"],
            "target_process_version_id": payload["process_version_id"],
            "product_id": payload["product_id"],
            "product_code": payload["product_code"],
            "standard_minutes_per_unit": payload["standard_minutes_per_unit"],
            "setup_minutes": payload["setup_minutes"],
            "difficulty_factor": payload["difficulty_factor"],
            "effective_from": payload["effective_from"],
            "effective_to": payload["effective_to"],
            "source_snapshot_json": json.dumps(source, ensure_ascii=False, sort_keys=True, default=str),
            "target_snapshot_json": json.dumps(payload, ensure_ascii=False, sort_keys=True, default=str),
            "status": status,
            "reason": item["reason"],
            "operator_id": item["operator_id"],
            "approver_id": item["approver_id"],
        })
        item["status"] = status
        applied.append(item)
    return applied


def run(db_path, *, apply=False, idempotency_key="", operator_id=None, approver_id=None):
    if not idempotency_key:
        raise ValueError("幂等键不能为空")
    if operator_id is None or approver_id is None:
        raise ValueError("必须提供操作人和独立批准人")
    db = sqlite3.connect(db_path)
    db.row_factory = sqlite3.Row
    try:
        run_migrations(db)
        plan = build_plan(db, idempotency_key, operator_id, approver_id)
        blocked = [item for item in plan if item["status"] == "blocked"]
        if apply and blocked:
            raise ValueError("存在冲突或缺失源标准，禁止应用")
        if apply:
            with db:
                apply_plan(db, plan)
        return {
            "ok": not blocked,
            "mode": "apply" if apply else "dry-run",
            "idempotency_key": idempotency_key,
            "operator_id": operator_id,
            "approver_id": approver_id,
            "total": len(plan),
            "planned": sum(item["status"] == "planned" for item in plan),
            "applied": sum(item["status"] == "applied" for item in plan),
            "skipped": sum(item["status"] == "skipped" for item in plan),
            "blocked": len(blocked),
            "items": [
                {key: value for key, value in item.items() if key not in {"payload", "source"}}
                for item in plan
            ],
        }
    finally:
        db.close()


def main(argv=None):
    parser = argparse.ArgumentParser(description="V085 历史路线精确标准受控绑定")
    parser.add_argument("--db", required=True)
    parser.add_argument("--idempotency-key", required=True)
    parser.add_argument("--operator-id", required=True, type=int)
    parser.add_argument("--approver-id", required=True, type=int)
    parser.add_argument("--dry-run", action="store_true", default=False)
    parser.add_argument("--apply", action="store_true", default=False)
    args = parser.parse_args(argv)
    if args.dry_run == args.apply:
        parser.error("必须且只能指定 --dry-run 或 --apply")
    report = run(
        args.db,
        apply=args.apply,
        idempotency_key=args.idempotency_key,
        operator_id=args.operator_id,
        approver_id=args.approver_id,
    )
    print(json.dumps(report, ensure_ascii=False, indent=2, default=str))
    return 0 if report["ok"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
