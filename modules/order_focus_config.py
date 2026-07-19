"""Shared constants for order completion focus control."""

COMPLETION_FOCUS_MODE_KEY = "completion_focus_mode"
COMPLETION_FOCUS_TAIL_PCT_KEY = "completion_focus_tail_pct"
COMPLETION_FOCUS_ENABLED_KEY = "completion_focus_enabled"

FOCUS_MODE_OFF = "off"
FOCUS_MODE_SOFT = "soft"
FOCUS_MODE_HARD = "hard"
COMPLETION_FOCUS_MODES = {FOCUS_MODE_OFF, FOCUS_MODE_SOFT, FOCUS_MODE_HARD}
DEFAULT_COMPLETION_FOCUS_MODE = FOCUS_MODE_SOFT
DEFAULT_COMPLETION_FOCUS_TAIL_PERCENT = 70

COMPLETION_FOCUS_MODE_OPTIONS = [
    {"value": FOCUS_MODE_OFF, "label": "\u5173\u95ed", "button_class": "btn-primary"},
    {"value": FOCUS_MODE_SOFT, "label": "\u8f6f\u63d0\u793a", "button_class": "btn-warning"},
    {"value": FOCUS_MODE_HARD, "label": "\u5f3a\u62e6\u622a", "button_class": "btn-danger"},
]
COMPLETION_FOCUS_EXCEPTION_REASONS = [
    "\u7f3a\u6599",
    "\u8bbe\u5907\u6545\u969c",
    "\u6025\u5355",
    "\u8fd4\u4fee",
    "\u4eba\u5458\u6280\u80fd\u9650\u5236",
    "\u5ba2\u6237\u63d2\u5355",
    "\u5176\u4ed6",
]
COMPLETION_FOCUS_BYPASS_PERMISSIONS = ["*", "orders:edit", "schedule:edit"]

COMPLETION_FOCUS_DEFAULT_SETTINGS = {
    COMPLETION_FOCUS_MODE_KEY: DEFAULT_COMPLETION_FOCUS_MODE,
    COMPLETION_FOCUS_TAIL_PCT_KEY: str(DEFAULT_COMPLETION_FOCUS_TAIL_PERCENT),
}

EVENT_SCAN_BLOCKED = "scan_blocked"
EVENT_SCAN_BYPASSED = "scan_bypassed"
EVENT_EXCEPTION_CREATED = "exception_created"
EVENT_EXCEPTION_CANCELLED = "exception_cancelled"
