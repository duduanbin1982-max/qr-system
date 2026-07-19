from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def _read(relative_path):
    return (PROJECT_ROOT / relative_path).read_text(encoding="utf-8")


def test_performance_page_uses_dedicated_modal_components():
    content = _read(Path("frontend/src/views/PerformancePage.vue"))

    for component in [
        "PerformanceDetailModal",
        "PerformanceReviewModal",
        "PerformancePlanModal",
    ]:
        assert component in content

    assert ':score="selectedScore"' in content
    assert ':rules="rules"' in content
    assert ':form="reviewForm"' in content
    assert ':form="planForm"' in content
    assert "detailValue(" not in content
    assert "weight(" not in content


def test_performance_modal_state_is_returned_by_composable():
    content = _read(Path("frontend/src/composables/usePerformanceModals.js"))

    for binding in [
        "detailModal",
        "reviewModal",
        "planModal",
        "selectedScore",
        "reviewForm",
        "planForm",
        "saveReviewForm",
        "savePlanForm",
    ]:
        assert binding in content


def test_performance_detail_modal_owns_score_detail_helpers():
    content = _read(Path("frontend/src/views/performance/PerformanceDetailModal.vue"))

    assert "score_details" in content
    assert "detailValue(key)" in content
    assert "weight(key)" in content
    assert "inspection_failed_qty" in content


def test_handoff_confirmation_refreshes_all_performance_lists():
    content = _read(Path("frontend/src/composables/usePerformancePageData.js"))

    assert "async function refreshPerformancePageData()" in content
    assert "await Promise.all([loadPlans(), loadHandoffReviews()])" in content
    assert "async function confirmHandoff" in content
    assert "await refreshPerformancePageData()" in content



def test_performance_page_exposes_position_filter_and_position_scope():
    content = _read(Path("frontend/src/views/PerformancePage.vue"))
    table = _read(Path("frontend/src/views/performance/PerformanceScoreTable.vue"))
    detail = _read(Path("frontend/src/views/performance/PerformanceDetailModal.vue"))
    data = _read(Path("frontend/src/composables/usePerformancePageData.js"))

    assert 'v-model="positionId"' in content
    assert '全部岗位' in content
    assert 'positionOptions' in content
    assert 'position_id: positionId.value' in data
    assert '岗位排名' in table
    assert '岗位最高产量' in table
    assert 'positionMaxOutput(row)' in table
    assert '岗位内排名' in detail
    assert 'position_max_output' in detail
