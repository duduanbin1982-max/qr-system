"""Product and order traceability service."""
import math

from modules.domain.errors import NotFoundError, ValidationError
from modules.repositories.trace_repository import TraceRepository


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
DEFAULT_PAGE_SIZE = 100
MAX_PAGE_SIZE = 200


def _row_dicts(rows):
    return [dict(row) for row in rows]


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


class TraceService:
    """Build stable public traceability views from repository records."""

    @staticmethod
    def trace(serial_no):
        serial_no = (serial_no or "").strip()
        if not serial_no:
            raise ValidationError("序列号不能为空")
        if len(serial_no) > 200:
            raise ValidationError("序列号过长")

        with TraceRepository.read_snapshot() as (db, snapshot_at):
            item_row = TraceRepository.find_product_item_by_serial(serial_no, db=db)
            if not item_row:
                raise NotFoundError("产品序列号不存在")

            item_data = dict(item_row)
            order_id = item_data.get("trace_order_id")
            order = _serial_order_dto(item_data) if order_id else None
            work_records = []
            rework_records = []
            quality_inspections = []
            quality_tasks = []
            quality_nonconformances = []
            quality_capa = []
            material_consumptions = []
            manual_material_consumptions = []
            inventory_logs = []
            shipments = []

            if order_id:
                work_records = _row_dicts(
                    TraceRepository.find_work_records_by_serial(serial_no, order_id, db=db)
                )
                rework_records = _row_dicts(
                    TraceRepository.find_rework_records_by_order(order_id, db=db)
                )
                quality_inspections = _row_dicts(
                    TraceRepository.find_quality_inspections_by_serial(serial_no, order_id, db=db)
                )
                quality_tasks = _row_dicts(
                    TraceRepository.find_quality_tasks_by_serial(serial_no, order_id, db=db)
                )
                quality_nonconformances = _row_dicts(
                    TraceRepository.find_quality_nonconformances_by_serial(serial_no, order_id, db=db)
                )
                quality_capa = _row_dicts(
                    TraceRepository.find_quality_capa_by_serial(serial_no, order_id, db=db)
                )
                material_consumptions = _row_dicts(
                    TraceRepository.find_material_consumptions_by_serial(serial_no, order_id, db=db)
                )
                manual_material_consumptions = _row_dicts(
                    TraceRepository.find_order_scope_material_consumptions(order_id, db=db)
                )
                inventory_logs = _row_dicts(
                    TraceRepository.find_inventory_logs_by_order(order_id, db=db)
                )
                shipments = _row_dicts(
                    TraceRepository.find_shipments_by_order_id(order_id, db=db)
                )

            serial_scope = {
                "work_records": work_records,
                "quality_inspections": quality_inspections,
                "quality_tasks": quality_tasks,
                "quality_nonconformances": quality_nonconformances,
                "quality_capa": quality_capa,
                "material_consumptions": material_consumptions,
            }
            order_scope = {
                "rework_records": rework_records,
                "manual_material_consumptions": manual_material_consumptions,
                "inventory_logs": inventory_logs,
                "shipments": shipments,
            }
            return {
                "item": _item_dto(item_data),
                "order": order,
                "serial_scope": serial_scope,
                "order_scope": order_scope,
                "meta": {"scope": "serial", "snapshot_at": snapshot_at},
                **serial_scope,
                "rework_records": [],
                "inventory_logs": [],
                "shipments": [],
            }

    @staticmethod
    def trace_by_order(order_no, page=1, per_page=DEFAULT_PAGE_SIZE):
        order_no = (order_no or "").strip()
        if not order_no:
            raise ValidationError("订单号不能为空")
        if len(order_no) > 100:
            raise ValidationError("订单号过长")
        page, per_page = TraceService._pagination(page, per_page)
        offset = (page - 1) * per_page

        with TraceRepository.read_snapshot() as (db, snapshot_at):
            order_row = TraceRepository.find_order_by_no(order_no, db=db)
            if not order_row:
                raise NotFoundError("订单不存在")

            order_data = dict(order_row)
            order_id = order_data["trace_order_id"]
            totals = TraceRepository.count_order_trace_collections(order_id, db=db)
            collections = {
                "items": _row_dicts(
                    TraceRepository.find_product_items_by_order(
                        order_id, per_page, offset, db=db
                    )
                ),
                "work_records": _row_dicts(
                    TraceRepository.find_work_records_by_order(
                        order_id, per_page, offset, db=db
                    )
                ),
                "rework_records": _row_dicts(
                    TraceRepository.find_rework_records_by_order(
                        order_id, per_page, offset, db=db
                    )
                ),
                "quality_inspections": _row_dicts(
                    TraceRepository.find_quality_inspections_by_order(
                        order_id, per_page, offset, db=db
                    )
                ),
                "quality_tasks": _row_dicts(
                    TraceRepository.find_quality_tasks_by_order(
                        order_id, per_page, offset, db=db
                    )
                ),
                "quality_nonconformances": _row_dicts(
                    TraceRepository.find_quality_nonconformances_by_order(
                        order_id, per_page, offset, db=db
                    )
                ),
                "quality_capa": _row_dicts(
                    TraceRepository.find_quality_capa_by_order(
                        order_id, per_page, offset, db=db
                    )
                ),
                "material_consumptions": _row_dicts(
                    TraceRepository.find_material_consumptions_by_order(
                        order_id, per_page, offset, db=db
                    )
                ),
                "inventory_logs": _row_dicts(
                    TraceRepository.find_inventory_logs_by_order(
                        order_id, per_page, offset, db=db
                    )
                ),
                "shipments": _row_dicts(
                    TraceRepository.find_shipments_by_order_id(
                        order_id, per_page, offset, db=db
                    )
                ),
            }
            total_pages = max(
                1,
                max(math.ceil(total / per_page) for total in totals.values()),
            )
            return {
                "order": _order_dto(order_data),
                **collections,
                "meta": {
                    "scope": "order",
                    "snapshot_at": snapshot_at,
                    "page": page,
                    "per_page": per_page,
                    "total_pages": total_pages,
                    "totals": totals,
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
