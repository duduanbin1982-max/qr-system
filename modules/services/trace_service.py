"""Product and order traceability service."""
import math

from modules.domain.errors import AuthorizationError, NotFoundError, ValidationError
from modules.repositories.trace_repository import TraceRepository
from modules.services.access_policy_service import AccessPolicyService


ITEM_FIELDS = (
    "serial_no",
    "position_no",
    "status",
    "weight",
    "production_date",
    "completed_at",
    "created_at",
    "current_process_name",
)
ORDER_FIELDS = (
    "order_no",
    "customer",
    "product_name",
    "product_code",
    "quantity",
    "completed",
    "scrapped",
    "rework",
    "status",
    "plan_start",
    "plan_end",
    "deadline",
    "remark",
    "qr_mode",
    "delivery_status",
    "created_at",
    "updated_at",
)
SERIAL_ORDER_KEYS = {
    "order_no": "trace_order_no",
    "customer": "trace_customer",
    "product_name": "trace_product_name",
    "product_code": "trace_product_code",
    "quantity": "trace_order_quantity",
    "completed": "trace_completed",
    "scrapped": "trace_scrapped",
    "rework": "trace_rework",
    "status": "trace_order_status",
    "plan_start": "trace_plan_start",
    "plan_end": "trace_plan_end",
    "deadline": "trace_deadline",
    "remark": "trace_remark",
    "qr_mode": "trace_qr_mode",
    "delivery_status": "trace_delivery_status",
    "created_at": "trace_order_created",
    "updated_at": "trace_order_updated",
}

COLLECTION_FIELDS = {
    "items": ITEM_FIELDS,
    "work_records": (
        "id", "serial_no", "quantity", "status", "type", "remark",
        "created_at", "process_name", "process_name_source", "worker_name",
    ),
    "rework_records": (
        "id", "quantity", "reason", "status", "created_at", "completed_at",
        "process_name", "process_name_source", "worker_name",
    ),
    "quality_inspections": (
        "id", "inspection_type", "quantity_checked", "quantity_passed",
        "quantity_failed", "result", "notes", "inspected_at", "created_at",
        "defect_category", "defect_quantity", "defect_level", "score_total",
        "serial_no", "process_name", "process_name_source", "inspector_name",
        "task_no", "ncr_no",
    ),
    "quality_tasks": (
        "id", "task_no", "inspection_type", "trigger_type", "gate_mode",
        "sample_qty", "priority", "status", "serial_no", "due_at",
        "started_at", "completed_at", "created_at", "process_name",
        "process_name_source", "standard_no", "standard_name", "assigned_name",
    ),
    "quality_nonconformances": (
        "id", "ncr_no", "defect_category", "defect_level", "defect_quantity",
        "description", "disposition", "status", "root_cause",
        "corrective_action", "verification_result", "due_at", "closed_at",
        "created_at", "serial_no", "process_name", "process_name_source",
        "owner_name", "task_no", "action_count",
    ),
    "quality_capa": (
        "id", "capa_no", "title", "problem_description", "root_cause",
        "corrective_action", "preventive_action", "due_at", "status",
        "effectiveness_result", "verified_at", "created_at", "ncr_no",
        "owner_name", "verifier_name",
    ),
    "material_consumptions": (
        "id", "quantity", "notes", "operator_name", "created_at",
        "material_name", "material_spec", "process_name", "process_name_source",
    ),
    "inventory_logs": (
        "id", "type", "quantity", "remark", "operator_name", "created_at",
        "product_model", "product_name",
    ),
    "shipments": (
        "id", "shipment_no", "customer", "status", "total_quantity",
        "order_quantity", "created_at", "completed_at",
    ),
}

DEFAULT_PAGE_SIZE = 100
MAX_PAGE_SIZE = 200


def _item_dto(row):
    data = dict(row)
    return {field: data.get(field) for field in ITEM_FIELDS}


def _order_dto(row):
    data = dict(row)
    return {field: data.get(field) for field in ORDER_FIELDS}


def _serial_order_dto(item):
    return {
        field: item.get(source_field)
        for field, source_field in SERIAL_ORDER_KEYS.items()
    }


def _collection_dtos(name, rows):
    fields = COLLECTION_FIELDS[name]
    return [{field: dict(row).get(field) for field in fields} for row in rows]


def _history_evidence(collections, *, scope="returned_records"):
    counts = {"snapshot": 0, "version": 0, "legacy_fallback": 0, "missing": 0}
    for rows in collections.values():
        for row in rows:
            source = dict(row).get("process_name_source")
            if source in counts:
                counts[source] += 1
    return {
        "counts": counts,
        "has_legacy_fallback": counts["legacy_fallback"] > 0,
        "has_missing": counts["missing"] > 0,
        "scope": scope,
    }


class TraceService:
    """Build stable public traceability views from repository records."""

    @staticmethod
    def _validate_code(value, label, max_length):
        value = (value or "").strip()
        if not value:
            raise ValidationError(f"{label}不能为空")
        if len(value) > max_length:
            raise ValidationError(f"{label}过长")
        return value

    @staticmethod
    def _require_scope(order_id, data_scope_pids, db):
        if not TraceRepository.order_has_process_in_scope(
            order_id, data_scope_pids, db=db
        ):
            raise AuthorizationError("无权限访问此订单")

    @staticmethod
    def _resolve_scope(order_id, data_scope_pids, actor, db):
        if actor is not None:
            return AccessPolicyService.get_user_process_ids(
                actor, order_id=order_id, db=db
            )
        return data_scope_pids

    @staticmethod
    def _load_serial_collections(serial_no, order_id, db):
        return {
            "work_records": TraceRepository.find_work_records_by_serial(
                serial_no, order_id, db=db
            ),
            "quality_inspections": TraceRepository.find_quality_inspections_by_serial(
                serial_no, order_id, db=db
            ),
            "quality_tasks": TraceRepository.find_quality_tasks_by_serial(
                serial_no, order_id, db=db
            ),
            "quality_nonconformances": TraceRepository.find_quality_nonconformances_by_serial(
                serial_no, order_id, db=db
            ),
            "quality_capa": TraceRepository.find_quality_capa_by_serial(
                serial_no, order_id, db=db
            ),
            "material_consumptions": TraceRepository.find_material_consumptions_by_serial(
                serial_no, order_id, db=db
            ),
            "rework_records": TraceRepository.find_rework_records_by_order(
                order_id, db=db
            ),
            "manual_material_consumptions": TraceRepository.find_order_scope_material_consumptions(
                order_id, db=db
            ),
            "inventory_logs": TraceRepository.find_inventory_logs_by_order(
                order_id, db=db
            ),
            "shipments": TraceRepository.find_shipments_by_order_id(order_id, db=db),
        }

    @staticmethod
    def trace(serial_no, data_scope_pids=None, actor=None):
        serial_no = TraceService._validate_code(serial_no, "序列号", 200)

        with TraceRepository.read_snapshot() as (db, snapshot_at):
            item_row = TraceRepository.find_product_item_by_serial(serial_no, db=db)
            if not item_row:
                raise NotFoundError("产品序列号不存在")

            item_data = dict(item_row)
            order_id = item_data.get("trace_order_id")
            if item_data.get("trace_order_deleted_at") is not None:
                # Keep archived-order existence indistinguishable from a missing serial.
                raise NotFoundError("产品序列号不存在")
            if order_id:
                TraceService._require_scope(
                    order_id,
                    TraceService._resolve_scope(
                        order_id, data_scope_pids, actor, db
                    ),
                    db,
                )
                collections = TraceService._load_serial_collections(
                    serial_no, order_id, db
                )
            else:
                collections = {
                    "work_records": [],
                    "quality_inspections": [],
                    "quality_tasks": [],
                    "quality_nonconformances": [],
                    "quality_capa": [],
                    "material_consumptions": [],
                    "rework_records": [],
                    "manual_material_consumptions": [],
                    "inventory_logs": [],
                    "shipments": [],
                }

            serial_scope = {
                name: _collection_dtos(name, collections[name])
                for name in (
                    "work_records",
                    "quality_inspections",
                    "quality_tasks",
                    "quality_nonconformances",
                    "quality_capa",
                    "material_consumptions",
                )
            }
            order_scope = {
                "rework_records": _collection_dtos(
                    "rework_records", collections["rework_records"]
                ),
                "manual_material_consumptions": _collection_dtos(
                    "material_consumptions",
                    collections["manual_material_consumptions"],
                ),
                "inventory_logs": _collection_dtos(
                    "inventory_logs", collections["inventory_logs"]
                ),
                "shipments": _collection_dtos("shipments", collections["shipments"]),
            }
            evidence = _history_evidence(collections, scope="serial_result")
            return {
                "item": _item_dto(item_data),
                "order": _serial_order_dto(item_data) if order_id else None,
                "serial_scope": serial_scope,
                "order_scope": order_scope,
                "meta": {
                    "scope": "serial",
                    "snapshot_at": snapshot_at,
                    "history_evidence": evidence,
                },
                **serial_scope,
                "rework_records": [],
                "inventory_logs": [],
                "shipments": [],
            }

    @staticmethod
    def trace_by_order(
        order_no,
        page=1,
        per_page=DEFAULT_PAGE_SIZE,
        data_scope_pids=None,
        actor=None,
        collection_pages=None,
        collection_per_pages=None,
    ):
        order_no = TraceService._validate_code(order_no, "订单号", 100)
        page, per_page = TraceService._pagination(page, per_page)
        collection_pages = collection_pages or {}
        collection_per_pages = collection_per_pages or {}

        with TraceRepository.read_snapshot() as (db, snapshot_at):
            order_row = TraceRepository.find_order_by_no(order_no, db=db)
            if not order_row:
                raise NotFoundError("订单不存在")

            order_data = dict(order_row)
            order_id = order_data["trace_order_id"]
            TraceService._require_scope(
                order_id,
                TraceService._resolve_scope(
                    order_id, data_scope_pids, actor, db
                ),
                db,
            )
            totals = TraceRepository.count_order_trace_collections(order_id, db=db)
            queries = {
                "items": TraceRepository.find_product_items_by_order,
                "work_records": TraceRepository.find_work_records_by_order,
                "rework_records": TraceRepository.find_rework_records_by_order,
                "quality_inspections": TraceRepository.find_quality_inspections_by_order,
                "quality_tasks": TraceRepository.find_quality_tasks_by_order,
                "quality_nonconformances": TraceRepository.find_quality_nonconformances_by_order,
                "quality_capa": TraceRepository.find_quality_capa_by_order,
                "material_consumptions": TraceRepository.find_material_consumptions_by_order,
                "inventory_logs": TraceRepository.find_inventory_logs_by_order,
                "shipments": TraceRepository.find_shipments_by_order_id,
            }
            raw_collections = {}
            pagination = {}
            for name, query in queries.items():
                current_page = collection_pages.get(
                    name, page if name == "items" else 1
                )
                current_per_page = collection_per_pages.get(name, per_page)
                current_page, current_per_page = TraceService._pagination(
                    current_page, current_per_page
                )
                offset = (current_page - 1) * current_per_page
                raw_collections[name] = query(
                    order_id, current_per_page, offset, db=db
                )
                total = totals.get(name, 0)
                pagination[name] = {
                    "page": current_page,
                    "per_page": current_per_page,
                    "total": total,
                    "total_pages": max(1, math.ceil(total / current_per_page)),
                }

            collections = {
                name: _collection_dtos(name, rows)
                for name, rows in raw_collections.items()
            }
            returned_evidence = _history_evidence(
                raw_collections, scope="returned_page"
            )
            full_counts = TraceRepository.count_order_trace_history_evidence(
                order_id, db=db
            )
            evidence = {
                "counts": full_counts,
                "page_counts": returned_evidence["counts"],
                "has_legacy_fallback": full_counts["legacy_fallback"] > 0,
                "has_missing": full_counts["missing"] > 0,
                "scope": "full_order",
            }
            return {
                "order": _order_dto(order_data),
                **collections,
                "meta": {
                    "scope": "order",
                    "snapshot_at": snapshot_at,
                    "page": pagination["items"]["page"],
                    "per_page": pagination["items"]["per_page"],
                    "total_pages": pagination["items"]["total_pages"],
                    "totals": totals,
                    "pagination": pagination,
                    "history_evidence": evidence,
                },
            }

    @staticmethod
    def _pagination(page, per_page):
        try:
            page = int(page)
            per_page = int(per_page)
        except (TypeError, ValueError) as exc:
            raise ValidationError("分页参数必须是整数") from exc
        if page < 1:
            raise ValidationError("页码必须大于等于 1")
        if per_page < 1 or per_page > MAX_PAGE_SIZE:
            raise ValidationError(f"每页数量必须在 1 到 {MAX_PAGE_SIZE} 之间")
        return page, per_page
