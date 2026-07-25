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


def _asset_version(content, script_name):
    match = re.search(rf"{re.escape(script_name)}\?v=(\d+)", content)
    assert match, f"{script_name} must be cache-busted with ?v="
    return int(match.group(1))


def test_mobile_quality_evaluation_assets_are_cache_busted_and_network_first():
    mobile_html = (PROJECT_ROOT / "public" / "mobile.html").read_text(encoding="utf-8")
    sw_content = (PROJECT_ROOT / "public" / "sw.js").read_text(encoding="utf-8")

    assert _asset_version(mobile_html, "mobile-utils.js") >= 27
    assert _asset_version(mobile_html, "mobile-order.js") >= 36
    assert _asset_version(mobile_html, "mobile-init.js") >= 31
    assert _asset_version(mobile_html, "mobile-quality-evaluation.js") >= 2
    cache_match = re.search(r'CACHE_NAME = "qr-system-v3\.(\d+)"', sw_content)
    assert cache_match and int(cache_match.group(1)) >= 5
    assert 'url.pathname.startsWith("/js/mobile/")' in sw_content
    assert "Mobile business JS: network-first" in sw_content


def test_mobile_uses_independent_quality_evaluation_center():
    mobile_html = (PROJECT_ROOT / "public" / "mobile.html").read_text(encoding="utf-8")
    order_script = (MOBILE_DIR / "mobile-order.js").read_text(encoding="utf-8")

    assert 'id="quality-evaluation-entry"' in mobile_html
    assert 'id="s-quality-evaluation"' in mobile_html
    assert "handoffPending" not in order_script
    assert "openHandoffReview" not in order_script


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
