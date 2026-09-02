"""qr-system - ScanQRService (Repository-refactored)"""
import json
from modules.domain.errors import ConflictError
from modules.services import BaseService
from modules.repositories.scan_qr_repository import ScanQRRepository


class ScanQRService:
    @staticmethod
    def find_order_by_no(order_no):
        return ScanQRRepository.find_order_by_no(order_no)

    @staticmethod
    def find_order_by_id(order_id):
        return ScanQRRepository.find_order_by_id(order_id)

    @staticmethod
    def find_order_for_qr(order_id):
        return ScanQRRepository.find_order_for_qr(order_id)

    @staticmethod
    def find_items_by_order(order_id):
        return ScanQRRepository.find_items_by_order(order_id)

    @staticmethod
    def generate_serial_numbers(order_id, order_no, quantity):
        with BaseService.transaction() as txn:
            active_items = ScanQRRepository.find_items_by_order(order_id, db=txn)
            if active_items:
                if len(active_items) != quantity:
                    raise ConflictError(
                        f'订单数量为 {quantity}，但已有 {len(active_items)} 个有效序列件；'
                        '请先修正订单或序列件数量'
                    )
                return active_items
            if ScanQRRepository.count_all_items_by_order(order_id, db=txn):
                raise ConflictError('该订单存在已作废序列件，不能自动重新生成相同序列号')
            for i in range(1, quantity + 1):
                serial_no = order_no + "-" + str(i).zfill(3)
                qr_content = json.dumps({
                    "t": "pi", "sn": serial_no, "oid": order_id, "on": order_no
                }, ensure_ascii=False)
                ScanQRRepository.insert_product_item_txn(serial_no, order_id, i, qr_content, db=txn)
            generated = ScanQRRepository.find_items_by_order(order_id, db=txn)
            if len(generated) != quantity:
                raise ConflictError('序列件生成数量与订单数量不一致，请刷新后重试')
            return generated

    @staticmethod
    def find_product_code(product_name):
        return ScanQRRepository.find_product_code(product_name)

    @staticmethod
    def set_qr_mode(order_id, mode):
        with BaseService.transaction() as txn:
            ScanQRRepository.set_qr_mode_txn(order_id, mode, db=txn)
