import re
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
MOBILE_DIR = PROJECT_ROOT / "public" / "js" / "mobile"

BUSINESS_MOBILE_FILES = [
    MOBILE_DIR / "mobile-order.js",
    MOBILE_DIR / "inspection.js",
    MOBILE_DIR / "mobile-auth.js",
    MOBILE_DIR / "mobile-init.js",
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


def test_mobile_api_facade_keeps_backend_error_messages_visible():
    api_content = (MOBILE_DIR / "mobile-api.js").read_text(encoding="utf-8")
    auth_content = (MOBILE_DIR / "mobile-auth.js").read_text(encoding="utf-8")

    assert "payload && payload.error" in api_content
    assert "e && e.message" in auth_content



def _asset_version(content, script_name):
    match = re.search(rf"{re.escape(script_name)}\?v=(\d+)", content)
    assert match, f"{script_name} must be cache-busted with ?v="
    return int(match.group(1))


def test_mobile_handoff_review_is_blocking_and_resumable():
    order_content = (MOBILE_DIR / "mobile-order.js").read_text(encoding="utf-8")
    init_content = (MOBILE_DIR / "mobile-init.js").read_text(encoding="utf-8")
    utils_content = (MOBILE_DIR / "mobile-utils.js").read_text(encoding="utf-8")

    assert "handleReportHandoffReview(body, d || {})" in order_content
    assert "openHandoffReview(response && response.handoff_pending, { afterClose: finishReport })" in order_content
    assert "请先完成上一工序交接评价" in order_content
    assert "show('handoff')" in order_content
    assert "show('order')" in order_content
    assert "closeHandoffModal('submitted')" in order_content
    assert "closeHandoffModal('skipped')" in init_content
    assert "handoffAfterClose" in utils_content


def test_mobile_handoff_assets_are_cache_busted_and_network_first():
    mobile_html = (PROJECT_ROOT / "public" / "mobile.html").read_text(encoding="utf-8")
    sw_content = (PROJECT_ROOT / "public" / "sw.js").read_text(encoding="utf-8")

    assert _asset_version(mobile_html, "mobile-utils.js") >= 27
    assert _asset_version(mobile_html, "mobile-order.js") >= 32
    assert _asset_version(mobile_html, "mobile-init.js") >= 29
    cache_match = re.search(r'CACHE_NAME = "qr-system-v3\.(\d+)"', sw_content)
    assert cache_match and int(cache_match.group(1)) >= 5
    assert 'url.pathname.startsWith("/js/mobile/")' in sw_content
    assert "Mobile business JS: network-first" in sw_content


def test_mobile_handoff_review_has_dedicated_screen():
    mobile_html = (PROJECT_ROOT / "public" / "mobile.html").read_text(encoding="utf-8")
    css_content = (PROJECT_ROOT / "public" / "css" / "mobile.css").read_text(encoding="utf-8")

    assert 'id="s-handoff"' in mobile_html
    assert "handoff-screen" in mobile_html
    assert "handoff-tip" in mobile_html
    assert ".handoff-screen" in css_content
    assert "z-index:10000" in css_content
