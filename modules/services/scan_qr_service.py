"""qr-system - ScanQRService (Repository-refactored)"""
import json
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
            for i in range(1, quantity + 1):
                serial_no = order_no + "-" + str(i).zfill(3)
                qr_content = json.dumps({
                    "t": "pi", "sn": serial_no, "oid": order_id, "on": order_no
                }, ensure_ascii=False)
                ScanQRRepository.insert_product_item_txn(serial_no, order_id, i, qr_content, db=txn)
        return ScanQRRepository.find_items_by_order(order_id)

    @staticmethod
    def find_product_code(product_name):
        return ScanQRRepository.find_product_code(product_name)

    @staticmethod
    def set_qr_mode(order_id, mode):
        with BaseService.transaction() as txn:
            ScanQRRepository.set_qr_mode_txn(order_id, mode, db=txn)
