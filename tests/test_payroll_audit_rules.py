from modules.domain.payroll_audit_rules import (
    PAYROLL_AUDIT_RULE_VERSION,
    evaluate_payroll_audit,
)


def _work(work_record_id, **overrides):
    return {
        "work_record_id": work_record_id,
        "user_id": 7,
        "employee_no": "E-7",
        "employee_name": "测试员工",
        "order_id": 11,
        "order_no": "ORD-11",
        "process_id": 13,
        "process_name": "组装",
        "work_type": "normal",
        "status": "approved",
        "quantity": 4,
        "serial_no": "",
        "created_at": "2026-10-02 08:00:00",
        "actual_completed_at": "",
        **overrides,
    }


def _batch(**overrides):
    return {
        "payroll_month": "2026-10",
        "source_cutoff_at": "2026-11-01 12:00:00",
        **overrides,
    }


def test_pending_approval_is_blocking_and_rejected_work_is_ignored():
    findings = evaluate_payroll_audit(
        _batch(),
        [_work(1, status="pending"), _work(2, status="rejected")],
        [],
        {},
    )

    assert [(item["finding_type"], item["subject_id"], item["severity"]) for item in findings] == [
        ("pending_approval_work", 1, "blocking"),
    ]
    assert findings[0]["rule_version"] == PAYROLL_AUDIT_RULE_VERSION
    assert findings[0]["snapshot"]["work_record"]["status"] == "pending"
    assert findings[0]["snapshot"]["cutoff_at"] == "2026-11-01 12:00:00"


def test_duplicate_serial_and_exact_work_candidate_are_separate_rules():
    findings = evaluate_payroll_audit(
        _batch(),
        [
            _work(2, serial_no=" SN-1 "),
            _work(1, serial_no="SN-1", actual_completed_at="2026-10-02 08:00:00.900"),
        ],
        [],
        {},
    )

    assert [(item["finding_type"], item["subject_id"], item["severity"]) for item in findings] == [
        ("duplicate_serial_work", 1, "blocking"),
        ("duplicate_serial_work", 2, "blocking"),
        ("duplicate_work_candidate", 1, "review"),
        ("duplicate_work_candidate", 2, "review"),
    ]
    assert findings[0]["snapshot"]["work_record_ids"] == [1, 2]
    assert findings[2]["snapshot"]["effective_at"] == "2026-10-02 08:00:00"


def test_duplicate_candidate_requires_identical_fields_and_second_level_time():
    findings = evaluate_payroll_audit(
        _batch(),
        [
            _work(1, actual_completed_at="2026-10-02 08:00:00.100"),
            _work(2, actual_completed_at="2026-10-02 08:00:00.900"),
            _work(3, quantity=5, actual_completed_at="2026-10-02 08:00:00.100"),
            _work(4, status="rejected", actual_completed_at="2026-10-02 08:00:00.100"),
        ],
        [],
        {},
    )

    assert [(item["finding_type"], item["subject_id"]) for item in findings] == [
        ("duplicate_work_candidate", 1),
        ("duplicate_work_candidate", 2),
    ]


def test_cross_period_rule_uses_the_seven_am_reporting_boundary():
    findings = evaluate_payroll_audit(
        _batch(),
        [
            _work(1, actual_completed_at="2026-10-01 06:59:59"),
            _work(2, actual_completed_at="2026-10-01 07:00:00"),
        ],
        [],
        {},
    )

    cross_period = [item for item in findings if item["finding_type"] == "cross_period_work"]
    assert [(item["subject_id"], item["severity"]) for item in cross_period] == [(1, "blocking")]
    assert cross_period[0]["snapshot"]["actual_payroll_month"] == "2026-09"
    assert cross_period[0]["snapshot"]["recorded_payroll_month"] == "2026-10"
    assert cross_period[0]["snapshot"]["boundary_hour"] == 7


def test_cross_period_rule_normalizes_explicit_offsets_to_production_time():
    findings = evaluate_payroll_audit(
        _batch(),
        [
            _work(
                1,
                created_at="2026-10-01 08:00:00",
                actual_completed_at="2026-09-30T23:30:00Z",
            ),
        ],
        [],
        {},
    )

    assert not [item for item in findings if item["finding_type"] == "cross_period_work"]


def test_high_payroll_deviation_uses_three_formal_periods_and_both_thresholds():
    history = {
        7: [
            {"payroll_month": "2026-09", "version": 1, "payable_wage_cents": 100000},
            {"payroll_month": "2026-08", "version": 1, "payable_wage_cents": 100000},
            {"payroll_month": "2026-07", "version": 1, "payable_wage_cents": 100000},
        ]
    }
    finding = evaluate_payroll_audit(
        _batch(),
        [],
        [{"employee_id": 7, "employee_name_snapshot": "测试员工", "payable_wage_cents": 150000}],
        history,
    )

    assert len(finding) == 1
    assert finding[0]["finding_type"] == "high_payroll_deviation"
    assert finding[0]["severity"] == "review"
    assert finding[0]["snapshot"]["historical_median_twice_cents"] == 200000
    assert finding[0]["snapshot"]["difference_twice_cents"] == 100000

    below_absolute = evaluate_payroll_audit(
        _batch(),
        [],
        [{"employee_id": 7, "employee_name_snapshot": "测试员工", "payable_wage_cents": 149999}],
        history,
    )
    assert below_absolute == []


def test_high_payroll_deviation_requires_three_comparable_periods():
    findings = evaluate_payroll_audit(
        _batch(),
        [],
        [{"employee_id": 7, "payable_wage_cents": 1000000}],
        {7: [{"payroll_month": "2026-09", "version": 1, "payable_wage_cents": 100000}]},
    )

    assert findings == []
