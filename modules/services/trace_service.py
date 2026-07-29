"""Product and order traceability service."""
from modules.domain.errors import NotFoundError, ValidationError
from modules.repositories.trace_repository import TraceRepository

# Public product-item fields returned by trace APIs.
ITEM_FIELDS = [
    'id', 'serial_no', 'order_id', 'position_no',
    'qr_content', 'status', 'current_process_id', 'created_at'
]




class TraceService:
    """Build traceability views from repository records."""

    @staticmethod
    def trace(serial_no):
        """Trace one product item by serial number.

        Args:
            serial_no: product serial number; surrounding whitespace is ignored

        Returns:
            dict with keys: item, order, work_records, rework_records, shipments

        Raises:
            ValidationError: when the serial number is empty or too long
        """
        serial_no = serial_no.strip()
        if not serial_no:
            raise ValidationError('序列号不能为空')
        if len(serial_no) > 200:
            raise ValidationError('序列号过长')

        # 1. Load the product item and joined order fields.
        item_row = TraceRepository.find_product_item_by_serial(serial_no)
        if not item_row:
            raise NotFoundError('产品序列号不存在')

        item_dict = dict(item_row)

        # 2. Normalize the order summary.
        order = None
        order_id = item_row['order_id']
        if order_id:
            order = {
                'order_no': item_dict.get('trace_order_no', ''),
                'product_name': item_dict.get('trace_product_name', ''),
                'quantity': item_dict.get('trace_order_quantity', 0),
                'completed': item_dict.get('trace_completed', 0),
                'status': item_dict.get('trace_order_status', ''),
                'created_at': item_dict.get('trace_order_created', ''),
                'customer': item_dict.get('trace_customer', ''),
            }

        # 3. Keep only public product-item fields.
        clean_item = {k: item_dict.get(k) for k in ITEM_FIELDS if k in item_dict}

        # 4. Load work reports.
        work_records = []
        if order_id:
            rows = TraceRepository.find_work_records_by_serial(serial_no, order_id)
            work_records = [dict(r) for r in rows]

        # 5. Load rework records.
        rework_records = []
        if order_id:
            rows = TraceRepository.find_rework_records_by_order(order_id)
            rework_records = [dict(r) for r in rows]

        # 6. 质检记录
        quality_inspections = []
        if order_id:
            rows = TraceRepository.find_quality_inspections_by_serial(serial_no, order_id)
            quality_inspections = [dict(r) for r in rows]

        quality_tasks = []
        quality_nonconformances = []
        quality_capa = []
        if order_id:
            quality_tasks = [
                dict(row) for row in TraceRepository.find_quality_tasks_by_serial(serial_no, order_id)
            ]
            quality_nonconformances = [
                dict(row)
                for row in TraceRepository.find_quality_nonconformances_by_serial(serial_no, order_id)
            ]
            quality_capa = [
                dict(row) for row in TraceRepository.find_quality_capa_by_serial(serial_no, order_id)
            ]

        # 7. 物料消耗
        material_consumptions = []
        manual_material_consumptions = []
        if order_id:
            rows = TraceRepository.find_material_consumptions_by_serial(serial_no, order_id)
            material_consumptions = [dict(r) for r in rows]
            rows = TraceRepository.find_order_scope_material_consumptions(order_id)
            manual_material_consumptions = [dict(r) for r in rows]

        # 8. 入库记录
        inventory_logs = []
        if order_id:
            rows = TraceRepository.find_inventory_logs_by_order(order_id)
            inventory_logs = [dict(r) for r in rows]

        # 9. 发货记录（按order_id精确关联）
        shipments = []
        if order_id:
            rows = TraceRepository.find_shipments_by_order_id(order_id)
            shipments = [dict(r) for r in rows]

        serial_scope = {
            'work_records': work_records,
            'quality_inspections': quality_inspections,
            'quality_tasks': quality_tasks,
            'quality_nonconformances': quality_nonconformances,
            'quality_capa': quality_capa,
            'material_consumptions': material_consumptions,
        }
        order_scope = {
            'rework_records': rework_records,
            'manual_material_consumptions': manual_material_consumptions,
            'inventory_logs': inventory_logs,
            'shipments': shipments,
        }

        return {
            'item': clean_item,
            'order': order,
            'serial_scope': serial_scope,
            'order_scope': order_scope,
            **serial_scope,
            'rework_records': [],
            'inventory_logs': [],
            'shipments': [],
        }
    @staticmethod
    def trace_by_order(order_no):
        """按订单号追溯
        
        Returns:
            dict with keys: order, items, work_records, rework_records, shipments
        """
        order_no = order_no.strip()
        if not order_no:
            raise ValidationError("订单号不能为空")
        if len(order_no) > 100:
            raise ValidationError("订单号过长")

        # 1. 查订单
        order_row = TraceRepository.find_order_by_no(order_no)
        if not order_row:
            raise NotFoundError("订单不存在")

        order = dict(order_row)
        order_id = order["id"]

        # 2. 查该订单全部产品项
        item_rows = TraceRepository.find_product_items_by_order(order_id)
        items = [dict(r) for r in item_rows]

        # 3. 查全部报工记录
        wr_rows = TraceRepository.find_work_records_by_order(order_id)
        work_records = [dict(r) for r in wr_rows]

        # 4. 查返工记录
        rr_rows = TraceRepository.find_rework_records_by_order(order_id)
        rework_records = [dict(r) for r in rr_rows]

        # 5. 查质检记录
        qi_rows = TraceRepository.find_quality_inspections_by_order(order_id)
        quality_inspections = [dict(r) for r in qi_rows]

        quality_tasks = [dict(row) for row in TraceRepository.find_quality_tasks_by_order(order_id)]
        quality_nonconformances = [
            dict(row) for row in TraceRepository.find_quality_nonconformances_by_order(order_id)
        ]
        quality_capa = [dict(row) for row in TraceRepository.find_quality_capa_by_order(order_id)]

        # 6. 查物料消耗
        mc_rows = TraceRepository.find_material_consumptions_by_order(order_id)
        material_consumptions = [dict(r) for r in mc_rows]

        # 7. 查入库记录
        il_rows = TraceRepository.find_inventory_logs_by_order(order_id)
        inventory_logs = [dict(r) for r in il_rows]

        # 8. 查发货记录（按order_id精确关联）
        sh_rows = TraceRepository.find_shipments_by_order_id(order_id)
        shipments = [dict(r) for r in sh_rows]

        return {
            "order": order,
            "items": items,
            "work_records": work_records,
            "rework_records": rework_records,
            "quality_inspections": quality_inspections,
            "quality_tasks": quality_tasks,
            "quality_nonconformances": quality_nonconformances,
            "quality_capa": quality_capa,
            "material_consumptions": material_consumptions,
            "inventory_logs": inventory_logs,
            "shipments": shipments,
        }
