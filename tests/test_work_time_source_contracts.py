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
    assert not offenders, "工时管理源码疑似存在中文乱码: " + "; ".join(offenders)


def test_work_time_page_is_composition_shell():
    page = Path("frontend/src/views/WorkTimePage.vue")
    source = page.read_text(encoding="utf-8")

    assert "WorkTimeStandardsPanel" in source
    assert "WorkTimeRecordsPanel" in source
    assert "WorkTimeAuditPanel" in source
    assert "WorkTimeReviewModal" in source
    assert len(source.splitlines()) <= 180


def test_work_time_batch_logic_lives_in_composable():
    composable = Path("frontend/src/composables/useRouteWorkTimeStandards.js")
    source = composable.read_text(encoding="utf-8")

    assert "useRouteWorkTimeStandards" in source
    assert "buildStandardRows" in source
    assert "validateStandardRows" in source
    assert "buildSavePayload" in source



def test_work_time_standard_modal_has_explicit_layout_contract():
    source = Path("frontend/src/views/work-time/WorkTimeStandardsPanel.vue").read_text(encoding="utf-8")

    assert 'class="modal route-standard-modal"' in source
    assert 'route-standard-modal {' in source
    assert 'width: min(1180px, calc(100vw - 48px));' in source
    assert 'route-standard-modal-body' in source
    assert 'standard-edit-table-wrap' in source
    assert 'route-standard-edit-table' in source
    assert 'position: sticky;' in source



def test_work_time_standard_modal_uses_body_teleport():
    source = Path("frontend/src/views/work-time/WorkTimeStandardsPanel.vue").read_text(encoding="utf-8")

    assert '<teleport to="body">' in source
    assert 'route-standard-modal-overlay' in source
    assert 'align-items: flex-start;' in source
    assert 'animation: none;' in source
    assert source.count('animation: none;') >= 2
    assert 'overscroll-behavior: contain;' in source



def test_work_time_record_modal_uses_body_teleport():
    source = Path("frontend/src/views/work-time/WorkTimeRecordsPanel.vue").read_text(encoding="utf-8")

    assert '<teleport to="body">' in source
    assert 'record-modal-overlay' in source
    assert 'record-modal-body' in source
    assert 'align-items: flex-start;' in source
    assert 'animation: none;' in source
    assert 'overscroll-behavior: contain;' in source



def test_work_time_record_entry_uses_order_search_and_standard_hint():
    source = Path("frontend/src/views/work-time/WorkTimeRecordsPanel.vue").read_text(encoding="utf-8")

    assert "订单号（搜索选择）" in source
    assert "api.domains.orders.listOrders" in source
    assert "availableProcesses" in source
    assert "standardStatus" in source
    assert "standard_missing" in source
    assert "缺标准工时" in source


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
