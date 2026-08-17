"""Cross-cutting policy for safe audit-event details.

Audit details are evidence, not a copy of an HTTP request.  This module keeps
the first-line redaction rule in one place while callers migrate to structured
event payloads.
"""

import json
import re
from collections.abc import Mapping, Sequence


REDACTED_VALUE = "[REDACTED]"
AUDIT_MIN_RETENTION_DAYS = 1095

_SENSITIVE_KEY_RE = re.compile(
    r"(?:password|passwd|token|secret|api[_-]?key|authorization|cookie|"
    r"private[_-]?key|access[_-]?key|refresh[_-]?token|file[_-]?data|"
    r"phone|email|address|contact)",
    re.IGNORECASE,
)

_SENSITIVE_KEY_VALUE_RE = re.compile(
    r"(?P<key>[\"']?[A-Za-z0-9_.-]*(?:password|passwd|token|secret|"
    r"api[_-]?key|authorization|cookie|private[_-]?key|access[_-]?key|"
    r"refresh[_-]?token|file[_-]?data|phone|email|address|contact)"
    r"[A-Za-z0-9_.-]*[\"']?)"
    r"(?P<separator>\s*[:=]\s*)"
    r"(?P<value>\"[^\"]*\"|'[^']*'|[^,;}\]\s]+)",
    re.IGNORECASE,
)


def is_sensitive_key(key) -> bool:
    """Return whether a field name must never carry its value into audit logs."""

    return bool(_SENSITIVE_KEY_RE.search(str(key or "")))


def _sanitize_value(value):
    if isinstance(value, Mapping):
        return {
            str(key): REDACTED_VALUE if is_sensitive_key(key) else _sanitize_value(item)
            for key, item in value.items()
        }
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return [_sanitize_value(item) for item in value]
    if isinstance(value, (bytes, bytearray)):
        return REDACTED_VALUE
    return value


def sanitize_audit_detail(detail) -> str:
    """Redact sensitive values while preserving existing safe detail strings.

    Mapping/list inputs are serialized as stable JSON.  Legacy string details
    are supported during migration by masking common ``key=value`` and
    ``key: value`` forms.
    """

    if detail is None:
        return ""
    if isinstance(detail, (Mapping, list, tuple)):
        return json.dumps(
            _sanitize_value(detail),
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            default=str,
        )

    text = str(detail)

    def replace(match):
        value = match.group("value")
        quote = value[0] if value[:1] in ("'", '"') else ""
        return (
            f"{match.group('key')}{match.group('separator')}"
            f"{quote}{REDACTED_VALUE}{quote}"
        )

    return _SENSITIVE_KEY_VALUE_RE.sub(replace, text)
