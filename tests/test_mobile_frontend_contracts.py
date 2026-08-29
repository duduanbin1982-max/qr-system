import re
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
MOBILE_DIR = PROJECT_ROOT / "public" / "js" / "mobile"

BUSINESS_MOBILE_FILES = [
    MOBILE_DIR / "mobile-order.js",
    MOBILE_DIR / "inspection.js",
    MOBILE_DIR / "mobile-auth.js",
    MOBILE_DIR / "mobile-init.js",
    MOBILE_DIR / "mobile-quality-evaluation.js",
]


def _script_index(html, script_name):
    content = html.read_text(encoding="utf-8")
    index = content.find(script_name)
    assert index != -1, f"{script_name} is not loaded by {html.name}"
    return index


def test_mobile_business_scripts_use_api_facade_instead_of_direct_fetch():
    offenders = []
    for path in BUSINESS_MOBILE_FILES:
        content = path.read_text(encoding="utf-8")
        if "fetch(API" in content or "fetch('/api" in content or 'fetch("/api' in content:
            offenders.append(path.relative_to(PROJECT_ROOT).as_posix())

    assert offenders == []


def test_mobile_api_facade_is_loaded_before_business_scripts():
    mobile_html = PROJECT_ROOT / "public" / "mobile.html"
    inspection_html = PROJECT_ROOT / "public" / "mobile_inspection.html"

    assert _script_index(mobile_html, "mobile-api.js") < _script_index(mobile_html, "mobile-auth.js")
    assert _script_index(mobile_html, "mobile-api.js") < _script_index(mobile_html, "mobile-order.js")
    assert _script_index(mobile_html, "mobile-api.js") < _script_index(mobile_html, "mobile-init.js")
    assert _script_index(inspection_html, "mobile-api.js") < _script_index(inspection_html, "inspection.js")


def test_mobile_auth_uses_same_origin_cookie_without_js_token_handoff():
    api_script = (MOBILE_DIR / "mobile-api.js").read_text(encoding="utf-8")
    auth_script = (MOBILE_DIR / "mobile-auth.js").read_text(encoding="utf-8")
    utils_script = (MOBILE_DIR / "mobile-utils.js").read_text(encoding="utf-8")
    order_script = (MOBILE_DIR / "mobile-order.js").read_text(encoding="utf-8")
    inspection_script = (MOBILE_DIR / "inspection.js").read_text(encoding="utf-8")

    assert 'credentials: "same-origin"' in api_script
    assert "Authorization" not in api_script
    assert "Bearer " not in api_script
    assert "function token(" not in api_script
    assert "document.cookie" not in api_script

    assert "token: merged.token" not in auth_script
    assert "setItem('iq_token'" not in auth_script
    assert "delete merged.token" in auth_script
    assert "delete u.token" in utils_script

    assert 'setItem("iq_token"' not in order_script
    assert "token()" not in order_script
    assert "document.cookie" not in order_script

    assert "function getToken" not in inspection_script
    assert "getItem('iq_token')" not in inspection_script
    assert "document.cookie" not in inspection_script


def test_mobile_api_error_protocol_exposes_consistent_domain_context():
    api_script = (MOBILE_DIR / "mobile-api.js").read_text(encoding="utf-8")

    for field in (
        "error.code",
        "error.status",
        "error.domainCode",
        "error.action",
        "error.details",
        "error.payload",
    ):
        assert field in api_script
    assert 'response.status === 409 ? "数据冲突"' in api_script
    assert "window.handleAuthExpired" in api_script


def _asset_version(content, script_name):
    match = re.search(rf"{re.escape(script_name)}\?v=(\d+)", content)
    assert match, f"{script_name} must be cache-busted with ?v="
    return int(match.group(1))


def test_mobile_quality_evaluation_assets_are_cache_busted_and_network_first():
    mobile_html = (PROJECT_ROOT / "public" / "mobile.html").read_text(encoding="utf-8")
    inspection_html = (
        PROJECT_ROOT / "public" / "mobile_inspection.html"
    ).read_text(encoding="utf-8")
    sw_content = (PROJECT_ROOT / "public" / "sw.js").read_text(encoding="utf-8")

    assert _asset_version(mobile_html, "mobile.css") >= 19
    assert _asset_version(mobile_html, "mobile-api.js") >= 9
    assert _asset_version(mobile_html, "mobile-utils.js") >= 31
    assert _asset_version(mobile_html, "mobile-auth.js") >= 30
    assert _asset_version(mobile_html, "mobile-order.js") >= 43
    assert _asset_version(mobile_html, "mobile-init.js") >= 35
    assert _asset_version(mobile_html, "mobile-quality-evaluation.js") >= 8
    assert _asset_version(inspection_html, "mobile-api.js") >= 9
    assert _asset_version(inspection_html, "inspection.js") >= 9
    assert _asset_version(mobile_html, "mobile-api.js") == _asset_version(inspection_html, "mobile-api.js")
    cache_match = re.search(r'CACHE_REVISION = "(\d{8}\.\d+)"', sw_content)
    assert cache_match
    assert 'CACHE_NAME = "qr-system-cache-" + CACHE_REVISION' in sw_content
    assert 'url.pathname.startsWith("/js/mobile/")' in sw_content
    assert "Mobile business JS: network-first" in sw_content
    for asset in (
        "/css/mobile.css?v=19",
        "/css/inspection.css?v=3",
        "/js/mobile/mobile-api.js?v=9",
        "/js/mobile/mobile-utils.js?v=31",
        "/js/mobile/mobile-auth.js?v=31",
        "/js/mobile/mobile-scan.js?v=27",
        "/js/mobile/mobile-order.js?v=43",
        "/js/mobile/mobile-quality-evaluation.js?v=8",
        "/js/mobile/mobile-init.js?v=36",
        "/js/mobile/inspection.js?v=9",
    ):
        assert '"' + asset + '"' in sw_content


def test_mobile_uses_independent_quality_evaluation_center():
    mobile_html = (PROJECT_ROOT / "public" / "mobile.html").read_text(encoding="utf-8")
    order_script = (MOBILE_DIR / "mobile-order.js").read_text(encoding="utf-8")

    assert 'id="quality-evaluation-entry"' in mobile_html
    assert 'id="s-quality-evaluation"' in mobile_html
    assert "handoffPending" not in order_script
    assert "openHandoffReview" not in order_script


def test_mobile_process_order_selection_is_wired():
    order_script = (MOBILE_DIR / "mobile-order.js").read_text(encoding="utf-8")

    assert "requires_process_selection" in order_script
    assert "normal_reportable" in order_script
    assert "max_report_quantity" in order_script
    assert "selectReportProcess" in order_script


def test_mobile_camera_lifecycle_invalidates_pending_requests_and_releases_on_leave():
    scan_script = (MOBILE_DIR / "mobile-scan.js").read_text(encoding="utf-8")
    init_script = (MOBILE_DIR / "mobile-init.js").read_text(encoding="utf-8")
    auth_script = (MOBILE_DIR / "mobile-auth.js").read_text(encoding="utf-8")

    assert "cameraRequestToken" in scan_script
    assert "releaseCamResources" in scan_script
    assert "stopCameraStream(stream)" in scan_script
    assert "requestToken !== cameraRequestToken" in scan_script
    assert "window.addEventListener('pagehide'" in init_script
    assert "releaseCamResources();" in auth_script


def test_mobile_photo_decode_releases_blob_urls_and_ignores_stale_images():
    scan_script = (MOBILE_DIR / "mobile-scan.js").read_text(encoding="utf-8")

    assert "photoRequestToken" in scan_script
    assert "photoObjectUrl" in scan_script
    assert "URL.revokeObjectURL(photoObjectUrl)" in scan_script
    assert "requestToken !== photoRequestToken" in scan_script
    assert "function releasePhotoResources()" in scan_script


def test_mobile_inspection_selects_and_submits_by_stable_process_id_without_duplicate_submit():
    inspection_script = (MOBILE_DIR / "inspection.js").read_text(encoding="utf-8")

    assert "function processIdOf(process)" in inspection_script
    assert "currentProcessId === processId" in inspection_script
    assert "getAttribute('data-process-id') === currentProcessId" in inspection_script
    assert "if (submissionState === 'submitting') return;" in inspection_script
    assert "submissionState = 'submitting';" in inspection_script
    assert "工序缺少稳定标识" in inspection_script


def test_mobile_offline_copy_and_write_protocol_do_not_promise_background_sync():
    init_script = (MOBILE_DIR / "mobile-init.js").read_text(encoding="utf-8")
    api_script = (MOBILE_DIR / "mobile-api.js").read_text(encoding="utf-8")
    sw_content = (PROJECT_ROOT / "public" / "sw.js").read_text(encoding="utf-8")

    assert "数据将在恢复网络后同步" not in init_script
    assert "业务提交不会保存，请恢复网络后重新提交" in init_script
    assert "业务提交未保存，请恢复网络后重新提交" in api_script
    assert 'domainCode = "offline"' in api_script
    assert 'code: "offline"' in sw_content
    assert 'action: "retry_online"' in sw_content


def test_mobile_controlled_serial_backfill_is_wired():
    mobile_html = (PROJECT_ROOT / "public" / "mobile.html").read_text(encoding="utf-8")
    order_script = (MOBILE_DIR / "mobile-order.js").read_text(encoding="utf-8")

    assert 'id="serial-backfill-fields"' in mobile_html
    assert "serial_backfill_reportable" in order_script
    assert "补报申请已提交" in order_script
    assert "申请时间: 系统自动记录" in order_script
    assert "backfill-completed-at" not in mobile_html
    assert "backfill-reason" not in mobile_html


def test_mobile_backfill_selection_never_uses_auto_report():
    order_script = (MOBILE_DIR / "mobile-order.js").read_text(encoding="utf-8")

    assert "canAutoReportSelectedProcess()" in order_script
    assert "reportMode === 'auto' && !serialBackfillMode" in order_script
    assert "isNormalReportProcessSelectable(getSelectedReportProcess())" in order_script
    assert "focusFirstBackfillCandidate()" in order_script
    assert "window.confirm" in order_script


def test_mobile_process_list_is_explicit_and_numbered_from_one():
    order_script = (MOBILE_DIR / "mobile-order.js").read_text(encoding="utf-8")
    mobile_css = (PROJECT_ROOT / "public" / "css" / "mobile.css").read_text(encoding="utf-8")

    assert "选择报工工序" in order_script
    assert "data-backfill-candidate" in order_script
    assert "index + 1" in order_script
    assert '<button type="button" class="proc-item ' in order_script
    assert "订单进度：已完成" in order_script
    assert ".order-body::-webkit-scrollbar{width:6px}" in mobile_css
    assert ".order-body>*{flex-shrink:0}" in mobile_css
    assert ".proc-card{background:#fff;border-radius:var(--radius-lg);overflow:visible" in mobile_css


def test_mobile_active_position_selection_is_wired():
    mobile_html = (PROJECT_ROOT / "public" / "mobile.html").read_text(encoding="utf-8")
    api_script = (MOBILE_DIR / "mobile-api.js").read_text(encoding="utf-8")
    auth_script = (MOBILE_DIR / "mobile-auth.js").read_text(encoding="utf-8")
    order_script = (MOBILE_DIR / "mobile-order.js").read_text(encoding="utf-8")

    assert 'id="active-position-select"' in mobile_html
    assert 'id="active-position-hint"' in mobile_html
    assert "/auth/active-position" in api_script
    assert "changeActivePosition" in auth_script
    assert "available_positions" in auth_script
    assert "position_reportable" in order_script
    assert "process_selection_source" in order_script
    assert "changeOrderActivePosition" in order_script
    assert "serial_backfill_selection_source" in order_script


def test_mobile_quality_center_paginates_and_ignores_stale_responses():
    quality_script = (MOBILE_DIR / "mobile-quality-evaluation.js").read_text(encoding="utf-8")
    auth_script = (MOBILE_DIR / "mobile-auth.js").read_text(encoding="utf-8")

    assert "QUALITY_PAGE_SIZE = 50" in quality_script
    assert "qualityRequestSeq" in quality_script
    assert "isCurrentQualityRequest" in quality_script
    assert "load-more-quality-tasks" in quality_script
    assert "load-more-quality-mine" in quality_script
    assert "recordPages" not in quality_script
    assert "appealPages" not in quality_script
    assert "var _logoutBusy = false" in auth_script
    assert "服务端注销未确认，本地已退出，请检查网络" in auth_script
    assert "Promise.race([settled, timeout])" in auth_script


def test_mobile_order_rendering_is_split_into_state_selection_markup_and_binding_steps():
    order_script = (MOBILE_DIR / "mobile-order.js").read_text(encoding="utf-8")

    for helper in (
        "buildOrderHeader",
        "resolveOrderProcessSelection",
        "buildOrderProcessSection",
        "bindOrderInteractions",
    ):
        assert "function " + helper in order_script
    assert "b.innerHTML = buildOrderHeader(o, qty) + buildOrderProcessSection(o, qty, processes, selection);" in order_script
    assert "bindOrderInteractions(b);" in order_script
    render_body = order_script.split("function renderOrder(", 1)[1].split("function changeOrderActivePosition", 1)[0]
    assert render_body.count("function ") == 0


def test_mobile_quality_evaluation_b_workflow_is_wired():
    mobile_html = (PROJECT_ROOT / "public" / "mobile.html").read_text(encoding="utf-8")
    order_script = (MOBILE_DIR / "mobile-order.js").read_text(encoding="utf-8")
    quality_script = (MOBILE_DIR / "mobile-quality-evaluation.js").read_text(encoding="utf-8")

    assert 'data-quality-view="mine"' in mobile_html
    assert "quality_evaluation_auto_open" in order_script
    assert "openQualityEvaluationCenter" in order_script
    assert "dimension_scores" in quality_script
    assert "不适用" in quality_script
    assert "critical_issue_tags" in quality_script
    assert "quality-critical-tag" in quality_script
    assert "skipQualityEvaluationTask" in quality_script
    assert "createQualityEvaluationAppeal" in quality_script
    assert "target_user_name" not in quality_script
