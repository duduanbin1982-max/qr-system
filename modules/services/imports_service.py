"""qr-system - ImportsService (Repository-refactored)"""
from modules.services import BaseService
from modules.repositories.imports_repository import ImportsRepository


class ImportsService:
    @staticmethod
    def check_order_exists(order_no):
        return ImportsRepository.check_order_exists(order_no)

    @staticmethod
    def insert_order(data):
        with BaseService.transaction() as txn:
            return ImportsRepository.insert_order_txn(data, db=txn)

    @staticmethod
    def insert_product(data):
        with BaseService.transaction() as txn:
            return ImportsRepository.insert_product_txn(data, db=txn)

    @staticmethod
    def check_customer_exists(name):
        return ImportsRepository.check_customer_exists(name)

    @staticmethod
    def insert_customer(data):
        with BaseService.transaction() as txn:
            return ImportsRepository.insert_customer_txn(data, db=txn)
