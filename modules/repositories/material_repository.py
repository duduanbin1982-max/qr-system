"""
qr-system ? MaterialRepository???????

Brooks R6 fix: ??? materials / material_logs / material_consumptions / suppliers ? SQL ???????
Service ?????????????? SQL?
"""
from modules.services import BaseService


class MaterialRepository:
    """?????? ? ?? materials / material_logs / material_consumptions CRUD ?????"""

    # ============================================================
    # ??
    # ============================================================

    @staticmethod
    def count_all(db=None):
        """?????"""
        db = db or BaseService.db()
        return db.execute('SELECT COUNT(*) FROM materials').fetchone()[0]

    @staticmethod
    def find_all_with_supplier(db=None):
        """?????????????????"""
        db = db or BaseService.db()
        return db.execute('''
            SELECT m.*, s.name as supplier_name
            FROM materials m LEFT JOIN suppliers s ON m.supplier_id = s.id
            ORDER BY m.id DESC
        ''').fetchall()

    @staticmethod
    def find_all_with_supplier_paginated(limit, offset, db=None):
        """????????????????"""
        db = db or BaseService.db()
        return db.execute('''
            SELECT m.*, s.name as supplier_name
            FROM materials m LEFT JOIN suppliers s ON m.supplier_id = s.id
            ORDER BY m.id DESC LIMIT ? OFFSET ?
        ''', (limit, offset)).fetchall()

    @staticmethod
    def check_duplicate(name, spec, material_type, exclude_id=None, db=None):
        """Check duplicate by name + spec + material_type combination.
        Returns the duplicate row or None."""
        db = db or BaseService.db()
        spec_val = (spec or '').strip()
        mt_val = (material_type or '').strip()
        if exclude_id:
            return db.execute(
                'SELECT id FROM materials WHERE name = ? AND spec = ? AND material_type = ? AND id != ?',
                (name, spec_val, mt_val, exclude_id)
            ).fetchone()
        return db.execute(
            'SELECT id FROM materials WHERE name = ? AND spec = ? AND material_type = ?',
            (name, spec_val, mt_val)
        ).fetchone()

    @staticmethod
    def find_by_id(mid, db=None):
        """? ID ?????"""
        db = db or BaseService.db()
        return db.execute(
            'SELECT * FROM materials WHERE id = ?', (mid,)
        ).fetchone()

    @staticmethod
    def find_quantity_by_id(mid, db=None):
        """????????id + quantity??"""
        db = db or BaseService.db()
        return db.execute(
            'SELECT id, quantity FROM materials WHERE id = ?', (mid,)
        ).fetchone()

    @staticmethod
    def count_logs_by_material(mid, db=None):
        """???????????"""
        db = db or BaseService.db()
        return db.execute(
            'SELECT COUNT(*) FROM material_logs WHERE material_id = ?', (mid,)
        ).fetchone()[0]

    @staticmethod
    def find_logs_by_material(mid, limit=100, db=None):
        """??????????"""
        db = db or BaseService.db()
        return db.execute(
            'SELECT ml.*, u.name as operator_name_from_fk FROM material_logs ml'
            ' LEFT JOIN users u ON ml.operator_id = u.id WHERE ml.material_id = ? '
            'ORDER BY ml.created_at DESC LIMIT ?', (mid, limit)
        ).fetchall()

    @staticmethod
    def find_logs_by_material_paginated(mid, limit, offset, db=None):
        """??????????????"""
        db = db or BaseService.db()
        return db.execute(
            'SELECT ml.*, u.name as operator_name_from_fk FROM material_logs ml'
            ' LEFT JOIN users u ON ml.operator_id = u.id WHERE ml.material_id = ? '
            'ORDER BY ml.created_at DESC LIMIT ? OFFSET ?', (mid, limit, offset)
        ).fetchall()

    @staticmethod
    def count_consumptions_by_material(mid, db=None):
        """?????????"""
        db = db or BaseService.db()
        return db.execute(
            'SELECT COUNT(*) FROM material_consumptions WHERE material_id = ?', (mid,)
        ).fetchone()[0]

    @staticmethod
    def find_consumptions_by_material(mid, limit=100, db=None):
        """??????????/??/???????"""
        db = db or BaseService.db()
        return db.execute('''
            SELECT mc.*, o.order_no, o.product_name, p.name as process_name,
                   u.name as operator_name_from_fk
            FROM material_consumptions mc
            LEFT JOIN orders o ON mc.order_id = o.id
            LEFT JOIN processes p ON mc.process_id = p.id
            LEFT JOIN users u ON mc.operator_id = u.id
            WHERE mc.material_id = ?
            ORDER BY mc.created_at DESC LIMIT ?
        ''', (mid, limit)).fetchall()

    @staticmethod
    def find_consumptions_by_material_paginated(mid, limit, offset, db=None):
        """??????????/??/??????????"""
        db = db or BaseService.db()
        return db.execute('''
            SELECT mc.*, o.order_no, o.product_name, p.name as process_name,
                   u.name as operator_name_from_fk
            FROM material_consumptions mc
            LEFT JOIN orders o ON mc.order_id = o.id
            LEFT JOIN processes p ON mc.process_id = p.id
            LEFT JOIN users u ON mc.operator_id = u.id
            WHERE mc.material_id = ?
            ORDER BY mc.created_at DESC LIMIT ? OFFSET ?
        ''', (mid, limit, offset)).fetchall()

    @staticmethod
    def find_consumption_by_id(cid, db=None):
        """? ID ???????"""
        db = db or BaseService.db()
        return db.execute(
            'SELECT * FROM material_consumptions WHERE id = ?', (cid,)
        ).fetchone()

    @staticmethod
    def count_refs(mid, db=None):
        """????????????????????"""
        db = db or BaseService.db()
        row = db.execute(
            'SELECT COUNT(*) as cnt FROM material_consumptions WHERE material_id = ?', (mid,)
        ).fetchone()
        return row['cnt'] if row else 0

    # ============================================================
    # ???
    # ============================================================

    @staticmethod
    def insert(data_tuple, db=None):
        """Insert material, returns lastrowid."""
        db = db or BaseService.db()
        cur = db.execute(
            'INSERT INTO materials '
            '(name, spec, unit, quantity, unit_price, safe_stock, '
            'location, supplier_id, remark, material_type) '
            'VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)',
            data_tuple
        )
        return cur.lastrowid

    @staticmethod
    def update(mid, set_clauses, params, db=None):
        """???? SET ... WHERE id = ????????? set_clauses ? params?"""
        db = db or BaseService.db()
        params.append(mid)
        db.execute(f'UPDATE materials SET {", ".join(set_clauses)} WHERE id = ?', params)

    @staticmethod
    def delete(mid, db=None):
        """?????"""
        db = db or BaseService.db()
        db.execute('DELETE FROM materials WHERE id = ?', (mid,))

    @staticmethod
    def delete_logs_by_material(mid, db=None):
        """?????????"""
        db = db or BaseService.db()
        db.execute('DELETE FROM material_logs WHERE material_id = ?', (mid,))

    @staticmethod
    def update_quantity(mid, new_qty, db=None):
        """????????? updated_at??"""
        db = db or BaseService.db()
        db.execute(
            "UPDATE materials SET quantity = ?, "
            "updated_at = datetime('now','localtime') WHERE id = ?",
            (new_qty, mid)
        )

    @staticmethod
    def increment_quantity(mid, amount, db=None):
        """????????? updated_at??"""
        db = db or BaseService.db()
        db.execute(
            "UPDATE materials SET quantity = quantity + ?, "
            "updated_at = datetime('now','localtime') WHERE id = ?",
            (amount, mid)
        )

    @staticmethod
    def insert_log(material_id, log_type, quantity, remark, operator_name, db=None):
        """?????????"""
        db = db or BaseService.db()
        db.execute(
            'INSERT INTO material_logs '
            '(material_id, type, quantity, remark, operator_name) '
            'VALUES (?, ?, ?, ?, ?)',
            (material_id, log_type, quantity, remark, operator_name)
        )

    @staticmethod
    def insert_consumption(material_id, order_id, process_id, quantity,
                           user_id, operator_name, notes, db=None):
        """?????????"""
        db = db or BaseService.db()
        db.execute(
            'INSERT INTO material_consumptions '
            '(material_id, order_id, process_id, quantity, '
            'operator_id, operator_name, notes) '
            'VALUES (?,?,?,?,?,?,?)',
            (material_id, order_id or None, process_id or None, quantity,
             user_id, operator_name, notes)
        )

    @staticmethod
    def delete_consumption_by_id(cid, db=None):
        """???????"""
        db = db or BaseService.db()
        db.execute('DELETE FROM material_consumptions WHERE id = ?', (cid,))


class SupplierRepository:
    """??????? ? ?? suppliers ? CRUD ?????"""

    @staticmethod
    def count_all(db=None):
        """??????"""
        db = db or BaseService.db()
        return db.execute('SELECT COUNT(*) FROM suppliers').fetchone()[0]

    @staticmethod
    def find_all(db=None):
        """?????????????"""
        db = db or BaseService.db()
        return db.execute('SELECT * FROM suppliers ORDER BY name').fetchall()

    @staticmethod
    def find_all_paginated(limit, offset, db=None):
        """????????????????"""
        db = db or BaseService.db()
        return db.execute(
            'SELECT * FROM suppliers ORDER BY name LIMIT ? OFFSET ?', (limit, offset)
        ).fetchall()

    @staticmethod
    def find_by_id(sid, db=None):
        """? ID ??????? name ????????"""
        db = db or BaseService.db()
        return db.execute(
            'SELECT id, name FROM suppliers WHERE id = ?', (sid,)
        ).fetchone()

    @staticmethod
    def count_refs(sid, db=None):
        """????????????"""
        db = db or BaseService.db()
        row = db.execute(
            'SELECT COUNT(*) as cnt FROM materials WHERE supplier_id = ?', (sid,)
        ).fetchone()
        return row['cnt'] if row else 0

    @staticmethod
    def insert(data_tuple, db=None):
        """???????? lastrowid?"""
        db = db or BaseService.db()
        cur = db.execute(
            'INSERT INTO suppliers (name, contact, phone, address, remark) '
            'VALUES (?,?,?,?,?)',
            data_tuple
        )
        return cur.lastrowid

    @staticmethod
    def update(sid, data_tuple, db=None):
        """??????"""
        db = db or BaseService.db()
        db.execute(
            'UPDATE suppliers SET name=?, contact=?, phone=?, '
            'address=?, remark=? WHERE id=?',
            data_tuple + (sid,)
        )

    @staticmethod
    def delete(sid, db=None):
        """??????"""
        db = db or BaseService.db()
        db.execute('DELETE FROM suppliers WHERE id = ?', (sid,))
