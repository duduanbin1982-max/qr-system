"""Shared validation for staged versioned-master-data cutovers."""

import os


TRUTHY_VALUES = frozenset({"1", "true", "yes", "on"})


def environment_flag(name, environ=None):
    """Parse a boolean environment value using the application's convention."""
    source = os.environ if environ is None else environ
    return str(source.get(name, "false")).strip().lower() in TRUTHY_VALUES


def get_versioning_flags(names, environ=None):
    """Return an ordered flag mapping for one versioned domain."""
    return {name: environment_flag(name, environ=environ) for name in names}


def validate_versioning_flags(
    flags,
    *,
    label,
    query_key,
    audit_key,
    write_key,
    legacy_blocked_key,
):
    """Enforce the common query -> audit -> write -> Legacy cutover order."""
    values = dict(flags)
    query_enabled = bool(values.get(query_key))
    audit_enabled = bool(values.get(audit_key))
    write_enabled = bool(values.get(write_key))
    legacy_blocked = bool(values.get(legacy_blocked_key))
    violations = []
    if audit_enabled and not query_enabled:
        violations.append("兼容双读审计要求先开启版本化查询")
    if write_enabled and not query_enabled:
        violations.append("版本化写入要求先开启版本化查询")
    if legacy_blocked and not write_enabled:
        violations.append("阻断 Legacy 写入要求先开启版本化写入")
    if violations:
        raise RuntimeError(f"{label}功能开关组合无效：" + "；".join(violations))
    return values
