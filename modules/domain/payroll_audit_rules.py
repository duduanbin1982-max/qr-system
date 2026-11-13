"""Deterministic audit rules for versioned payroll calculations."""

from collections import defaultdict
from datetime import timedelta

from modules.domain.production_time import parse_database_timestamp


PAYROLL_AUDIT_RULE_VERSION = "payroll-audit-v1"


def _timestamp(value):
    parsed = parse_database_timestamp(value)
    return parsed.replace(microsecond=0) if parsed is not None else None


def _payroll_month(value):
    parsed = _timestamp(value)
    if parsed is None:
        return None
    report_date = parsed.date()
    if parsed.hour < 7:
        report_date -= timedelta(days=1)
    return report_date.strftime("%Y-%m")


def _work_snapshot(row):
    return {
        "work_record_id": row.get("work_record_id", row.get("id")),
        "employee_id": row.get("user_id"),
        "employee_no": row.get("employee_no") or "",
        "employee_name": row.get("employee_name") or "",
        "order_id": row.get("order_id"),
        "order_no": row.get("order_no") or "",
        "process_id": row.get("process_id"),
        "process_name": row.get("process_name") or "",
        "work_type": row.get("work_type", row.get("type")) or "",
        "quantity": row.get("quantity"),
        "serial_no": str(row.get("serial_no") or "").strip(),
        "status": row.get("status") or "",
        "created_at": row.get("created_at") or "",
        "actual_completed_at": row.get("actual_completed_at") or "",
    }


def _finding(finding_type, severity, subject_type, subject_id, summary, facts):
    return {
        "finding_type": finding_type,
        "severity": severity,
        "subject_type": subject_type,
        "subject_id": int(subject_id),
        "rule_version": PAYROLL_AUDIT_RULE_VERSION,
        "snapshot": {"summary": summary, **facts},
    }


def _eligible_rows(work_records):
    return [row for row in work_records if (row.get("status") or "") != "rejected"]


def evaluate_payroll_audit(batch, work_records, employee_lines, historical_wages):
    """Return stable, explainable findings for one captured payroll calculation."""
    findings = []
    eligible = _eligible_rows(work_records)

    for row in eligible:
        if row.get("status") != "pending":
            continue
        subject_id = row.get("work_record_id", row.get("id"))
        snapshot = _work_snapshot(row)
        findings.append(_finding(
            "pending_approval_work", "blocking", "work_record", subject_id,
            f"报工记录 {subject_id} 在工资批次截止时仍待审批",
            {"work_record": snapshot, "cutoff_at": batch.get("source_cutoff_at") or ""},
        ))

    serial_groups = defaultdict(list)
    candidate_groups = defaultdict(list)
    for row in eligible:
        subject_id = row.get("work_record_id", row.get("id"))
        serial_no = str(row.get("serial_no") or "").strip()
        if serial_no:
            serial_groups[(row.get("order_id"), row.get("process_id"), serial_no)].append(row)

        effective_time = _timestamp(row.get("actual_completed_at")) or _timestamp(row.get("created_at"))
        if effective_time is not None:
            candidate_groups[(
                row.get("user_id"), row.get("order_id"), row.get("process_id"),
                row.get("work_type", row.get("type")), row.get("quantity"),
                effective_time.strftime("%Y-%m-%d %H:%M:%S"),
            )].append(row)

        actual_at = row.get("actual_completed_at")
        if actual_at:
            actual_month = _payroll_month(actual_at)
            recorded_month = _payroll_month(row.get("created_at"))
            if actual_month and recorded_month and actual_month != recorded_month:
                snapshot = _work_snapshot(row)
                findings.append(_finding(
                    "cross_period_work", "blocking", "work_record", subject_id,
                    f"报工实际完成于 {actual_month}，录入时间归属 {recorded_month}",
                    {
                        "work_record": snapshot,
                        "actual_payroll_month": actual_month,
                        "recorded_payroll_month": recorded_month,
                        "boundary_hour": 7,
                    },
                ))

    for (order_id, process_id, serial_no), rows in serial_groups.items():
        if len(rows) < 2:
            continue
        record_ids = sorted(int(row.get("work_record_id", row.get("id"))) for row in rows)
        for row in rows:
            subject_id = row.get("work_record_id", row.get("id"))
            findings.append(_finding(
                "duplicate_serial_work", "blocking", "work_record", subject_id,
                f"同订单、工序和序列号存在重复报工（记录 {', '.join(map(str, record_ids))}）",
                {
                    "order_id": order_id,
                    "order_no": row.get("order_no") or "",
                    "process_id": process_id,
                    "process_name": row.get("process_name") or "",
                    "serial_no": serial_no,
                    "work_record_ids": record_ids,
                    "work_record": _work_snapshot(row),
                },
            ))

    for key, rows in candidate_groups.items():
        if len(rows) < 2:
            continue
        record_ids = sorted(int(row.get("work_record_id", row.get("id"))) for row in rows)
        for row in rows:
            subject_id = row.get("work_record_id", row.get("id"))
            findings.append(_finding(
                "duplicate_work_candidate", "review", "work_record", subject_id,
                f"员工、订单、工序、类型、数量和实际时间完全相同（记录 {', '.join(map(str, record_ids))}）",
                {
                    "employee_id": key[0],
                    "order_id": key[1],
                    "process_id": key[2],
                    "work_type": key[3],
                    "quantity": key[4],
                    "effective_at": key[5],
                    "work_record_ids": record_ids,
                    "work_record": _work_snapshot(row),
                },
            ))

    for line in employee_lines:
        employee_id = line.get("employee_id")
        if employee_id is None:
            continue
        history = list(historical_wages.get(employee_id, ()))[:3]
        if len(history) < 3:
            continue
        values = sorted(int(item["payable_wage_cents"]) for item in history)
        median_twice_cents = values[1] * 2 if len(values) % 2 else values[1] + values[2]
        current_cents = int(line["payable_wage_cents"])
        delta_twice_cents = abs(current_cents * 2 - median_twice_cents)
        if delta_twice_cents < 100000 or 2 * delta_twice_cents < abs(median_twice_cents):
            continue
        findings.append(_finding(
            "high_payroll_deviation", "review", "employee", employee_id,
            "本期工资相对最近三个正式工资期间的中位数偏差至少 50%，且差额不少于 500 元",
            {
                "employee_id": employee_id,
                "employee_no": line.get("employee_no_snapshot") or "",
                "employee_name": line.get("employee_name_snapshot") or "",
                "payroll_month": batch.get("payroll_month") or "",
                "current_payable_cents": current_cents,
                "historical_periods": [
                    {
                        "payroll_month": item["payroll_month"],
                        "version": item["version"],
                        "payable_wage_cents": int(item["payable_wage_cents"]),
                    }
                    for item in history
                ],
                "historical_median_twice_cents": median_twice_cents,
                "difference_twice_cents": delta_twice_cents,
                "relative_threshold_basis_points": 5000,
                "absolute_threshold_cents": 50000,
            },
        ))

    findings.sort(key=lambda item: (
        item["finding_type"], item["subject_type"], item["subject_id"]
    ))
    return findings
