"""
qr-system ? TraceService???????????

? routes/trace.py ???????SQL ??? TraceRepository?
"""
from modules.repositories.trace_repository import TraceRepository

# product_items ??????
ITEM_FIELDS = [
    'id', 'serial_no', 'order_id', 'position_no',
    'qr_content', 'status', 'current_process_id', 'created_at'
]




class TraceService:
    """?????????"""

    @staticmethod
    def trace(serial_no):
        """???????????

        Args:
            serial_no: ??????? trim?

        Returns:
            dict with keys: item, order, work_records, rework_records, shipments

        Raises:
            ValueError: ?????
        """
        serial_no = serial_no.strip()
        if not serial_no:
            raise ValueError('????????')
        if len(serial_no) > 200:
            raise ValueError('?????')

        # 1. ?????
        item_row = TraceRepository.find_product_item_by_serial(serial_no)
        if not item_row:
            return {
                'item': None, 'order': None,
                'work_records': [], 'rework_records': [], 'shipments': []
            }

        item_dict = dict(item_row)

        # 2. ??????
        order = None
        order_id = item_row['order_id']
        if order_id:
            order = {
                'order_no': item_row.get('order_no', ''),
                'product_name': item_row.get('product_name', ''),
                'quantity': item_row.get('order_quantity', 0),
                'completed': item_row.get('completed', 0),
                'status': item_row.get('order_status', ''),
                'created_at': item_row.get('order_created', ''),
                'customer': item_row.get('customer', ''),
            }

        # 3. ?? item_dict???? product_items ???
        clean_item = {k: item_dict.get(k) for k in ITEM_FIELDS if k in item_dict}

        # 4. ????
        work_records = []
        if order_id:
            rows = TraceRepository.find_work_records_by_serial(serial_no, order_id)
            work_records = [dict(r) for r in rows]

        # 5. ????
        rework_records = []
        if order_id:
            rows = TraceRepository.find_rework_records_by_order(order_id)
            rework_records = [dict(r) for r in rows]

        # 6. 质检记录
        quality_inspections = []
        if order_id:
            rows = TraceRepository.find_quality_inspections_by_order(order_id)
            quality_inspections = [dict(r) for r in rows]

        # 7. 物料消耗
        material_consumptions = []
        if order_id:
            rows = TraceRepository.find_material_consumptions_by_order(order_id)
            material_consumptions = [dict(r) for r in rows]

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

        return {
            'item': clean_item,
            'order': order,
            'work_records': work_records,
            'rework_records': rework_records,
            'quality_inspections': quality_inspections,
            'material_consumptions': material_consumptions,
            'inventory_logs': inventory_logs,
            'shipments': shipments,
        }
    @staticmethod
    def trace_by_order(order_no):
        """按订单号追溯
        
        Returns:
            dict with keys: order, items, work_records, rework_records, shipments
        """
        order_no = order_no.strip()
        if not order_no:
            raise ValueError("订单号不能为空")
        if len(order_no) > 100:
            raise ValueError("订单号过长")

        # 1. 查订单
        order_row = TraceRepository.find_order_by_no(order_no)
        if not order_row:
            return {"order": None, "items": [], "work_records": [], "rework_records": [], "shipments": []}

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
            "material_consumptions": material_consumptions,
            "inventory_logs": inventory_logs,
            "shipments": shipments,
        }
