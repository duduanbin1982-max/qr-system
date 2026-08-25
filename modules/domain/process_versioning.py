"""Pure workflow, diff, identity, and digest rules for process master versions."""

from collections import Counter
from copy import deepcopy
import hashlib
import json
from math import isfinite

from modules.domain.errors import ConflictError, ValidationError


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
TERMINAL_VERSION_STATUSES = frozenset(
    {STATUS_SUPERSEDED, STATUS_REJECTED, STATUS_CANCELLED, STATUS_RETIRED}
)

VERSION_TRANSITIONS = {
    STATUS_DRAFT: frozenset({STATUS_DRAFT, STATUS_PENDING_APPROVAL, STATUS_CANCELLED}),
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

ROUTE_VERSION_TRANSITIONS = {
    **VERSION_TRANSITIONS,
    STATUS_PENDING_APPROVAL: frozenset(
        {STATUS_PENDING_APPROVAL, STATUS_PUBLISHED, STATUS_DRAFT}
    ),
}

EVENT_CREATED = "created"
EVENT_REVISION_CREATED = "revision_created"
EVENT_SUBMITTED = "submitted"
EVENT_APPROVED = "approved"
EVENT_REJECTED = "rejected"
EVENT_PUBLISHED = "published"
EVENT_SUPERSEDED = "superseded"
EVENT_CANCELLED = "cancelled"
EVENT_RETIRED = "retired"
EVENT_REACTIVATED = "reactivated"
EVENT_LEGACY_BASELINE_CREATED = "legacy_baseline_created"

VERSION_EVENT_TYPES = frozenset(
    {
        EVENT_CREATED,
        EVENT_REVISION_CREATED,
        EVENT_SUBMITTED,
        EVENT_APPROVED,
        EVENT_REJECTED,
        EVENT_PUBLISHED,
        EVENT_SUPERSEDED,
        EVENT_CANCELLED,
        EVENT_RETIRED,
        EVENT_REACTIVATED,
        EVENT_LEGACY_BASELINE_CREATED,
    }
)

ERROR_PROCESS_VERSION_STALE = "PROCESS_VERSION_STALE"
ERROR_PROCESS_VERSION_IMMUTABLE = "PROCESS_VERSION_IMMUTABLE"
ERROR_PROCESS_APPROVAL_SEPARATION = "PROCESS_APPROVAL_SEPARATION_REQUIRED"
ERROR_ROUTE_VERSION_STALE = "ROUTE_VERSION_STALE"
ERROR_ROUTE_VERSION_IMMUTABLE = "ROUTE_VERSION_IMMUTABLE"
ERROR_ROUTE_PROCESS_CATEGORY_MISMATCH = "ROUTE_PROCESS_CATEGORY_MISMATCH"
ERROR_ROUTE_PROCESS_VERSION_INVALID = "ROUTE_PROCESS_VERSION_INVALID"
ERROR_PRICE_VERSION_BINDING_REQUIRED = "PRICE_VERSION_BINDING_REQUIRED"
ERROR_RELEASE_DEPENDENCY_MISSING = "MASTER_DATA_RELEASE_DEPENDENCY_MISSING"
ERROR_LEGACY_WRITE_BLOCKED = "LEGACY_MASTER_DATA_WRITE_BLOCKED"
ERROR_ROOT_IDENTITY_CHANGED = "MASTER_DATA_ROOT_IDENTITY_CHANGED"

PROCESS_FIELDS = ("name", "category", "description", "seq_order")
ROUTE_FIELDS = ("name", "category", "description")
ROUTE_ITEM_FIELDS = (
    "process_id",
    "process_version_id",
    "seq_order",
    "is_required",
    "required_audit",
)

IMPACT_LEVEL_ORDER = {"info": 0, "warning": 1, "high": 2, "blocking": 3}
ROUTE_NODE_CHANGE_ORDER = {
    "node_removed": 0,
    "node_added": 1,
    "node_reordered": 2,
    "process_version_changed": 3,
    "approval_requirement_changed": 4,
}


class ProcessVersioningError(ConflictError):
    """Conflict with a stable error code and suggested recovery action."""

    code = "PROCESS_VERSION_CONFLICT"
    action = "refresh_master_data"

    def __init__(self, message, *, details=None, action=None):
        super().__init__(message, details=details)
        self.action = action or self.action

    def to_payload(self):
        payload = super().to_payload()
        if self.action:
            payload["action"] = self.action
        return payload


class ProcessVersionImmutableError(ProcessVersioningError):
    code = ERROR_PROCESS_VERSION_IMMUTABLE
    action = "create_process_revision"


class RouteVersionImmutableError(ProcessVersioningError):
    code = ERROR_ROUTE_VERSION_IMMUTABLE
    action = "create_route_revision"


class ProcessVersionStaleError(ProcessVersioningError):
    code = ERROR_PROCESS_VERSION_STALE
    action = "refresh_process_version"


class RouteVersionStaleError(ProcessVersioningError):
    code = ERROR_ROUTE_VERSION_STALE
    action = "refresh_route_version"


class ApprovalSeparationError(ProcessVersioningError):
    code = ERROR_PROCESS_APPROVAL_SEPARATION
    action = "select_different_approver"


class ReleaseDependencyError(ProcessVersioningError):
    code = ERROR_RELEASE_DEPENDENCY_MISSING
    action = "complete_release_dependencies"


class RouteProcessCategoryMismatchError(ProcessVersioningError):
    code = ERROR_ROUTE_PROCESS_CATEGORY_MISMATCH
    action = "align_route_and_process_categories"


class RouteProcessVersionInvalidError(ProcessVersioningError):
    code = ERROR_ROUTE_PROCESS_VERSION_INVALID
    action = "select_matching_process_version"


class LegacyMasterDataWriteBlockedError(ProcessVersioningError):
    code = ERROR_LEGACY_WRITE_BLOCKED
    action = "use_versioned_master_data_api"


class VersionedMasterDataWriteDisabledError(ProcessVersioningError):
    code = "PROCESS_VERSIONED_WRITE_DISABLED"
    action = "enable_process_versioned_write"


class MasterDataIdentityChangedError(ProcessVersioningError):
    code = ERROR_ROOT_IDENTITY_CHANGED
    action = "create_new_root_entity"


def _entity_type(value):
    entity_type = str(value or "").strip().lower()
    aliases = {
        "process": "process",
        "process_version": "process",
        "route": "route",
        "process_route": "route",
        "route_version": "route",
    }
    if entity_type not in aliases:
        raise ValidationError("主数据实体类型必须是 process 或 route")
    return aliases[entity_type]


def _require_status(value):
    status = str(value or "").strip()
    if status not in VERSION_STATUSES:
        raise ValidationError("工序或路线版本状态无效", details={"status": status})
    return status


def validate_version_transition(current, target, *, entity_type="process"):
    entity = _entity_type(entity_type)
    current_status = _require_status(current)
    target_status = _require_status(target)
    if target_status in VERSION_TRANSITIONS[current_status]:
        return target_status

    details = {"current_status": current_status, "target_status": target_status}
    if entity == "process":
        raise ProcessVersionImmutableError(
            "当前工序版本状态不允许执行该转换", details=details
        )
    raise RouteVersionImmutableError(
        "当前路线版本状态不允许执行该转换", details=details
    )


def validate_process_version_transition(current, target):
    return validate_version_transition(current, target, entity_type="process")


def validate_route_version_transition(current, target):
    current_status = _require_status(current)
    target_status = _require_status(target)
    if target_status in ROUTE_VERSION_TRANSITIONS[current_status]:
        return target_status
    raise RouteVersionImmutableError(
        "当前路线版本状态不允许执行该转换",
        details={"current_status": current_status, "target_status": target_status},
    )


def require_row_version(value):
    try:
        version = int(value)
    except (TypeError, ValueError) as exc:
        raise ValidationError("缺少有效的 row_version") from exc
    if version < 0:
        raise ValidationError("row_version 无效")
    return version


def assert_row_version(expected, actual, *, entity_type="process"):
    entity = _entity_type(entity_type)
    expected_version = require_row_version(expected)
    actual_version = require_row_version(actual)
    if expected_version == actual_version:
        return actual_version

    details = {"expected": expected_version, "actual": actual_version}
    if entity == "process":
        raise ProcessVersionStaleError(
            "工序版本已被其他操作修改，请刷新后重试", details=details
        )
    raise RouteVersionStaleError(
        "路线版本已被其他操作修改，请刷新后重试", details=details
    )


def _actor_id(value, label):
    if value is None or isinstance(value, bool):
        raise ValidationError(f"{label}不能为空")
    try:
        actor_id = int(value)
    except (TypeError, ValueError) as exc:
        raise ValidationError(f"{label}无效") from exc
    if actor_id <= 0:
        raise ValidationError(f"{label}无效")
    return actor_id


def assert_separation_of_duties(prepared_by, approved_by, *, entity_type="process"):
    _entity_type(entity_type)
    preparer_id = _actor_id(prepared_by, "制单人")
    approver_id = _actor_id(approved_by, "批准人")
    if preparer_id == approver_id:
        raise ApprovalSeparationError(
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
    """Return a deterministic JSON-compatible representation."""
    if isinstance(value, dict):
        return {
            str(key): canonicalize(value[key])
            for key in sorted(value, key=lambda item: str(item))
        }
    if isinstance(value, (list, tuple)):
        return [canonicalize(item) for item in value]
    if isinstance(value, (set, frozenset)):
        normalized = [canonicalize(item) for item in value]
        return sorted(normalized, key=canonical_json)
    if value is None or isinstance(value, (str, int, float, bool)):
        return _canonical_scalar(value)
    raise ValidationError(
        "摘要输入包含不支持的数据类型",
        details={"type": type(value).__name__},
    )


def canonical_json(value):
    return json.dumps(
        canonicalize(value),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )


def payload_sha256(value):
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


def _impact_sort_key(item):
    return (
        str(item.get("resource") or item.get("resource_code") or ""),
        str(item.get("scope") or ""),
        str(item.get("action") or ""),
        canonical_json(item),
    )


def summarize_impact(impact_items):
    items = [canonicalize(item) for item in (impact_items or [])]
    items.sort(key=_impact_sort_key)
    total_count = 0
    levels = Counter()
    resources = []
    for item in items:
        try:
            count = int(item.get("count") or 0)
        except (TypeError, ValueError) as exc:
            raise ValidationError("影响数量必须是整数") from exc
        if count < 0:
            raise ValidationError("影响数量不能为负数")
        level = str(item.get("blocking_level") or item.get("impact_level") or "info")
        if level not in IMPACT_LEVEL_ORDER:
            raise ValidationError("影响级别无效", details={"blocking_level": level})
        total_count += count
        levels[level] += 1
        resource = item.get("resource") or item.get("resource_code")
        if resource:
            resources.append(str(resource))
    highest = max(levels, key=IMPACT_LEVEL_ORDER.get) if levels else "info"
    return {
        "items": items,
        "resource_count": len(set(resources)),
        "total_reference_count": total_count,
        "highest_blocking_level": highest,
        "blocking_item_count": levels["blocking"],
    }


def _version_content(entity_type, content):
    entity = _entity_type(entity_type)
    source = content or {}
    if not isinstance(source, dict):
        raise ValidationError("版本内容必须是对象")
    if entity == "process":
        fields = (
            "process_id",
            "version",
            "process_code_snapshot",
            *PROCESS_FIELDS,
        )
        return {field: canonicalize(source.get(field)) for field in fields}
    fields = (
        "process_route_id",
        "version",
        "route_code_snapshot",
        *ROUTE_FIELDS,
    )
    result = {field: canonicalize(source.get(field)) for field in fields}
    result["items"] = normalize_route_items(source.get("items") or [])
    return result


def canonical_version_payload(entity_type, content, impact_items=()):
    entity = _entity_type(entity_type)
    return {
        "entity_type": entity,
        "content": _version_content(entity, content),
        "impact": summarize_impact(impact_items),
    }


def _change(field, old, new, impact_level="normal"):
    return {
        "field": field,
        "old": canonicalize(old),
        "new": canonicalize(new),
        "impact_level": impact_level,
    }


def diff_process_versions(before, after):
    original = before or {}
    revised = after or {}
    changes = []
    for field in PROCESS_FIELDS:
        old_value = original.get(field)
        new_value = revised.get(field)
        if old_value != new_value:
            changes.append(
                _change(
                    field,
                    old_value,
                    new_value,
                    "high" if field == "category" else "normal",
                )
            )
    category_changed = "category" in {item["field"] for item in changes}
    return {
        "entity_type": "process",
        "has_changes": bool(changes),
        "changed_fields": [item["field"] for item in changes],
        "changes": changes,
        "high_impact": category_changed,
        "requires_authorized_review": category_changed,
        "review_reasons": ["category_changed"] if category_changed else [],
    }


def _normalize_flag(value, field):
    if value in (True, 1, "1"):
        return 1
    if value in (False, 0, "0", None, ""):
        return 0
    raise ValidationError(f"路线节点 {field} 必须是布尔值")


def _positive_id(value, field):
    if value is None or isinstance(value, bool):
        raise ValidationError(f"路线节点缺少 {field}")
    try:
        result = int(value)
    except (TypeError, ValueError) as exc:
        raise ValidationError(f"路线节点 {field} 无效") from exc
    if result <= 0:
        raise ValidationError(f"路线节点 {field} 无效")
    return result


def _sequence(value):
    try:
        sequence = int(value)
    except (TypeError, ValueError) as exc:
        raise ValidationError("路线节点 seq_order 无效") from exc
    if sequence < 0:
        raise ValidationError("路线节点 seq_order 无效")
    return sequence


def normalize_route_items(items):
    if not isinstance(items, (list, tuple)):
        raise ValidationError("路线节点必须是数组")
    normalized = []
    seen_process_ids = set()
    seen_sequences = set()
    for item in items:
        if not isinstance(item, dict):
            raise ValidationError("路线节点必须是对象")
        process_id = _positive_id(item.get("process_id"), "process_id")
        process_version_id = _positive_id(
            item.get("process_version_id"), "process_version_id"
        )
        seq_order = _sequence(item.get("seq_order"))
        if process_id in seen_process_ids:
            raise ValidationError(
                "同一路线版本不能重复使用同一工序",
                details={"process_id": process_id},
            )
        if seq_order in seen_sequences:
            raise ValidationError(
                "同一路线版本的节点顺序不能重复",
                details={"seq_order": seq_order},
            )
        seen_process_ids.add(process_id)
        seen_sequences.add(seq_order)
        normalized.append(
            {
                "process_id": process_id,
                "process_version_id": process_version_id,
                "seq_order": seq_order,
                "is_required": _normalize_flag(item.get("is_required", 1), "is_required"),
                "required_audit": _normalize_flag(
                    item.get("required_audit", 0), "required_audit"
                ),
            }
        )
    return sorted(
        normalized,
        key=lambda item: (item["seq_order"], item["process_id"], item["process_version_id"]),
    )


def _node_change(change_type, process_id, **details):
    result = {"change_type": change_type, "process_id": process_id}
    result.update(canonicalize(details))
    return result


def diff_route_versions(before, after):
    original = before or {}
    revised = after or {}
    field_changes = []
    for field in ROUTE_FIELDS:
        old_value = original.get(field)
        new_value = revised.get(field)
        if old_value != new_value:
            field_changes.append(
                _change(
                    field,
                    old_value,
                    new_value,
                    "high" if field == "category" else "normal",
                )
            )

    before_items = normalize_route_items(original.get("items") or [])
    after_items = normalize_route_items(revised.get("items") or [])
    before_by_process = {item["process_id"]: item for item in before_items}
    after_by_process = {item["process_id"]: item for item in after_items}
    node_changes = []

    for process_id in sorted(before_by_process.keys() - after_by_process.keys()):
        node_changes.append(
            _node_change("node_removed", process_id, before=before_by_process[process_id])
        )
    for process_id in sorted(after_by_process.keys() - before_by_process.keys()):
        node_changes.append(
            _node_change("node_added", process_id, after=after_by_process[process_id])
        )
    for process_id in sorted(before_by_process.keys() & after_by_process.keys()):
        old = before_by_process[process_id]
        new = after_by_process[process_id]
        if old["seq_order"] != new["seq_order"]:
            node_changes.append(
                _node_change(
                    "node_reordered",
                    process_id,
                    old_seq_order=old["seq_order"],
                    new_seq_order=new["seq_order"],
                )
            )
        if old["process_version_id"] != new["process_version_id"]:
            node_changes.append(
                _node_change(
                    "process_version_changed",
                    process_id,
                    old_process_version_id=old["process_version_id"],
                    new_process_version_id=new["process_version_id"],
                )
            )
        if (
            old["required_audit"] != new["required_audit"]
            or old["is_required"] != new["is_required"]
        ):
            node_changes.append(
                _node_change(
                    "approval_requirement_changed",
                    process_id,
                    old_required_audit=old["required_audit"],
                    new_required_audit=new["required_audit"],
                    old_is_required=old["is_required"],
                    new_is_required=new["is_required"],
                )
            )

    node_changes.sort(
        key=lambda item: (
            ROUTE_NODE_CHANGE_ORDER[item["change_type"]],
            item["process_id"],
        )
    )
    summary = Counter(item["change_type"] for item in node_changes)
    category_changed = "category" in {item["field"] for item in field_changes}
    return {
        "entity_type": "route",
        "has_changes": bool(field_changes or node_changes),
        "changed_fields": [item["field"] for item in field_changes],
        "field_changes": field_changes,
        "node_changes": node_changes,
        "node_summary": dict(summary),
        "high_impact": category_changed or bool(node_changes),
        "requires_authorized_review": category_changed,
        "review_reasons": ["category_changed"] if category_changed else [],
    }


def assert_root_identity_preserved(
    entity_type,
    before,
    after,
    *,
    identity_change_reason="",
):
    entity = _entity_type(entity_type)
    original = before or {}
    revised = after or {}
    reason = str(identity_change_reason or revised.get("identity_change_reason") or "").strip()
    meaning_changed = bool(
        revised.get("manufacturing_meaning_changed")
        or revised.get("skill_requirement_changed")
        or revised.get("process_purpose_changed")
        or revised.get("root_identity_changed")
    )
    if meaning_changed:
        raise MasterDataIdentityChangedError(
            "制造含义、技能要求或工艺目的已经改变，必须创建新的主数据根实体",
            details={
                "entity_type": entity,
                "reason": reason,
                "before_name": original.get("name"),
                "after_name": revised.get("name"),
            },
        )
    return True


def assert_route_category_consistency(route_category, process_versions):
    category = str(route_category or "").strip()
    mismatched = []
    for item in process_versions or []:
        process_category = str(
            item.get("process_category") or item.get("category") or ""
        ).strip()
        if process_category != category:
            mismatched.append(
                {
                    "process_id": item.get("process_id"),
                    "process_version_id": item.get("process_version_id"),
                    "process_category": process_category,
                }
            )
    if mismatched:
        raise RouteProcessCategoryMismatchError(
            "路线分类必须与全部节点工序版本分类一致",
            details={
                "route_category": category,
                "mismatched_process_ids": sorted(
                    item["process_id"]
                    for item in mismatched
                    if item["process_id"] is not None
                ),
                "mismatched_items": mismatched,
            },
        )
    return True


def assert_route_process_version_binding(
    expected_process_id,
    actual_process_id,
    *,
    process_version_id=None,
):
    expected = _positive_id(expected_process_id, "process_id")
    actual = _positive_id(actual_process_id, "process_id")
    if expected != actual:
        raise RouteProcessVersionInvalidError(
            "工序版本不属于路线节点指定的稳定工序",
            details={
                "expected_process_id": expected,
                "actual_process_id": actual,
                "process_version_id": process_version_id,
            },
        )
    return True


def summarize_release_batch(
    *,
    process_versions=(),
    route_versions=(),
    price_versions=(),
    approved_exceptions=(),
):
    def normalized_rows(rows):
        values = [canonicalize(row) for row in (rows or [])]
        return sorted(
            values,
            key=lambda item: (
                int(item.get("id") or 0),
                canonical_json(item),
            ),
        )

    return {
        "process_versions": normalized_rows(process_versions),
        "route_versions": normalized_rows(route_versions),
        "price_versions": normalized_rows(price_versions),
        "approved_exceptions": normalized_rows(approved_exceptions),
    }


def _release_failure(reason_code, message, **details):
    payload = {"reason_code": reason_code}
    payload.update(canonicalize(details))
    raise ReleaseDependencyError(message, details=payload)


def _ids(rows):
    result = set()
    for row in rows or []:
        if isinstance(row, dict):
            value = row.get("id")
        else:
            value = row
        if value is not None:
            result.add(int(value))
    return result


def validate_release_batch_dependencies(batch):
    if not isinstance(batch, dict):
        raise ValidationError("发布批次依赖必须是对象")
    process_versions = list(batch.get("process_versions") or [])
    route_versions = list(batch.get("route_versions") or [])
    price_versions = list(batch.get("price_versions") or [])
    approved_exceptions = list(batch.get("approved_exceptions") or [])
    batch_process_ids = _ids(process_versions)
    batch_route_ids = _ids(route_versions)
    published_process_ids = _ids(batch.get("published_process_version_ids") or [])
    published_route_ids = _ids(batch.get("published_route_version_ids") or [])

    price_bindings = {
        (
            int(price["route_version_id"]),
            int(price["process_version_id"]),
        )
        for price in price_versions
        if price.get("route_version_id") is not None
        and price.get("process_version_id") is not None
    }
    exception_route_ids = {
        int(item["route_version_id"])
        for item in approved_exceptions
        if item.get("route_version_id") is not None
    }

    for route in route_versions:
        route_version_id = int(route.get("id") or 0)
        if route_version_id <= 0:
            _release_failure(
                "ROUTE_VERSION_ID_REQUIRED",
                "发布批次中的路线版本缺少稳定 ID",
            )
        for item in route.get("items") or []:
            process_version_id = int(item.get("process_version_id") or 0)
            if process_version_id not in batch_process_ids | published_process_ids:
                _release_failure(
                    ERROR_ROUTE_PROCESS_VERSION_INVALID,
                    "路线节点依赖的工序版本未发布且不在当前发布批次中",
                    route_version_id=route_version_id,
                    process_id=item.get("process_id"),
                    process_version_id=process_version_id,
                )
            if item.get("requires_price") and (
                route_version_id,
                process_version_id,
            ) not in price_bindings:
                _release_failure(
                    ERROR_PRICE_VERSION_BINDING_REQUIRED,
                    "需要计件工价的路线节点缺少对应工价版本",
                    route_version_id=route_version_id,
                    process_id=item.get("process_id"),
                    process_version_id=process_version_id,
                )

    released_route_ids = batch_route_ids | published_route_ids | exception_route_ids
    for affected in batch.get("affected_routes") or []:
        route_version_id = int(affected.get("route_version_id") or 0)
        if route_version_id not in released_route_ids:
            _release_failure(
                "AFFECTED_ROUTE_REVISION_OR_EXCEPTION_REQUIRED",
                "受影响路线缺少路线修订版或批准例外",
                route_version_id=route_version_id,
                process_version_id=affected.get("process_version_id"),
            )
    return summarize_release_batch(
        process_versions=process_versions,
        route_versions=route_versions,
        price_versions=price_versions,
        approved_exceptions=approved_exceptions,
    )


def assert_legacy_master_data_write_allowed(versioned_write_enabled):
    if not bool(versioned_write_enabled):
        raise LegacyMasterDataWriteBlockedError(
            "Legacy 工序和路线写入已关闭，请使用版本化主数据接口"
        )
    return True


def copy_revision_content(entity_type, current_content, *, version, revision_reason):
    """Copy editable content for a new revision without reading external state."""
    entity = _entity_type(entity_type)
    reason = str(revision_reason or "").strip()
    if not reason:
        raise ValidationError("修订原因不能为空")
    try:
        next_version = int(version)
    except (TypeError, ValueError) as exc:
        raise ValidationError("版本号无效") from exc
    if next_version <= 0:
        raise ValidationError("版本号无效")
    content = deepcopy(current_content or {})
    content["version"] = next_version
    content["status"] = STATUS_DRAFT
    content["revision_reason"] = reason
    content["row_version"] = 0
    content.pop("id", None)
    content.pop("approved_by", None)
    content.pop("approved_at", None)
    content.pop("published_at", None)
    if entity == "route":
        content["items"] = normalize_route_items(content.get("items") or [])
    return content


__all__ = [
    "ApprovalSeparationError",
    "LegacyMasterDataWriteBlockedError",
    "MasterDataIdentityChangedError",
    "ProcessVersionImmutableError",
    "ProcessVersionStaleError",
    "ReleaseDependencyError",
    "RouteProcessCategoryMismatchError",
    "RouteProcessVersionInvalidError",
    "RouteVersionImmutableError",
    "RouteVersionStaleError",
    "VersionedMasterDataWriteDisabledError",
    "VERSION_EVENT_TYPES",
    "VERSION_STATUSES",
    "VERSION_TRANSITIONS",
    "ROUTE_VERSION_TRANSITIONS",
    "assert_legacy_master_data_write_allowed",
    "assert_root_identity_preserved",
    "assert_route_category_consistency",
    "assert_route_process_version_binding",
    "assert_row_version",
    "assert_separation_of_duties",
    "canonical_json",
    "canonical_version_payload",
    "canonicalize",
    "copy_revision_content",
    "diff_process_versions",
    "diff_route_versions",
    "normalize_route_items",
    "payload_sha256",
    "require_row_version",
    "summarize_impact",
    "summarize_release_batch",
    "validate_process_version_transition",
    "validate_release_batch_dependencies",
    "validate_route_version_transition",
    "validate_version_transition",
]
