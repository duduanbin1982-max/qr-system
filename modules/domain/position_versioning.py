"""Pure policy for immutable position revisions and lifecycle commands."""

from math import isfinite

from modules.domain import evidence_protocol
from modules.domain.errors import ConflictError, NotFoundError, ValidationError


STATUS_DRAFT = "draft"
STATUS_PENDING_APPROVAL = "pending_approval"
STATUS_PUBLISHED = "published"
STATUS_SUPERSEDED = "superseded"
STATUS_REJECTED = "rejected"
STATUS_CANCELLED = "cancelled"
STATUS_RETIRED = "retired"

VERSION_STATUSES = frozenset(
    {
        STATUS_DRAFT,
        STATUS_PENDING_APPROVAL,
        STATUS_PUBLISHED,
        STATUS_SUPERSEDED,
        STATUS_REJECTED,
        STATUS_CANCELLED,
        STATUS_RETIRED,
    }
)

VERSION_TRANSITIONS = {
    STATUS_DRAFT: frozenset(
        {STATUS_DRAFT, STATUS_PENDING_APPROVAL, STATUS_CANCELLED}
    ),
    STATUS_PENDING_APPROVAL: frozenset(
        {STATUS_PENDING_APPROVAL, STATUS_PUBLISHED, STATUS_REJECTED}
    ),
    STATUS_PUBLISHED: frozenset(
        {STATUS_PUBLISHED, STATUS_SUPERSEDED, STATUS_RETIRED}
    ),
    STATUS_SUPERSEDED: frozenset({STATUS_SUPERSEDED}),
    STATUS_REJECTED: frozenset({STATUS_REJECTED}),
    STATUS_CANCELLED: frozenset({STATUS_CANCELLED}),
    STATUS_RETIRED: frozenset({STATUS_RETIRED}),
}

POSITION_CONTENT_FIELDS = ("name", "description", "process_ids")
IMPACT_LEVELS = frozenset({"info", "warning", "high", "blocking"})


class _ActionPayloadMixin:
    action = "refresh_position"

    def to_payload(self):
        payload = super().to_payload()
        payload["action"] = self.action
        return payload


class PositionVersioningError(_ActionPayloadMixin, ConflictError):
    code = "POSITION_REFERENCE_CONFLICT"


class PositionValidationError(_ActionPayloadMixin, ValidationError):
    code = "POSITION_PROCESS_INVALID"


class PositionNotFoundError(_ActionPayloadMixin, NotFoundError):
    code = "POSITION_NOT_FOUND"
    action = "refresh_positions"


class PositionVersionNotFoundError(PositionNotFoundError):
    code = "POSITION_VERSION_NOT_FOUND"
    action = "refresh_position_versions"


class PositionVersionStaleError(PositionVersioningError):
    code = "POSITION_VERSION_STALE"
    action = "refresh_position_version"


class PositionVersionImmutableError(PositionVersioningError):
    code = "POSITION_VERSION_IMMUTABLE"
    action = "create_position_revision"


class PositionVersionAlreadyOpenError(PositionVersioningError):
    code = "POSITION_VERSION_ALREADY_OPEN"
    action = "open_existing_position_revision"


class PositionApprovalSeparationError(PositionVersioningError):
    code = "POSITION_APPROVAL_SEPARATION_REQUIRED"
    action = "select_different_approver"


class PositionProcessInvalidError(PositionValidationError):
    code = "POSITION_PROCESS_INVALID"
    action = "select_active_processes"


class PositionImpactChangedError(PositionVersioningError):
    code = "POSITION_IMPACT_CHANGED"
    action = "refresh_position_impact"


class PositionActiveEmployeesError(PositionVersioningError):
    code = "POSITION_ACTIVE_EMPLOYEES_EXIST"
    action = "reassign_active_employees"


class PositionActiveSessionsError(PositionVersioningError):
    code = "POSITION_ACTIVE_SESSIONS_EXIST"
    action = "expire_position_sessions"


class PositionReferenceConflictError(PositionVersioningError):
    code = "POSITION_REFERENCE_CONFLICT"
    action = "create_new_position_root"


class PositionLegacyWriteBlockedError(PositionVersioningError):
    code = "POSITION_LEGACY_WRITE_BLOCKED"
    action = "use_position_version_api"


class PositionMigrationReviewRequiredError(PositionVersioningError):
    code = "POSITION_MIGRATION_REVIEW_REQUIRED"
    action = "review_position_migration_evidence"


class PositionVersionedWriteDisabledError(PositionVersioningError):
    code = "POSITION_VERSIONED_WRITE_DISABLED"
    action = "enable_position_versioned_write"


def _require_status(value):
    status = str(value or "").strip()
    if status not in VERSION_STATUSES:
        raise ValidationError("岗位版本状态无效", details={"status": status})
    return status


def validate_transition(current, target):
    current_status = _require_status(current)
    target_status = _require_status(target)
    if target_status not in VERSION_TRANSITIONS[current_status]:
        raise PositionVersionImmutableError(
            "当前岗位版本状态不允许执行该转换",
            details={
                "current_status": current_status,
                "target_status": target_status,
            },
        )
    return target_status


def require_row_version(value):
    if value is None or isinstance(value, bool):
        raise ValidationError("缺少有效的 row_version")
    try:
        version = int(value)
    except (TypeError, ValueError) as exc:
        raise ValidationError("缺少有效的 row_version") from exc
    if version < 0:
        raise ValidationError("row_version 无效")
    return version


def assert_row_version(expected, actual):
    expected_version = require_row_version(expected)
    actual_version = require_row_version(actual)
    if expected_version != actual_version:
        raise PositionVersionStaleError(
            "岗位版本已被其他操作修改，请刷新后重试",
            details={"expected": expected_version, "actual": actual_version},
        )
    return actual_version


def _positive_actor_id(value, label):
    if value is None or isinstance(value, bool):
        raise ValidationError(f"{label}不能为空")
    try:
        result = int(value)
    except (TypeError, ValueError) as exc:
        raise ValidationError(f"{label}无效") from exc
    if result <= 0:
        raise ValidationError(f"{label}无效")
    return result


def assert_separation_of_duties(prepared_by, approved_by):
    preparer_id = _positive_actor_id(prepared_by, "制单人")
    approver_id = _positive_actor_id(approved_by, "批准人")
    if preparer_id == approver_id:
        raise PositionApprovalSeparationError(
            "制单人与批准人必须不同",
            details={"prepared_by": preparer_id, "approved_by": approver_id},
        )
    return True


def _canonical_scalar(value):
    if isinstance(value, float):
        if not isfinite(value):
            raise ValidationError("摘要输入不能包含 NaN 或 Infinity")
        if value == 0:
            return 0
    return value


def canonicalize(value):
    if isinstance(value, dict):
        return {
            str(key): canonicalize(value[key])
            for key in sorted(value, key=lambda item: str(item))
        }
    if isinstance(value, (list, tuple)):
        return [canonicalize(item) for item in value]
    if isinstance(value, (set, frozenset)):
        values = [canonicalize(item) for item in value]
        return sorted(values, key=canonical_json)
    if value is None or isinstance(value, (str, int, float, bool)):
        return _canonical_scalar(value)
    raise ValidationError(
        "摘要输入包含不支持的数据类型",
        details={"type": type(value).__name__},
    )


def canonical_json(value):
    return evidence_protocol.canonical_json_v1(canonicalize(value))


def stable_digest(value):
    return evidence_protocol.sha256_digest_v1(canonicalize(value))


def _positive_process_id(value):
    if value is None or isinstance(value, bool):
        raise PositionProcessInvalidError("岗位工序 ID 无效")
    try:
        process_id = int(value)
    except (TypeError, ValueError) as exc:
        raise PositionProcessInvalidError("岗位工序 ID 无效") from exc
    if process_id <= 0:
        raise PositionProcessInvalidError(
            "岗位工序 ID 无效", details={"process_id": value}
        )
    return process_id


def normalize_process_ids(values):
    if values is None:
        return []
    if not isinstance(values, (list, tuple, set, frozenset)):
        raise PositionProcessInvalidError("岗位工序必须是数组")
    return sorted({_positive_process_id(value) for value in values})


def normalize_position_content(payload):
    source = payload or {}
    if not isinstance(source, dict):
        raise ValidationError("岗位版本内容必须是对象")
    name = str(source.get("name") or "").strip()
    if not name:
        raise ValidationError("岗位名称不能为空")
    return {
        "name": name,
        "description": str(source.get("description") or "").strip(),
        "process_ids": normalize_process_ids(source.get("process_ids") or []),
    }


def canonical_position_payload(payload):
    source = payload or {}
    content = normalize_position_content(source)
    return {
        "position_id": source.get("position_id"),
        "version": source.get("version"),
        "position_code_snapshot": str(
            source.get("position_code_snapshot") or ""
        ).strip(),
        **content,
    }


def content_digest(payload):
    return stable_digest(canonical_position_payload(payload))


def normalize_impact_items(items):
    if items is None:
        return []
    if not isinstance(items, (list, tuple)):
        raise ValidationError("岗位影响必须是数组")
    normalized = []
    for item in items:
        if not isinstance(item, dict):
            raise ValidationError("岗位影响项必须是对象")
        key = str(item.get("key") or "").strip()
        if not key:
            raise ValidationError("岗位影响项缺少 key")
        try:
            count = int(item.get("count") or 0)
        except (TypeError, ValueError) as exc:
            raise ValidationError("岗位影响数量必须是整数") from exc
        if count < 0:
            raise ValidationError("岗位影响数量不能为负数")
        level = str(item.get("blocking_level") or "info").strip()
        if level not in IMPACT_LEVELS:
            raise ValidationError(
                "岗位影响级别无效", details={"blocking_level": level}
            )
        normalized.append(
            {"key": key, "count": count, "blocking_level": level}
        )
    return sorted(normalized, key=lambda item: (item["key"], canonical_json(item)))


def impact_digest(items):
    return stable_digest(normalize_impact_items(items))


def assert_impact_digest(submitted, current):
    submitted_digest = str(submitted or "")
    current_digest = str(current or "")
    if submitted_digest != current_digest:
        raise PositionImpactChangedError(
            "岗位影响范围已变化，请刷新后重新提交",
            details={
                "submitted_impact_digest": submitted_digest,
                "current_impact_digest": current_digest,
            },
        )
    return True


def position_diff(before, after):
    original = normalize_position_content(before)
    revised = normalize_position_content(after)
    changes = []
    for field in ("name", "description"):
        if original[field] != revised[field]:
            changes.append(
                {"field": field, "old": original[field], "new": revised[field]}
            )
    before_processes = set(original["process_ids"])
    after_processes = set(revised["process_ids"])
    added = sorted(after_processes - before_processes)
    removed = sorted(before_processes - after_processes)
    if added or removed:
        changes.append(
            {
                "field": "process_ids",
                "old": original["process_ids"],
                "new": revised["process_ids"],
            }
        )
    changed_fields = [change["field"] for change in changes]
    return {
        "has_changes": bool(changes),
        "changed_fields": changed_fields,
        "changes": changes,
        "added_process_ids": added,
        "removed_process_ids": removed,
        "requires_assignment_snapshot_split": "name" in changed_fields,
        "high_impact": bool(added or removed),
    }


def assert_root_identity_preserved(
    before, after, *, identity_change_reason=""
):
    original = before or {}
    revised = after or {}
    meaning_changed = any(
        bool(revised.get(field))
        for field in (
            "organizational_meaning_changed",
            "responsibility_changed",
            "skill_requirement_changed",
            "root_identity_changed",
        )
    )
    if meaning_changed:
        raise PositionReferenceConflictError(
            "岗位职责、技能或组织含义已经改变，必须创建新的岗位根实体",
            details={
                "before_name": str(original.get("name") or ""),
                "after_name": str(revised.get("name") or ""),
                "reason": str(identity_change_reason or "").strip(),
            },
        )
    return True


def copy_revision_content(current, *, version, revision_reason):
    source = current or {}
    reason = str(revision_reason or "").strip()
    if not reason:
        raise ValidationError("修订原因不能为空")
    content = normalize_position_content(source)
    return {
        "position_id": source.get("position_id"),
        "version": int(version),
        "position_code_snapshot": str(
            source.get("position_code_snapshot") or ""
        ).strip(),
        **content,
        "status": STATUS_DRAFT,
        "supersedes_version_id": source.get("id"),
        "revision_reason": reason,
    }
