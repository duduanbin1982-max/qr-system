"""
qr-system ? ApprovalRepository???????

???????? ? approval_records ?? + ?????????
"""
from modules.services import BaseService


class ApprovalRepository:
    """???????"""

    # ============================================================
    # ??
    # ============================================================

    @staticmethod
    def count_by_status(status_condition, db=None):
        """?????????????
        status_condition: '=' ?? pending, '!=' ?? history
        """
        db = db or BaseService.db()
        op = '=' if status_condition == 'pending' else '!='
        return db.execute(f'''
            SELECT COUNT(*) FROM approval_records ar
            LEFT JOIN work_records wr ON ar.work_record_id = wr.id
            LEFT JOIN orders o ON wr.order_id = o.id
            WHERE ar.status {op} 'pending' AND (o.deleted_at IS NULL OR o.id IS NULL)
        ''').fetchone()[0]

    @staticmethod
    def find_by_status(status_condition, limit, offset, db=None):
        """?????????????????/??/???????"""
        db = db or BaseService.db()
        op = '=' if status_condition == 'pending' else '!='
        return db.execute(f'''
            SELECT ar.*, o.order_no, wr.process_id, p.name as process_name,
                   u.name as worker_name, wr.quantity
            FROM approval_records ar
            LEFT JOIN work_records wr ON ar.work_record_id = wr.id
            LEFT JOIN orders o ON wr.order_id = o.id
            LEFT JOIN processes p ON wr.process_id = p.id
            LEFT JOIN users u ON wr.user_id = u.id
            WHERE ar.status {op} 'pending' AND (o.deleted_at IS NULL OR o.id IS NULL)
            ORDER BY ar.created_at DESC
            LIMIT ? OFFSET ?
        ''', (limit, offset)).fetchall()

    @staticmethod
    def find_by_id(record_id, db=None):
        """? ID ???????"""
        db = db or BaseService.db()
        return db.execute(
            'SELECT * FROM approval_records WHERE id = ?', (record_id,)
        ).fetchone()

    @staticmethod
    def find_work_record(wr_id, db=None):
        """查询报工记录（含process_id用于多级审批）"""
        db = db or BaseService.db()
        return db.execute(
            'SELECT id, quantity, order_id, status, process_id FROM work_records WHERE id = ?', (wr_id,)
        ).fetchone()

    @staticmethod
    def find_order(oid, db=None):
        """???????????????"""
        db = db or BaseService.db()
        return db.execute(
            'SELECT quantity, completed, deleted_at FROM orders WHERE id = ?', (oid,)
        ).fetchone()

    # ============================================================
    # ???
    # ============================================================

    @staticmethod
    def approve(record_id, approver_id, approver_name, comment, db=None):
        """??????????? + ???? + ??????"""
        db = db or BaseService.db()
        db.execute('''
            UPDATE approval_records
            SET status = 'approved', approver_id = ?, approver_name = ?,
                comment = ?, processed_at = datetime('now','localtime')
            WHERE id = ?
        ''', (approver_id, approver_name, comment, record_id))

    @staticmethod
    def reject(record_id, approver_id, approver_name, comment, db=None):
        """??????????? + ???????"""
        db = db or BaseService.db()
        db.execute('''
            UPDATE approval_records
            SET status = 'rejected', approver_id = ?, approver_name = ?,
                comment = ?, processed_at = datetime('now','localtime')
            WHERE id = ?
        ''', (approver_id, approver_name, comment, record_id))

    @staticmethod
    def update_work_record_status(wr_id, status, db=None):
        """?????????"""
        db = db or BaseService.db()
        db.execute(
            'UPDATE work_records SET status = ? WHERE id = ?', (status, wr_id)
        )

    @staticmethod
    def increment_order_completed(oid, quantity, db=None):
        """??????????"""
        db = db or BaseService.db()
        db.execute(
            'UPDATE orders SET completed = completed + ? WHERE id = ?', (quantity, oid)
        )

    @staticmethod
    def advance_level(record_id, approver_id, approver_name, comment, next_level, db=None):
        """Advance approval to next level without finalizing."""
        db = db or BaseService.db()
        db.execute("""
            UPDATE approval_records
            SET current_level = ?, approver_id = ?, approver_name = ?,
                comment = ?, processed_at = datetime('now','localtime')
            WHERE id = ?
        """, (next_level, approver_id, approver_name, comment, record_id))

    @staticmethod
    def find_approval_config(process_id, db=None):
        """Find approval config for a process."""
        db = db or BaseService.db()
        return db.execute(
            "SELECT * FROM approval_config WHERE process_id = ?", (process_id,)
        ).fetchone()
