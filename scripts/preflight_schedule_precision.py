#!/usr/bin/env python3
"""Run a non-destructive precision-schedule trial on a database copy.

The source database is opened read-only and copied through SQLite's backup API.
All order generation and coverage checks happen on the temporary copy, so this
script can be pointed at a production backup without changing production data.
"""

import argparse
import json
import os
import sqlite3
import sys
import tempfile
from collections import Counter


PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from modules.migrations import run_migrations
from modules.repositories.schedule_capacity_repository import ScheduleCapacityRepository
from modules.services.schedule_capacity_service import ScheduleCapacityService


def _copy_database(source_path):
    source_uri = f"file:{os.path.abspath(source_path)}?mode=ro"
    source = sqlite3.connect(source_uri, uri=True)
    temp = tempfile.NamedTemporaryFile(prefix="qr-schedule-preflight-", suffix=".db", delete=False)
    temp.close()
    target = sqlite3.connect(temp.name)
    target.row_factory = sqlite3.Row
    try:
        source.backup(target)
        target.commit()
    finally:
        source.close()
    return target, temp.name


def run_preflight(source_path, limit=1000):
    db, copied_path = _copy_database(source_path)
    try:
        run_migrations(db)
        orders = ScheduleCapacityRepository.list_schedulable_orders(limit, db=db)
        totals = {
            "orders": len(orders),
            "operations": 0,
            "planned_operations": 0,
            "blocked_operations": 0,
            "blocked_missing_standard": 0,
            "blocked_missing_calendar": 0,
            "errors": [],
        }
        process_stats = {}
        product_stats = {}
        blocked_reasons = Counter()
        missing_standard_details = []
        for order in orders:
            run_key = f"preflight-{order['id']}-{order['plan_start'] or 'no-date'}"
            product_key = (
                f"id:{order['product_id']}"
                if order["product_id"] is not None
                else f"code:{order['product_code'] or ''}"
            )
            product_stats.setdefault(product_key, {
                "product_id": order["product_id"],
                "product_code": order["product_code"] or "",
                "product_name": order["product_name"] or "",
                "orders": 0,
                "operations": 0,
                "planned_operations": 0,
                "blocked_operations": 0,
                "blocked_missing_standard": 0,
                "occupied_minutes": 0.0,
                "match_scope_counts": Counter(),
                "blocked_reason_counts": Counter(),
            })
            product_stats[product_key]["orders"] += 1
            try:
                result = ScheduleCapacityService.generate_order_schedule(
                    order["id"],
                    start_date=order["plan_start"] or None,
                    schedule_run_key=run_key,
                    db=db,
                )
            except Exception as exc:  # an invalid legacy order must not hide other gaps
                totals["errors"].append({"order_id": order["id"], "error": str(exc)})
                continue
            operations = result.get("operations", [])
            totals["operations"] += len(operations)
            for operation in operations:
                process_key = str(operation.get("process_id"))
                process_stats.setdefault(process_key, {
                    "process_id": operation.get("process_id"),
                    "process_name": operation.get("process_name_snapshot")
                    or operation.get("process_name") or "",
                    "operations": 0,
                    "planned_operations": 0,
                    "blocked_operations": 0,
                    "occupied_minutes": 0.0,
                    "match_scope_counts": Counter(),
                    "blocked_reason_counts": Counter(),
                })
                process_stat = process_stats[process_key]
                process_stat["operations"] += 1
                product_stat = product_stats[product_key]
                product_stat["operations"] += 1
                if operation.get("status") == "planned":
                    totals["planned_operations"] += 1
                    process_stat["planned_operations"] += 1
                    product_stat["planned_operations"] += 1
                    process_stat["occupied_minutes"] += float(operation.get("occupied_minutes") or operation.get("planned_minutes") or 0)
                    product_stat["occupied_minutes"] += float(operation.get("occupied_minutes") or operation.get("planned_minutes") or 0)
                    process_stat["match_scope_counts"][operation.get("standard_match_scope") or "未匹配"] += 1
                    product_stat["match_scope_counts"][operation.get("standard_match_scope") or "未匹配"] += 1
                elif operation.get("status") == "blocked":
                    totals["blocked_operations"] += 1
                    reason = operation.get("blocked_reason", "")
                    blocked_reasons[reason or "未说明"] += 1
                    process_stat["blocked_operations"] += 1
                    process_stat["blocked_reason_counts"][reason or "未说明"] += 1
                    product_stat["blocked_reason_counts"][reason or "未说明"] += 1
                    product_stat["blocked_operations"] += 1
                    if reason == "未配置标准工时":
                        totals["blocked_missing_standard"] += 1
                        product_stat["blocked_missing_standard"] += 1
                        missing_standard_details.append({
                            "order_id": order["id"],
                            "order_no": order["order_no"],
                            "product_id": order["product_id"],
                            "product_code": order["product_code"] or "",
                            "product_name": order["product_name"] or "",
                            "process_id": operation.get("process_id"),
                            "process_name": operation.get("process_name_snapshot")
                            or operation.get("process_name") or "",
                            "route_version_id": operation.get("route_version_id"),
                            "process_version_id": operation.get("process_version_id"),
                        })
                    if "工作日历" in reason or "班次" in reason:
                        totals["blocked_missing_calendar"] += 1
        conflicts = [dict(row) for row in ScheduleCapacityRepository.list_schedule_conflicts(db=db)]
        totals["coverage_percent"] = round(
            totals["planned_operations"] / totals["operations"] * 100, 2
        ) if totals["operations"] else 100.0
        totals["line_conflicts"] = len(conflicts)
        totals["schedule_runs"] = db.execute("SELECT COUNT(*) FROM schedule_runs").fetchone()[0]
        totals["database_user_version"] = db.execute("PRAGMA user_version").fetchone()[0]
        totals["calendars"] = ScheduleCapacityRepository.list_calendars(db=db)
        totals["conflicts"] = conflicts
        line_loads = [dict(row) for row in ScheduleCapacityRepository.list_line_loads(db=db)]
        conflict_counts = Counter(row.get("process_line_id") for row in conflicts)
        for line in line_loads:
            line["conflict_count"] = conflict_counts.get(line.get("process_line_id"), 0)
        totals["line_loads"] = line_loads
        totals["blocked_reason_counts"] = dict(sorted(blocked_reasons.items()))
        totals["missing_standard_details"] = missing_standard_details

        def finalize_stats(stats):
            result = []
            for item in stats.values():
                operations = item["operations"]
                item["coverage_percent"] = round(
                    item["planned_operations"] / operations * 100, 2
                ) if operations else 100.0
                item["occupied_minutes"] = round(item["occupied_minutes"], 2)
                item["match_scope_counts"] = dict(sorted(item["match_scope_counts"].items()))
                item["blocked_reason_counts"] = dict(sorted(item["blocked_reason_counts"].items()))
                result.append(item)
            return sorted(result, key=lambda row: (str(row.get("process_name") or row.get("product_name") or ""), str(row.get("process_id") or row.get("product_id") or "")))

        totals["process_statistics"] = finalize_stats(process_stats)
        totals["product_statistics"] = finalize_stats(product_stats)
        return totals
    finally:
        db.close()
        for candidate in (copied_path, copied_path + "-wal", copied_path + "-shm"):
            try:
                os.unlink(candidate)
            except OSError:
                pass


def main(argv=None):
    parser = argparse.ArgumentParser(description="在数据库副本上执行排程精度试排")
    parser.add_argument("--db", required=True, help="源数据库路径（只读）")
    parser.add_argument("--limit", type=int, default=1000, help="最多试排订单数，1-1000")
    args = parser.parse_args(argv)
    if args.limit < 1 or args.limit > 1000:
        parser.error("--limit 必须在 1 到 1000 之间")
    print(json.dumps(run_preflight(args.db, args.limit), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
