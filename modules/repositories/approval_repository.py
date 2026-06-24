"""
qr-system ? ApprovalRepository???????

???????? ? approval_records ?? + ?????????
"""
from modules.db_unit_of_work import BaseService


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
        """查询报工记录[含process_id用于多级审批]"""
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

    # ============================================================
    # 审批配置
    # ============================================================

    @staticmethod
    def find_all_configs(db=None):
        """返回所有工序的审批配置[含工序名称]"""
        db = db or BaseService.db()
        return db.execute("""
            SELECT ac.id, ac.process_id, COALESCE(ac.require_approval, 0) as require_approval,
                   COALESCE(ac.approver_role, 'admin') as approver_role,
                   COALESCE(ac.approval_level, 1) as approval_level,
                   COALESCE(ac.approver_role_2, '') as approver_role_2,
                   COALESCE(ac.approver_role_3, '') as approver_role_3,
                   p.name as process_name, p.category
            FROM processes p
            LEFT JOIN approval_config ac ON ac.process_id = p.id
            ORDER BY p.name
        """).fetchall()

    @staticmethod
    def upsert_config(process_id, require_approval, approver_role, approver_role_2, approver_role_3, approval_level, db=None):
        """插入或更新审批配置;require_approval=0 时删除"""
        db = db or BaseService.db()
        existing = db.execute(
            "SELECT id FROM approval_config WHERE process_id = ?", (process_id,)
        ).fetchone()
        if require_approval:
            if existing:
                db.execute(
                    "UPDATE approval_config SET require_approval=?, approver_role=?, approver_role_2=?, approver_role_3=?, approval_level=? WHERE process_id=?",
                    (require_approval, approver_role, approver_role_2, approver_role_3, approval_level, process_id)
                )
            else:
                db.execute(
                    "INSERT INTO approval_config (process_id, require_approval, approver_role, approver_role_2, approver_role_3, approval_level) VALUES (?,?,?,?,?,?)",
                    (process_id, require_approval, approver_role, approver_role_2, approver_role_3, approval_level)
                )
        else:
            # 关闭审批时直接删除,不做冗余 UPDATE
            if existing:
                db.execute("DELETE FROM approval_config WHERE process_id = ?", (process_id,))

    @staticmethod
    def get_approval_stats(db=None):
        """审批统计数据"""
        db = db or BaseService.db()
        pending = db.execute("SELECT COUNT(*) FROM approval_records WHERE status='pending'").fetchone()[0]
        avg_row = db.execute("""
            SELECT ROUND(AVG(
                (julianday(processed_at) - julianday(created_at)) * 24
            ), 1) as avg_hours
            FROM approval_records
            WHERE status != 'pending' AND processed_at IS NOT NULL
        """).fetchone()
        pending_over = db.execute("""
            SELECT COUNT(*) FROM approval_records
            WHERE status='pending' AND created_at < datetime('now','localtime','-24 hours')
        """).fetchone()[0]
        total = db.execute("SELECT COUNT(*) FROM approval_records").fetchone()[0]
        return {
            "pending": pending,
            "avg_hours": avg_row["avg_hours"] if avg_row and avg_row["avg_hours"] else 0,
            "pending_over_24h": pending_over,
            "total": total
        }

    @staticmethod
    def find_approval_config(process_id, db=None):
        """查单个工序的审批配置"""
        db = db or BaseService.db()
        return db.execute(
            "SELECT * FROM approval_config WHERE process_id = ?", (process_id,)
        ).fetchone()
