"""qr-system — ImportsService"""
from modules.services import BaseService


class ImportsService:
    @staticmethod
    def check_order_exists(order_no):
        db = BaseService.db()
        return db.execute("SELECT id FROM orders WHERE order_no = ?", (order_no,)).fetchone()

    @staticmethod
    def insert_order(data):
        db = BaseService.db()
        with BaseService.transaction() as txn:
            txn.execute(
                "INSERT INTO orders (order_no, product_name, product_code, customer, quantity, "
                "status, plan_start, plan_end, deadline, remark) VALUES (?,?,?,?,?,?,?,?,?,?)",
                (data['order_no'], data.get('product_name',''), data.get('product_code',''),
                 data.get('customer',''), data.get('quantity',0), data.get('status','pending'),
                 data.get('plan_start',''), data.get('plan_end',''), data.get('deadline',''),
                 data.get('remark',''))
            )
            return txn.lastrowid

    @staticmethod
    def insert_product(data):
        db = BaseService.db()
        with BaseService.transaction() as txn:
            txn.execute(
                "INSERT INTO products (product_name, model, spec, category, weight, price) "
                "VALUES (?,?,?,?,?,?)",
                (data.get('product_name',''), data.get('model',''), data.get('spec',''),
                 data.get('category',''), data.get('weight',0), data.get('price',0))
            )
            return txn.lastrowid

    @staticmethod
    def check_customer_exists(name):
        db = BaseService.db()
        return db.execute("SELECT id FROM customers WHERE name = ?", (name,)).fetchone()

    @staticmethod
    def insert_customer(data):
        db = BaseService.db()
        with BaseService.transaction() as txn:
            txn.execute(
                "INSERT INTO customers (name, contact, phone, address, remark) VALUES (?,?,?,?,?)",
                (data.get('name',''), data.get('contact',''), data.get('phone',''),
                 data.get('address',''), data.get('remark',''))
            )
            return txn.lastrowid
