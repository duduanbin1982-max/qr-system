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
