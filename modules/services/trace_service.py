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

# ? JOIN ??????? order ?????
ORDER_POP_FIELDS = [
    'order_no', 'product_name', 'order_quantity', 'completed',
    'order_status', 'order_created', 'customer'
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
                'order_no': item_dict.pop('order_no', ''),
                'product_name': item_dict.pop('product_name', ''),
                'quantity': item_dict.pop('order_quantity', 0),
                'completed': item_dict.pop('completed', 0),
                'status': item_dict.pop('order_status', ''),
                'created_at': item_dict.pop('order_created', ''),
                'customer': item_dict.pop('customer', ''),
            }
        else:
            for k in ORDER_POP_FIELDS:
                item_dict.pop(k, None)

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

        # 6. ????
        shipments = []
        if order and order.get('product_name'):
            rows = TraceRepository.find_shipments_by_product_name(order['product_name'])
            shipments = [dict(r) for r in rows]

        return {
            'item': clean_item,
            'order': order,
            'work_records': work_records,
            'rework_records': rework_records,
            'shipments': shipments,
        }
