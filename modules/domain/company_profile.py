"""Pure validation and history-redaction policy for company profiles."""

import re

from modules.domain.errors import ConflictError, ValidationError


COMPANY_PROFILE_FIELDS = (
    "company_name",
    "contact",
    "phone",
    "address",
    "description",
)
COMPANY_PROFILE_LIMITS = {
    "company_name": 200,
    "contact": 100,
    "phone": 50,
    "address": 500,
    "description": 2000,
}
SENSITIVE_HISTORY_FIELDS = frozenset({"contact", "phone", "address"})
COMPANY_PROFILE_RETENTION_YEARS = 3

_PHONE_PATTERN = re.compile(r"^[0-9+()\-\s./#]*$")


class CompanyProfileStaleError(ConflictError):
    code = "COMPANY_PROFILE_STALE"

    def to_payload(self):
        payload = super().to_payload()
        payload["action"] = "reload_company_profile"
        return payload


def normalize_company_profile_changes(values):
    """Validate a partial update and return canonical string values."""
    if not isinstance(values, dict):
        raise ValidationError("公司资料必须是对象")
    unknown = sorted(set(values) - set(COMPANY_PROFILE_FIELDS))
    if unknown:
        raise ValidationError(
            "包含不支持的公司资料字段",
            details={"fields": unknown},
        )

    normalized = {}
    for field in COMPANY_PROFILE_FIELDS:
        if field not in values:
            continue
        value = values[field]
        if not isinstance(value, str):
            raise ValidationError(
                f"{field} 必须是字符串",
                details={"field": field},
            )
        value = value.strip()
        if len(value) > COMPANY_PROFILE_LIMITS[field]:
            raise ValidationError(
                f"{field} 最多 {COMPANY_PROFILE_LIMITS[field]} 个字符",
                details={"field": field, "max_length": COMPANY_PROFILE_LIMITS[field]},
            )
        if field == "phone" and value and not _PHONE_PATTERN.fullmatch(value):
            raise ValidationError(
                "联系电话格式无效",
                details={"field": "phone"},
            )
        normalized[field] = value
    return normalized


def changed_company_profile_fields(current, updates):
    return [
        field
        for field in COMPANY_PROFILE_FIELDS
        if field in updates and updates[field] != (current.get(field) or "")
    ]


def redact_company_profile_revision(revision, allow_sensitive_history=False):
    result = dict(revision)
    if allow_sensitive_history:
        result["sensitive_fields_redacted"] = False
        return result
    for field in SENSITIVE_HISTORY_FIELDS:
        result[field] = "***" if result.get(field) else ""
    result["sensitive_fields_redacted"] = True
    return result
