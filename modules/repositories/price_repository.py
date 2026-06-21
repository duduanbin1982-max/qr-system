"""qr-system — PriceRepository（工价数据访问层）
All raw SQL lives here. Methods accept optional db for transaction sharing.
"""
from modules.services import BaseService


class PriceRepository:
    """Route price database operations — queries + writes, no business logic."""

    @staticmethod
    def find_route_items(category='', db=None):
        db = db or BaseService.db()
        cat_clause = ''
        cat_params = []
        if category:
            cat_clause = 'AND p.category = ?'
            cat_params.append(category)
        return db.execute(
            'SELECT pri.route_id, pri.seq_order, pri.process_id, '
            'p.name as process_name, p.category, '
            'pr.name as route_name, pr.status as route_status '
            'FROM process_route_items pri '
            'JOIN processes p ON pri.process_id = p.id '
            'JOIN process_routes pr ON pri.route_id = pr.id '
            'WHERE pr.status = \'active\' ' + cat_clause + ' '
            'ORDER BY pri.route_id, pri.seq_order',
            cat_params
        ).fetchall()

    @staticmethod
    def find_active_route_prices(db=None):
        db = db or BaseService.db()
        return db.execute(
            'SELECT rp.*, p.category FROM route_prices rp '
            'JOIN processes p ON rp.process_id = p.id WHERE rp.status = \'active\''
        ).fetchall()

    @staticmethod
    def find_process_route_by_id(route_id, db=None):
        db = db or BaseService.db()
        return db.execute(
            'SELECT * FROM process_routes WHERE id = ?', (route_id,)
        ).fetchone()

    @staticmethod
    def find_route_steps(route_id, db=None):
        db = db or BaseService.db()
        return db.execute(
            'SELECT pri.seq_order, pri.process_id, p.name as process_name, p.category, '
            'rp.id as price_id, rp.unit_price, rp.effective_date, rp.remark '
            'FROM process_route_items pri '
            'JOIN processes p ON pri.process_id = p.id '
            'LEFT JOIN route_prices rp ON rp.route_id = pri.route_id '
            'AND rp.process_id = pri.process_id AND rp.status = \'active\' '
            'WHERE pri.route_id = ? ORDER BY pri.seq_order',
            (route_id,)
        ).fetchall()

    @staticmethod
    def find_valid_route_processes(route_id, db=None):
        db = db or BaseService.db()
        rows = db.execute(
            'SELECT process_id FROM process_route_items WHERE route_id = ?', (route_id,)
        ).fetchall()
        return set(r['process_id'] for r in rows)

    @staticmethod
    def find_route_price(route_id, process_id, db=None):
        db = db or BaseService.db()
        return db.execute(
            'SELECT id, unit_price, effective_date, remark FROM route_prices '
            'WHERE route_id = ? AND process_id = ?',
            (route_id, process_id)
        ).fetchone()

    @staticmethod
    def insert_route_price_history(route_id, process_id, old_price, new_price,
                                   effective_date, remark, db=None):
        db = db or BaseService.db()
        db.execute(
            'INSERT INTO route_price_history '
            '(route_id, process_id, old_price, new_price, effective_date, remark) '
            'VALUES (?,?,?,?,?,?)',
            (route_id, process_id, old_price, new_price, effective_date, remark)
        )

    @staticmethod
    def update_route_price(price_id, unit_price, effective_date, remark, db=None):
        db = db or BaseService.db()
        db.execute(
            'UPDATE route_prices SET unit_price = ?, effective_date = ?, remark = ?, '
            'updated_at = datetime("now","localtime") WHERE id = ?',
            (unit_price, effective_date, remark, price_id)
        )

    @staticmethod
    def insert_route_price(route_id, process_id, unit_price, effective_date, remark, db=None):
        db = db or BaseService.db()
        db.execute(
            'INSERT INTO route_prices (route_id, process_id, unit_price, '
            'effective_date, remark, status) VALUES (?, ?, ?, ?, ?, \'active\')',
            (route_id, process_id, unit_price, effective_date or '', remark or '')
        )

    @staticmethod
    def get_route_price_history(route_id, db=None):
        db = db or BaseService.db()
        return db.execute(
            "SELECT h.*, p.name as process_name "
            "FROM route_price_history h "
            "LEFT JOIN processes p ON h.process_id = p.id "
            "WHERE h.route_id = ? "
            "ORDER BY h.created_at DESC LIMIT 50",
            (route_id,)
        ).fetchall()
