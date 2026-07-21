from pathlib import Path


WORK_TIME_SOURCE_FILES = [
    Path("frontend/src/views/WorkTimePage.vue"),
    Path("frontend/src/views/work-time/WorkTimeStandardsPanel.vue"),
    Path("frontend/src/views/work-time/WorkTimeRecordsPanel.vue"),
    Path("frontend/src/views/work-time/WorkTimeAuditPanel.vue"),
    Path("frontend/src/views/work-time/WorkTimeReviewModal.vue"),
    Path("frontend/src/composables/useRouteWorkTimeStandards.js"),
    Path("modules/services/work_time_service.py"),
    Path("modules/routes/work_time.py"),
]


def test_work_time_source_has_no_replacement_question_text():
    offenders = []
    for path in WORK_TIME_SOURCE_FILES:
        for line_no, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            if "???" in line:
                offenders.append(f"{path}:{line_no}:{line.strip()}")
    assert not offenders, "??????????????: " + "; ".join(offenders)


def test_work_time_backend_records_have_snapshots_and_daily_summary_contracts():
    service = Path("modules/services/work_time_service.py").read_text(encoding="utf-8")
    repository = Path("modules/repositories/work_time_repository.py").read_text(encoding="utf-8")
    stats = Path("modules/services/stats_service.py").read_text(encoding="utf-8")

    assert "find_order_process" in service
    assert "standard_missing" in service
    assert "route_name" in service
    assert "product_code" in service
    assert "daily_summary" in repository
    assert "work_time_summary" in stats
