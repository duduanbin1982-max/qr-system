"""Persistence operations for materials, inventory movements, consumption, and suppliers."""
from modules.repositories.context import resolve_db


class MaterialRepository:
    """Material persistence gateway."""

    # ============================================================
    # Queries
    # ============================================================

    @staticmethod
    def count_all(db=None):
        """Count all material records."""
        db = resolve_db(db)
        return db.execute('SELECT COUNT(*) FROM materials').fetchone()[0]

    @staticmethod
    def find_all_with_supplier(db=None):
        """Return all materials with supplier names."""
        db = resolve_db(db)
        return db.execute('''
            SELECT m.*, s.name as supplier_name
            FROM materials m LEFT JOIN suppliers s ON m.supplier_id = s.id
            ORDER BY m.id DESC
        ''').fetchall()

    @staticmethod
    def find_all_with_supplier_paginated(limit, offset, db=None):
        """Return paginated materials with supplier names."""
        db = resolve_db(db)
        return db.execute('''
            SELECT m.*, s.name as supplier_name
            FROM materials m LEFT JOIN suppliers s ON m.supplier_id = s.id
            ORDER BY m.id DESC LIMIT ? OFFSET ?
        ''', (limit, offset)).fetchall()

    @staticmethod
    def check_duplicate(name, spec, material_type, exclude_id=None, db=None):
        """Check duplicate by name + spec + material_type combination.
        Returns the duplicate row or None."""
        db = resolve_db(db)
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
        """Find one material by ID."""
        db = resolve_db(db)
        return db.execute(
            'SELECT * FROM materials WHERE id = ?', (mid,)
        ).fetchone()

    @staticmethod
    def find_quantity_by_id(mid, db=None):
        """Find material identity and current quantity."""
        db = resolve_db(db)
        return db.execute(
            'SELECT id, quantity FROM materials WHERE id = ?', (mid,)
        ).fetchone()

    @staticmethod
    def count_logs_by_material(mid, db=None):
        """Count inventory logs for a material."""
        db = resolve_db(db)
        return db.execute(
            'SELECT COUNT(*) FROM material_logs WHERE material_id = ?', (mid,)
        ).fetchone()[0]

    @staticmethod
    def find_logs_by_material(mid, limit=100, db=None):
        """Return recent inventory logs for a material."""
        db = resolve_db(db)
        return db.execute(
            'SELECT ml.*, u.name as operator_name_from_fk FROM material_logs ml'
            ' LEFT JOIN users u ON ml.operator_id = u.id WHERE ml.material_id = ? '
            'ORDER BY ml.created_at DESC LIMIT ?', (mid, limit)
        ).fetchall()

    @staticmethod
    def find_logs_by_material_paginated(mid, limit, offset, db=None):
        """Return paginated inventory logs for a material."""
        db = resolve_db(db)
        return db.execute(
            'SELECT ml.*, u.name as operator_name_from_fk FROM material_logs ml'
            ' LEFT JOIN users u ON ml.operator_id = u.id WHERE ml.material_id = ? '
            'ORDER BY ml.created_at DESC LIMIT ? OFFSET ?', (mid, limit, offset)
        ).fetchall()

    @staticmethod
    def count_consumptions_by_material(mid, db=None):
        """Count consumption records for a material."""
        db = resolve_db(db)
        return db.execute(
            'SELECT COUNT(*) FROM material_consumptions WHERE material_id = ?', (mid,)
        ).fetchone()[0]

    @staticmethod
    def find_consumptions_by_material(mid, limit=100, db=None):
        """Return material consumptions with order, process, and operator details."""
        db = resolve_db(db)
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
        """Return paginated material consumptions with joined business details."""
        db = resolve_db(db)
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
        """Find one material consumption record by ID."""
        db = resolve_db(db)
        return db.execute(
            'SELECT * FROM material_consumptions WHERE id = ?', (cid,)
        ).fetchone()

    @staticmethod
    def find_log_for_source(source_type, source_id, db=None):
        """Find the latest ledger entry for a business source."""
        db = resolve_db(db)
        return db.execute(
            'SELECT * FROM material_logs WHERE source_type = ? AND source_id = ? '
            'ORDER BY id DESC LIMIT 1',
            (source_type, source_id),
        ).fetchone()

    @staticmethod
    def count_refs(mid, db=None):
        """Count business records that prevent material deletion."""
        db = resolve_db(db)
        row = db.execute(
            'SELECT COUNT(*) as cnt FROM material_consumptions WHERE material_id = ?', (mid,)
        ).fetchone()
        return row['cnt'] if row else 0

    # ============================================================
    # Mutations
    # ============================================================

    @staticmethod
    def insert(data_tuple, db=None):
        """Insert material, returns lastrowid."""
        db = resolve_db(db)
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
        """Update a material using validated SET clauses and parameters."""
        db = resolve_db(db)
        update_params = list(params) + [mid]
        db.execute(f'UPDATE materials SET {", ".join(set_clauses)} WHERE id = ?', update_params)

    @staticmethod
    def delete(mid, db=None):
        """Delete a material."""
        db = resolve_db(db)
        db.execute('DELETE FROM materials WHERE id = ?', (mid,))

    @staticmethod
    def delete_logs_by_material(mid, db=None):
        """Delete inventory logs for a material."""
        db = resolve_db(db)
        db.execute('DELETE FROM material_logs WHERE material_id = ?', (mid,))

    @staticmethod
    def update_quantity(mid, new_qty, db=None):
        """Set material quantity and refresh its update timestamp."""
        db = resolve_db(db)
        db.execute(
            "UPDATE materials SET quantity = ?, "
            "updated_at = datetime('now','localtime') WHERE id = ?",
            (new_qty, mid)
        )

    @staticmethod
    def increment_quantity(mid, amount, db=None):
        """Increment material quantity and refresh its update timestamp."""
        db = resolve_db(db)
        db.execute(
            "UPDATE materials SET quantity = quantity + ?, "
            "updated_at = datetime('now','localtime') WHERE id = ?",
            (amount, mid)
        )

    @staticmethod
    def apply_quantity_delta(mid, delta, db=None):
        """Apply a stock delta and return the balance transition."""
        db = resolve_db(db)
        row = db.execute(
            'SELECT id, COALESCE(quantity, 0) AS quantity FROM materials WHERE id = ?',
            (mid,),
        ).fetchone()
        if not row:
            return None
        balance_before = float(row['quantity'] or 0)
        balance_after = balance_before + float(delta)
        if balance_after < 0:
            return {
                'material_id': mid,
                'balance_before': balance_before,
                'balance_after': balance_before,
                'insufficient': True,
            }
        db.execute(
            "UPDATE materials SET quantity = ?, "
            "updated_at = datetime('now','localtime') WHERE id = ?",
            (balance_after, mid),
        )
        return {
            'material_id': mid,
            'balance_before': balance_before,
            'balance_after': balance_after,
            'insufficient': False,
        }

    @staticmethod
    def insert_log(
        material_id,
        log_type,
        quantity,
        remark,
        operator_name,
        *,
        operator_id=None,
        balance_before=None,
        balance_after=None,
        source_type='manual_stock',
        source_id=None,
        reversal_of_log_id=None,
        db=None,
    ):
        """Insert a material inventory movement."""
        db = resolve_db(db)
        cursor = db.execute(
            'INSERT INTO material_logs '
            '(material_id, type, quantity, remark, operator_id, operator_name, '
            'balance_before, balance_after, source_type, source_id, reversal_of_log_id) '
            'VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)',
            (
                material_id,
                log_type,
                quantity,
                remark,
                operator_id,
                operator_name,
                balance_before,
                balance_after,
                source_type,
                source_id,
                reversal_of_log_id,
            ),
        )
        return cursor.lastrowid

    @staticmethod
    def insert_consumption(material_id, order_id, process_id, quantity,
                           user_id, operator_name, notes, db=None):
        """Insert a material consumption record."""
        db = resolve_db(db)
        cursor = db.execute(
            'INSERT INTO material_consumptions '
            '(material_id, order_id, process_id, quantity, '
            'operator_id, operator_name, notes) '
            'VALUES (?,?,?,?,?,?,?)',
            (material_id, order_id or None, process_id or None, quantity,
             user_id, operator_name, notes)
        )
        return cursor.lastrowid

    @staticmethod
    def delete_consumption_by_id(cid, db=None):
        """Delete a material consumption record."""
        db = resolve_db(db)
        db.execute('DELETE FROM material_consumptions WHERE id = ?', (cid,))

    @staticmethod
    def mark_consumption_reversed(
        cid,
        reversed_by,
        reversal_reason,
        reversal_log_id,
        db=None,
    ):
        """Mark a consumption as reversed while preserving its audit history."""
        db = resolve_db(db)
        cursor = db.execute(
            "UPDATE material_consumptions SET status = 'reversed', "
            "reversed_at = datetime('now','localtime'), reversed_by = ?, "
            "reversal_reason = ?, reversal_log_id = ? "
            "WHERE id = ? AND COALESCE(status, 'active') = 'active'",
            (reversed_by, reversal_reason, reversal_log_id, cid),
        )
        return cursor.rowcount


class SupplierRepository:
    """Supplier persistence gateway."""

    @staticmethod
    def count_all(db=None):
        """Count all suppliers."""
        db = resolve_db(db)
        return db.execute('SELECT COUNT(*) FROM suppliers').fetchone()[0]

    @staticmethod
    def find_all(db=None):
        """Return all suppliers ordered by name."""
        db = resolve_db(db)
        return db.execute('SELECT * FROM suppliers ORDER BY name').fetchall()

    @staticmethod
    def find_all_paginated(limit, offset, db=None):
        """Return paginated suppliers ordered by name."""
        db = resolve_db(db)
        return db.execute(
            'SELECT * FROM suppliers ORDER BY name LIMIT ? OFFSET ?', (limit, offset)
        ).fetchall()

    @staticmethod
    def find_by_id(sid, db=None):
        """Find one supplier by ID and include its name."""
        db = resolve_db(db)
        return db.execute(
            'SELECT id, name FROM suppliers WHERE id = ?', (sid,)
        ).fetchone()

    @staticmethod
    def count_refs(sid, db=None):
        """Count materials that reference a supplier."""
        db = resolve_db(db)
        row = db.execute(
            'SELECT COUNT(*) as cnt FROM materials WHERE supplier_id = ?', (sid,)
        ).fetchone()
        return row['cnt'] if row else 0

    @staticmethod
    def insert(data_tuple, db=None):
        """Insert a supplier and return its ID."""
        db = resolve_db(db)
        cur = db.execute(
            'INSERT INTO suppliers (name, contact, phone, address, remark) '
            'VALUES (?,?,?,?,?)',
            data_tuple
        )
        return cur.lastrowid

    @staticmethod
    def update(sid, data_tuple, db=None):
        """Update a supplier."""
        db = resolve_db(db)
        db.execute(
            'UPDATE suppliers SET name=?, contact=?, phone=?, '
            'address=?, remark=? WHERE id=?',
            data_tuple + (sid,)
        )

    @staticmethod
    def delete(sid, db=None):
        """Delete a supplier."""
        db = resolve_db(db)
        db.execute('DELETE FROM suppliers WHERE id = ?', (sid,))
