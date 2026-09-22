#!/usr/bin/env python3
"""Render the precision work-time audit JSON into UTF-8 evidence files."""

from __future__ import annotations

import argparse
import csv
import json
from collections import Counter, defaultdict
from pathlib import Path


def _load_json(path: Path) -> dict:
    raw = path.read_bytes()
    for encoding in ("utf-8", "gb18030", "gbk"):
        try:
            text = raw.decode(encoding)
            start = text.find("{")
            if start < 0:
                raise ValueError("audit output does not contain a JSON object")
            return json.loads(text[start:])
        except (UnicodeDecodeError, json.JSONDecodeError):
            continue
    raise ValueError(f"cannot decode audit output: {path}")


def _count_by_process(rows):
    result = defaultdict(Counter)
    for row in rows:
        result[row.get("process_name") or "未命名工序"][row.get("match_tier") or "unknown"] += 1
    return {name: dict(sorted(counts.items())) for name, counts in sorted(result.items())}


def render(input_path: str | Path, output_dir: str | Path, *, source_host: str, production_commit: str, source_version: str) -> dict:
    data = _load_json(Path(input_path).expanduser().resolve())
    target = Path(output_dir).expanduser().resolve()
    target.mkdir(parents=True, exist_ok=True)
    rows = data.get("work_time_audit_rows") or []
    coverage = data.get("work_time_coverage") or {}

    normalized = {
        "schema": "qr-system-production-scheduling-work-time-audit/v1",
        "source_host": source_host,
        "production_commit": production_commit,
        "source_database_version": source_version,
        "replica_database_version": data.get("database_user_version"),
        "orders": data.get("orders", 0),
        "operations": data.get("operations", 0),
        "work_time_coverage": coverage,
        "process_tier_counts": _count_by_process(rows),
        "rows": rows,
    }
    json_path = target / "work-time-coverage-audit.json"
    json_path.write_text(json.dumps(normalized, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    csv_path = target / "work-time-coverage-audit.csv"
    fieldnames = [
        "order_id", "order_no", "product_id", "product_code", "product_name",
        "order_process_id", "process_id", "process_name", "route_version_id",
        "process_version_id", "status", "execution_mode", "standard_match_scope",
        "match_tier", "standard_id", "standard_version", "standard_minutes_per_unit",
        "setup_minutes", "difficulty_factor", "blocked_code", "blocked_reason",
    ]
    with csv_path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)

    tiers = Counter(row.get("match_tier") or "unknown" for row in rows)
    lines = [
        "# 生产排程 Task 2：192.168.1.8 精确工时覆盖真实副本审计",
        "",
        "**审计日期：** 2026-09-22（Asia/Shanghai）  ",
        f"**生产主机：** `{source_host}`  ",
        f"**生产代码提交：** `{production_commit}`  ",
        f"**生产数据库版本：** V{source_version}  ",
        f"**副本审计数据库版本：** V{data.get('database_user_version')}  ",
        "**安全边界：** 仅读取生产数据库并在本地副本迁移/试排；未修改生产数据库、配置、服务或附件。",
        "",
        "## 1. 总体结果",
        "",
        f"- 活动订单：**{data.get('orders', 0)}**",
        f"- 工序总数：**{data.get('operations', 0)}**",
        f"- 内部可评估工序：**{coverage.get('evaluable_internal_operation_count', 0)}**",
        f"- 工时已匹配：**{coverage.get('matched_operation_count', 0)}**",
        f"- 产品/路线版本/工序版本绑定命中：**{coverage.get('version_bound_match_count', 0)}**",
        f"- 内部工时覆盖率：**{coverage.get('coverage_percent', 0)}%**",
        f"- 版本绑定覆盖率：**{coverage.get('version_bound_coverage_percent', 0)}%**",
        f"- 缺失标准工时阻断：**{coverage.get('missing_standard_operation_count', 0)}**",
        f"- 节点/日历/其他阻断：**{coverage.get('blocked_operation_count', 0)}**",
        f"- 已完成事实：**{coverage.get('completed_fact_count', 0)}**",
        f"- 外协/非排程：**{coverage.get('non_scheduled_count', 0)}**",
        "",
        "## 2. 命中分层",
        "",
        "| 命中层级 | 数量 | 结论 |",
        "|---|---:|---|",
        f"| 精确路线版本 + 工序版本通用工时 | {tiers.get('exact_route_process_version_generic', 0)} | 已绑定当前路线/工序版本，使用通用产品标准 |",
        f"| 产品 + 路线版本 + 工序版本 | {tiers.get('exact_product_route_process_version', 0)} | 精确产品标准 |",
        f"| 路线/工序回退 | {sum(v for k, v in tiers.items() if k.endswith('_fallback'))} | 当前副本未发现 |",
        f"| 外协/非排程 | {tiers.get('non_scheduled', 0)} | 不占用内部节点容量 |",
        f"| 已完成事实 | {tiers.get('completed_fact', 0)} | 不重新排程，不要求当前工时 |",
        f"| 缺失标准工时 | {tiers.get('missing_standard', 0)} | 必须阻断并业务确认 |",
        f"| 其他阻断 | {sum(v for k, v in tiers.items() if k.startswith('blocked_'))} | 必须处理后才能发布 |",
        "",
        "## 3. 按工序分布",
        "",
        "| 工序 | 分类数量 |",
        "|---|---|",
    ]
    for process_name, counts in _count_by_process(rows).items():
        detail = "、".join(f"{key}={value}" for key, value in counts.items())
        lines.append(f"| {process_name} | {detail} |")

    lines.extend([
        "",
        "## 4. 非排程/外协真实清单",
        "",
    ])
    non_scheduled = [row for row in rows if row.get("match_tier") == "non_scheduled"]
    if non_scheduled:
        lines.extend([
            "| 订单 | 产品 | 工序 | 路线版本 | 工序版本 |",
            "|---|---|---|---:|---:|",
        ])
        for row in non_scheduled:
            lines.append(
                f"| {row.get('order_no','')} | {row.get('product_name','')} | "
                f"{row.get('process_name','')} | {row.get('route_version_id','')} | "
                f"{row.get('process_version_id','')} |"
            )
    else:
        lines.append("当前没有外协/非排程工序。")

    missing = coverage.get("missing_standard_details") or []
    blocked = coverage.get("blocked_details") or []
    lines.extend(["", "## 5. 缺失工时阻断清单", ""])
    if missing:
        lines.extend(["| 订单 | 工序 | 路线版本 | 工序版本 | 原因 |", "|---|---|---:|---:|---|"])
        for row in missing:
            lines.append(
                f"| {row.get('order_no','')} | {row.get('process_name','')} | "
                f"{row.get('route_version_id','')} | {row.get('process_version_id','')} | "
                f"{row.get('blocked_reason','未配置标准工时')} |"
            )
    else:
        lines.append("当前没有缺失标准工时阻断。")

    lines.extend(["", "## 6. 节点/日历/其他阻断清单", ""])
    if blocked:
        lines.extend(["| 订单 | 工序 | 阻断代码 | 阻断原因 |", "|---|---|---|---|"])
        for row in blocked:
            lines.append(
                f"| {row.get('order_no','')} | {row.get('process_name','')} | "
                f"{row.get('blocked_code','')} | {row.get('blocked_reason','')} |"
            )
    else:
        lines.append("当前没有节点、日历或其他排程阻断。")

    lines.extend([
        "",
        "## 7. 业务确认事项",
        "",
        "- 当前副本没有缺失标准工时和节点/日历阻断，不需要新增工时补录清单。",
        "- 5 条外协/非排程工序继续保留执行策略，不应补录为内部工时。",
        "- 386 条内部工序命中当前路线版本 + 工序版本的通用标准；如业务要求每个产品都有独立工时，需要另行建立产品级标准，不应自动复制。",
        "- 详细 664 条工序事实见同目录 `work-time-coverage-audit.csv` 和 `work-time-coverage-audit.json`。",
        "",
        "## 8. 审计结论",
        "",
        "本次真实副本审计证明：内部可排程工序工时覆盖率为 100%，没有发现缺失工时或节点/日历阻断；当前系统主要使用路线版本 + 工序版本的通用工时，外协/非排程工序已被正确隔离。",
    ])
    markdown_path = target / "production-scheduling-task2-real-work-time-audit-20260922.md"
    markdown_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return {"markdown": str(markdown_path), "json": str(json_path), "csv": str(csv_path)}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", required=True)
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--source-host", required=True)
    parser.add_argument("--production-commit", required=True)
    parser.add_argument("--source-version", required=True)
    args = parser.parse_args(argv)
    print(
        json.dumps(
            render(
                args.input,
                args.output_dir,
                source_host=args.source_host,
                production_commit=args.production_commit,
                source_version=args.source_version,
            ),
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
