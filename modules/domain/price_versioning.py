"""Pure policy for exact route and process price-version bindings."""

from modules.domain.errors import ConflictError


class _PriceVersioningConflict(ConflictError):
    default_message = "版本化工价操作冲突"

    def __init__(self, message=None, *, details=None):
        super().__init__(message or self.default_message, details=details)


class RouteVersionNotPricableError(_PriceVersioningConflict):
    code = "ROUTE_VERSION_NOT_PRICABLE"
    default_message = "路线版本当前状态不可定价"


class PriceBindingMismatchError(_PriceVersioningConflict):
    code = "PRICE_BINDING_MISMATCH"
    default_message = "工价引用与精确路线节点不匹配"


class PriceBindingStaleError(_PriceVersioningConflict):
    code = "PRICE_BINDING_STALE"
    default_message = "工价引用内容已变化，请刷新后重试"


class PriceVersionVoidedError(_PriceVersioningConflict):
    code = "PRICE_VERSION_VOIDED"
    default_message = "工价版本已作废"


class GroupReleaseRequiredError(_PriceVersioningConflict):
    code = "GROUP_RELEASE_REQUIRED"
    default_message = "待发布路线工价只能随成组发布批准"


class ProcessVersionNotFrozenError(_PriceVersioningConflict):
    code = "PROCESS_VERSION_NOT_FROZEN"
    default_message = "路线节点引用的工序版本尚未冻结"


class ActiveReleaseBatchConflictError(_PriceVersioningConflict):
    code = "ACTIVE_RELEASE_BATCH_CONFLICT"
    default_message = "版本仍在活动发布批次中"


class PendingRoutePriceWriteDisabledError(_PriceVersioningConflict):
    code = "PENDING_ROUTE_PRICE_WRITE_DISABLED"
    default_message = "待发布路线工价写入尚未启用"


class IdempotencyConflictError(_PriceVersioningConflict):
    code = "IDEMPOTENCY_CONFLICT"
    default_message = "幂等键已用于不同请求"


class StaleRowVersionError(_PriceVersioningConflict):
    code = "STALE_ROW_VERSION"
    default_message = "记录版本已变化，请刷新后重试"


def price_reference_key(route_version_id, process_version_id):
    return f"{int(route_version_id)}:{int(process_version_id)}"


def pricing_mode(route_status):
    modes = {
        "published": "published_adjustment",
        "pending_approval": "pending_group_release",
    }
    try:
        return modes[str(route_status or "")]
    except KeyError as exc:
        raise RouteVersionNotPricableError(
            "路线版本当前状态不可定价",
            details={"route_version_status": route_status},
        ) from exc


def assert_exact_price_binding(binding, route_id, process_id):
    if binding is None or (
        int(binding.get("route_id") or 0) != int(route_id)
        or int(binding.get("process_id") or 0) != int(process_id)
    ):
        raise PriceBindingMismatchError(
            "工价引用与精确路线节点不匹配",
            details={"route_id": route_id, "process_id": process_id},
        )


def assert_expected_digest(expected, actual):
    if str(expected or "") != str(actual or ""):
        raise PriceBindingStaleError(
            "工价引用内容已变化，请刷新后重试",
            details={"expected_digest": expected, "actual_digest": actual},
        )


def assert_price_snapshot_current(price, binding):
    if str(price.get("status") or "") == "voided":
        raise PriceVersionVoidedError(
            "工价版本已作废",
            details={"price_version_id": price.get("id")},
        )
    if binding is None:
        raise PriceBindingMismatchError(
            "工价引用的精确路线节点不存在",
            details={"price_version_id": price.get("id")},
        )
    assert_expected_digest(
        price.get("route_content_digest_snapshot"),
        binding.get("route_content_digest"),
    )
    assert_expected_digest(
        price.get("process_content_digest_snapshot"),
        binding.get("process_content_digest"),
    )
