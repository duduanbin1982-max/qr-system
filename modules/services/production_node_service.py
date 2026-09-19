"""Validated transactional commands for production-node administration."""

from datetime import datetime

from modules.domain.errors import ConflictError, NotFoundError, ValidationError
from modules.repositories.production_node_repository import ProductionNodeRepository
from modules.services import BaseService


class ProductionNodeService:
    NODE_STATUSES = {"active", "inactive", "maintenance"}

    @staticmethod
    def _positive_int(value, label):
        if isinstance(value, bool):
            raise ValidationError(f"{label}必须是正整数")
        try:
            normalized = int(value)
        except (TypeError, ValueError) as exc:
            raise ValidationError(f"{label}必须是正整数") from exc
        if normalized < 1 or str(value).strip() != str(normalized):
            raise ValidationError(f"{label}必须是正整数")
        return normalized

    @staticmethod
    def _limit(value):
        normalized = ProductionNodeService._positive_int(value, "limit")
        if normalized > 500:
            raise ValidationError("limit不能大于500")
        return normalized

    @staticmethod
    def _actor_id(actor_id, db):
        normalized = ProductionNodeService._positive_int(actor_id, "操作人")
        if not ProductionNodeRepository.actor_exists(normalized, db=db):
            raise ValidationError("操作人不存在或已失效")
        return normalized

    @staticmethod
    def _text(value, label, maximum):
        normalized = str(value or "").strip()
        if not normalized:
            raise ValidationError(f"{label}不能为空")
        if len(normalized) > maximum:
            raise ValidationError(f"{label}长度不能超过{maximum}")
        return normalized

    @staticmethod
    def _command_digest(command):
        payload = {
            key: value
            for key, value in command.items()
            if key not in {"idempotency_key"}
        }
        return ProductionNodeRepository.payload_digest(payload)

    @staticmethod
    def _replay(key, event_type, digest, db):
        event = ProductionNodeRepository.find_audit_by_idempotency_key(key, db=db)
        if not event:
            return None
        if (
            event["event_type"] != event_type
            or event["after"].get("command_digest") != digest
        ):
            raise ConflictError("幂等键已用于不同的生产节点请求")
        return event["after"]

    @staticmethod
    def _node(node_id, db):
        node = ProductionNodeRepository.find_node(node_id, db=db)
        if not node:
            raise NotFoundError("生产节点不存在")
        return node

    @staticmethod
    def resolve_downtime_target(production_node_id, db):
        """Resolve the node-native downtime target through its stable legacy key.

        The legacy column remains NOT NULL during the gradual migration, so a
        node without an explicit stable mapping must be rejected instead of
        silently writing an unrelated line identifier.
        """
        node_id = ProductionNodeService._positive_int(
            production_node_id, "production_node_id"
        )
        node = ProductionNodeService._node(node_id, db)
        if node.get("status") != "active":
            raise ValidationError("生产节点已停用，不能新建停机事件")
        legacy_line_id = node.get("legacy_process_line_id")
        if legacy_line_id in (None, ""):
            raise ValidationError(
                "生产节点缺少稳定的 Legacy 产线映射，不能新建停机事件"
            )
        return node

    @staticmethod
    def _validate_node_references(data, db):
        if not ProductionNodeRepository.process_is_active(data["process_id"], db=db):
            raise ValidationError("工序不存在或已停用")
        if not ProductionNodeRepository.calendar_is_active(data["calendar_id"], db=db):
            raise ValidationError("工作日历不存在或已停用")

    @staticmethod
    def _normalize_node_command(data):
        status = str(data.get("status", "active")).strip()
        if status not in ProductionNodeService.NODE_STATUSES:
            raise ValidationError("生产节点状态无效")
        return {
            "process_id": ProductionNodeService._positive_int(
                data.get("process_id"), "process_id"
            ),
            "node_code": ProductionNodeService._text(
                data.get("node_code"), "节点编码", 64
            ),
            "node_name": ProductionNodeService._text(
                data.get("node_name"), "节点名称", 128
            ),
            "capacity_mode": str(data.get("capacity_mode") or "").strip(),
            "status": status,
            "calendar_id": ProductionNodeService._positive_int(
                data.get("calendar_id"), "calendar_id"
            ),
            "row_version": ProductionNodeService._positive_int(
                data.get("row_version"), "row_version"
            ),
            "reason": str(data.get("reason") or "").strip(),
            "idempotency_key": ProductionNodeService._text(
                data.get("idempotency_key"), "幂等键", 128
            ),
        }

    @staticmethod
    def _assert_unique_code(process_id, node_code, db, exclude_id=None):
        if ProductionNodeRepository.node_code_exists(
            process_id, node_code, exclude_id=exclude_id, db=db
        ):
            raise ConflictError("同一工序下节点编码已存在")

    @staticmethod
    def list_nodes(process_id=None, status=None, limit=500):
        if process_id not in (None, ""):
            process_id = ProductionNodeService._positive_int(process_id, "process_id")
        if status not in (None, "") and status not in ProductionNodeService.NODE_STATUSES:
            raise ValidationError("status无效")
        limit = ProductionNodeService._limit(limit)
        return ProductionNodeRepository.list_nodes(
            process_id=process_id, status=status, limit=limit
        )

    @staticmethod
    def list_capabilities(node_id):
        node_id = ProductionNodeService._positive_int(node_id, "node_id")
        with BaseService.transaction() as db:
            node = ProductionNodeService._node(node_id, db)
            return {
                "node": node,
                "capabilities": ProductionNodeRepository.list_capabilities(
                    node_id, db=db
                ),
            }

    @staticmethod
    def create_node(data, actor_id):
        command = ProductionNodeService._normalize_node_command(data)
        if command["row_version"] != 1:
            raise ValidationError("新建生产节点的row_version必须为1")
        if command["capacity_mode"] not in {"exclusive", "batch"}:
            raise ValidationError("容量模式无效")
        digest = ProductionNodeService._command_digest(command)
        with BaseService.transaction() as db:
            actor_id = ProductionNodeService._actor_id(actor_id, db)
            replay = ProductionNodeService._replay(
                command["idempotency_key"], "node_created", digest, db
            )
            if replay:
                return replay["node"]
            ProductionNodeService._validate_node_references(command, db)
            ProductionNodeService._assert_unique_code(
                command["process_id"], command["node_code"], db
            )
            node = ProductionNodeRepository.create_node(command, actor_id, db)
            ProductionNodeRepository.append_audit_event(
                {
                    "production_node_id": node["id"],
                    "event_type": "node_created",
                    "actor_id": actor_id,
                    "reason": command["reason"],
                    "before": {},
                    "after": {"node": node, "command_digest": digest},
                    "idempotency_key": command["idempotency_key"],
                },
                db,
            )
            return node

    @staticmethod
    def update_node(node_id, data, actor_id):
        node_id = ProductionNodeService._positive_int(node_id, "node_id")
        command = ProductionNodeService._normalize_node_command(data)
        if command["capacity_mode"] not in {"exclusive", "batch"}:
            raise ValidationError("容量模式无效")
        digest = ProductionNodeService._command_digest(
            {**command, "node_id": node_id}
        )
        with BaseService.transaction() as db:
            actor_id = ProductionNodeService._actor_id(actor_id, db)
            replay = ProductionNodeService._replay(
                command["idempotency_key"], "node_updated", digest, db
            )
            if replay:
                return replay["node"]
            before = ProductionNodeService._node(node_id, db)
            if command["process_id"] != before["process_id"]:
                raise ConflictError("生产节点所属工序不可变更")
            if command["row_version"] != before["row_version"]:
                raise ConflictError("生产节点已被修改，请刷新后重试")
            ProductionNodeService._validate_node_references(command, db)
            ProductionNodeService._assert_unique_code(
                command["process_id"], command["node_code"], db, node_id
            )
            node = ProductionNodeRepository.update_node(node_id, command, actor_id, db)
            if not node:
                raise ConflictError("生产节点已被修改，请刷新后重试")
            ProductionNodeRepository.append_audit_event(
                {
                    "production_node_id": node_id,
                    "event_type": "node_updated",
                    "actor_id": actor_id,
                    "reason": command["reason"],
                    "before": {"node": before},
                    "after": {"node": node, "command_digest": digest},
                    "idempotency_key": command["idempotency_key"],
                },
                db,
            )
            return node

    @staticmethod
    def _normalize_capability(item):
        normalized = {
            "product_id": item.get("product_id"),
            "product_family": str(item.get("product_family") or "").strip(),
            "material_code": str(item.get("material_code") or "").strip(),
            "specification": str(item.get("specification") or "").strip(),
            "route_version_id": item.get("route_version_id"),
            "process_version_id": item.get("process_version_id"),
            "max_batch_quantity": item.get("max_batch_quantity"),
            "batch_minutes": item.get("batch_minutes"),
            "changeover_minutes": item.get("changeover_minutes", 0),
            "allow_mixed_orders": bool(item.get("allow_mixed_orders", False)),
            "status": item.get("status", "active"),
        }
        for field in ("product_id", "route_version_id", "process_version_id"):
            if normalized[field] is not None:
                normalized[field] = ProductionNodeService._positive_int(
                    normalized[field], field
                )
        return normalized

    @staticmethod
    def _validate_capabilities(node, capabilities, db):
        if node["capacity_mode"] == "batch" and not capabilities:
            raise ValidationError("批处理节点至少需要一条有效能力配置")
        signatures = set()
        for capability in capabilities:
            signature = tuple(
                capability.get(field)
                for field in (
                    "product_id",
                    "product_family",
                    "material_code",
                    "specification",
                    "route_version_id",
                    "process_version_id",
                )
            )
            if signature in signatures:
                raise ValidationError("能力限制不允许重复")
            signatures.add(signature)
            if capability["status"] not in {"active", "inactive"}:
                raise ValidationError("能力状态无效")
            if capability["product_id"] is not None and not ProductionNodeRepository.product_exists(
                capability["product_id"], db=db
            ):
                raise ValidationError("能力限制产品不存在")
            process_version = None
            if capability["process_version_id"] is not None:
                process_version_id = ProductionNodeRepository.process_version_process_id(
                    capability["process_version_id"], db=db
                )
                if process_version_id != node["process_id"]:
                    raise ValidationError("能力限制工序版本与节点工序不匹配")
            if capability["route_version_id"] is not None:
                if not ProductionNodeRepository.route_version_exists(
                    capability["route_version_id"], db=db
                ):
                    raise ValidationError("能力限制路线版本不存在")
                if not ProductionNodeRepository.route_version_contains_process(
                    capability["route_version_id"],
                    node["process_id"],
                    capability["process_version_id"],
                    db=db,
                ):
                    raise ValidationError("能力限制路线不包含该节点工序版本")
            batch_values = (
                capability["max_batch_quantity"],
                capability["batch_minutes"],
                capability["changeover_minutes"],
                capability["allow_mixed_orders"],
            )
            if node["capacity_mode"] == "exclusive" and (
                batch_values[0] is not None
                or batch_values[1] is not None
                or float(batch_values[2] or 0) != 0
                or batch_values[3]
            ):
                raise ValidationError("独占节点不能配置批处理能力字段")
            if node["capacity_mode"] == "batch" and (
                batch_values[0] is None or batch_values[1] is None
            ):
                raise ValidationError("批处理节点必须配置批量上限和单批时间")

    @staticmethod
    def replace_capabilities(node_id, data, actor_id):
        node_id = ProductionNodeService._positive_int(node_id, "node_id")
        reason = ProductionNodeService._text(data.get("reason"), "变更原因", 1024)
        key = ProductionNodeService._text(data.get("idempotency_key"), "幂等键", 128)
        capabilities = [
            ProductionNodeService._normalize_capability(item)
            for item in data.get("capabilities", [])
        ]
        command = {"node_id": node_id, "capabilities": capabilities, "reason": reason}
        digest = ProductionNodeService._command_digest(command)
        with BaseService.transaction() as db:
            actor_id = ProductionNodeService._actor_id(actor_id, db)
            replay = ProductionNodeService._replay(
                key, "capabilities_replaced", digest, db
            )
            if replay:
                return replay["capabilities"]
            node = ProductionNodeService._node(node_id, db)
            ProductionNodeService._validate_capabilities(node, capabilities, db)
            before = ProductionNodeRepository.list_capabilities(node_id, db=db)
            after = ProductionNodeRepository.replace_capabilities(
                node_id, capabilities, actor_id, key, reason, db
            )
            ProductionNodeRepository.append_audit_event(
                {
                    "production_node_id": node_id,
                    "event_type": "capabilities_replaced",
                    "actor_id": actor_id,
                    "reason": reason,
                    "before": {"capabilities": before},
                    "after": {"capabilities": after, "command_digest": digest},
                    "idempotency_key": key,
                },
                db,
            )
            return after

    @staticmethod
    def _parse_datetime(value, label):
        try:
            return datetime.fromisoformat(str(value).replace("T", " "))
        except (TypeError, ValueError) as exc:
            raise ValidationError(f"{label}时间格式无效") from exc

    @staticmethod
    def create_calendar_override(node_id, data, actor_id):
        node_id = ProductionNodeService._positive_int(node_id, "node_id")
        reason = ProductionNodeService._text(data.get("reason"), "变更原因", 1024)
        key = ProductionNodeService._text(data.get("idempotency_key"), "幂等键", 128)
        start_at = str(data.get("start_at") or "").replace("T", " ")
        end_at = str(data.get("end_at") or "").replace("T", " ")
        start = ProductionNodeService._parse_datetime(start_at, "开始")
        end = ProductionNodeService._parse_datetime(end_at, "结束")
        if end <= start:
            raise ValidationError("结束时间必须晚于开始时间")
        command = {
            "node_id": node_id,
            "start_at": start_at,
            "end_at": end_at,
            "override_type": data.get("override_type"),
            "reason": reason,
        }
        digest = ProductionNodeService._command_digest(command)
        with BaseService.transaction() as db:
            actor_id = ProductionNodeService._actor_id(actor_id, db)
            replay = ProductionNodeService._replay(
                key, "calendar_override_created", digest, db
            )
            if replay:
                return replay["override"]
            ProductionNodeService._node(node_id, db)
            overlap = ProductionNodeRepository.find_overlapping_active_override(
                node_id, start_at, end_at, db=db
            )
            if overlap:
                raise ConflictError("生产节点已存在重叠的日历覆盖")
            override = ProductionNodeRepository.create_calendar_override(
                node_id, {**data, "start_at": start_at, "end_at": end_at}, actor_id, db
            )
            ProductionNodeRepository.append_audit_event(
                {
                    "production_node_id": node_id,
                    "event_type": "calendar_override_created",
                    "actor_id": actor_id,
                    "reason": reason,
                    "before": {},
                    "after": {"override": override, "command_digest": digest},
                    "idempotency_key": key,
                },
                db,
            )
            return override

    @staticmethod
    def cancel_calendar_override(override_id, data, actor_id):
        override_id = ProductionNodeService._positive_int(override_id, "override_id")
        reason = ProductionNodeService._text(data.get("reason"), "取消原因", 1024)
        key = ProductionNodeService._text(data.get("idempotency_key"), "幂等键", 128)
        command = {"override_id": override_id, "reason": reason}
        digest = ProductionNodeService._command_digest(command)
        with BaseService.transaction() as db:
            actor_id = ProductionNodeService._actor_id(actor_id, db)
            replay = ProductionNodeService._replay(
                key, "calendar_override_cancelled", digest, db
            )
            if replay:
                return replay["override"]
            before = ProductionNodeRepository.find_calendar_override(override_id, db=db)
            if not before:
                raise NotFoundError("生产节点日历覆盖不存在")
            if before["status"] != "active":
                raise ConflictError("只有生效中的日历覆盖可以取消")
            override = ProductionNodeRepository.cancel_calendar_override(
                override_id, actor_id, reason, key, db
            )
            if not override:
                raise ConflictError("日历覆盖状态已变化，请刷新后重试")
            ProductionNodeRepository.append_audit_event(
                {
                    "production_node_id": before["production_node_id"],
                    "event_type": "calendar_override_cancelled",
                    "actor_id": actor_id,
                    "reason": reason,
                    "before": {"override": before},
                    "after": {"override": override, "command_digest": digest},
                    "idempotency_key": key,
                },
                db,
            )
            return override

    @staticmethod
    def list_calendar_overrides(node_id, start_at="", end_at="", limit=500):
        node_id = ProductionNodeService._positive_int(node_id, "node_id")
        limit = ProductionNodeService._limit(limit)
        if start_at and end_at:
            if ProductionNodeService._parse_datetime(end_at, "结束") <= ProductionNodeService._parse_datetime(start_at, "开始"):
                raise ValidationError("结束时间必须晚于开始时间")
        db = BaseService.db()
        ProductionNodeService._node(node_id, db)
        return ProductionNodeRepository.list_calendar_overrides(
            node_id, start_at=start_at, end_at=end_at, limit=limit, db=db
        )

    @staticmethod
    def list_audit_events(node_id, limit=500):
        node_id = ProductionNodeService._positive_int(node_id, "node_id")
        limit = ProductionNodeService._limit(limit)
        db = BaseService.db()
        ProductionNodeService._node(node_id, db)
        return ProductionNodeRepository.list_audit_events(node_id, limit=limit, db=db)
