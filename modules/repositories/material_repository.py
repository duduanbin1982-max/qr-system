"""Persistence operations for materials, inventory movements, consumption, and suppliers."""
from modules.repositories.context import resolve_db
from modules.process_fact_projection import (
    capture_process_fact_binding,
    process_value_sql,
    process_version_join,
    warn_legacy_fact_rows,
)


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
    def _list_filter(keyword='', material_type=''):
        clauses = []
        params = []
        keyword = (keyword or '').strip().lower()
        material_type = (material_type or '').strip()
        if keyword:
            pattern = f'%{keyword}%'
            clauses.append(
                "(LOWER(COALESCE(m.name, '')) LIKE ? OR "
                "LOWER(COALESCE(m.spec, '')) LIKE ? OR "
                "LOWER(COALESCE(m.material_type, '')) LIKE ? OR "
                "LOWER(COALESCE(m.location, '')) LIKE ? OR "
                "LOWER(COALESCE(s.name, '')) LIKE ?)"
            )
            params.extend([pattern] * 5)
        if material_type:
            clauses.append('m.material_type = ?')
            params.append(material_type)
        where_sql = f" WHERE {' AND '.join(clauses)}" if clauses else ''
        return where_sql, params

    @staticmethod
    def count_filtered(keyword='', material_type='', db=None):
        """Count materials matching the list filters."""
        db = resolve_db(db)
        where_sql, params = MaterialRepository._list_filter(keyword, material_type)
        return db.execute(
            'SELECT COUNT(*) FROM materials m '
            'LEFT JOIN suppliers s ON m.supplier_id = s.id' + where_sql,
            params,
        ).fetchone()[0]

    @staticmethod
    def inventory_summary(db=None):
        """Return global inventory metrics independent of list pagination."""
        db = resolve_db(db)
        row = db.execute('''
            SELECT COUNT(*) AS total,
                   COALESCE(SUM(
                       CASE WHEN COALESCE(quantity, 0) <= COALESCE(safe_stock, 0)
                            THEN 1 ELSE 0 END
                   ), 0) AS low_stock,
                   COALESCE(SUM(
                       COALESCE(quantity, 0) * COALESCE(unit_price, 0)
                   ), 0) AS inventory_value
            FROM materials
        ''').fetchone()
        return dict(row) if row else {
            'total': 0,
            'low_stock': 0,
            'inventory_value': 0,
        }

    @staticmethod
    def list_material_types(db=None):
        """Return all non-empty material types for the list filter."""
        db = resolve_db(db)
        return [
            row['material_type']
            for row in db.execute('''
                SELECT DISTINCT TRIM(material_type) AS material_type
                FROM materials
                WHERE TRIM(COALESCE(material_type, '')) != ''
                ORDER BY material_type
            ''').fetchall()
        ]

    @staticmethod
    def find_inventory_values(db=None):
        """Return the lightweight value ordering used by global ABC ranking."""
        db = resolve_db(db)
        return db.execute('''
            SELECT id,
                   COALESCE(quantity, 0) * COALESCE(unit_price, 0) AS inventory_value
            FROM materials
            ORDER BY inventory_value DESC, id DESC
        ''').fetchall()

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
    def find_all_with_supplier_paginated(
        limit,
        offset,
        keyword='',
        material_type='',
        db=None,
    ):
        """Return filtered, paginated materials with supplier names."""
        db = resolve_db(db)
        where_sql, params = MaterialRepository._list_filter(keyword, material_type)
        return db.execute('''
            SELECT m.*, s.name as supplier_name
            FROM materials m LEFT JOIN suppliers s ON m.supplier_id = s.id
        ''' + where_sql + '''
            ORDER BY m.id DESC LIMIT ? OFFSET ?
        ''', params + [limit, offset]).fetchall()

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
        process_name = process_value_sql("mc", "process_version", "p")
        rows = db.execute('''
            SELECT mc.*,o.order_no,o.product_name,'''
            + process_name + ''' as process_name,
                   u.name as operator_name_from_fk
            FROM material_consumptions mc
            LEFT JOIN orders o ON mc.order_id = o.id
            LEFT JOIN processes p ON mc.process_id = p.id
            ''' + process_version_join("mc", "process_version") + '''
            LEFT JOIN users u ON mc.operator_id = u.id
            WHERE mc.material_id = ?
            ORDER BY mc.created_at DESC LIMIT ?
        ''', (mid, limit)).fetchall()
        warn_legacy_fact_rows("material_consumptions", rows)
        return rows

    @staticmethod
    def find_consumptions_by_material_paginated(mid, limit, offset, db=None):
        """Return paginated material consumptions with joined business details."""
        db = resolve_db(db)
        process_name = process_value_sql("mc", "process_version", "p")
        rows = db.execute('''
            SELECT mc.*,o.order_no,o.product_name,'''
            + process_name + ''' as process_name,
                   u.name as operator_name_from_fk
            FROM material_consumptions mc
            LEFT JOIN orders o ON mc.order_id = o.id
            LEFT JOIN processes p ON mc.process_id = p.id
            ''' + process_version_join("mc", "process_version") + '''
            LEFT JOIN users u ON mc.operator_id = u.id
            WHERE mc.material_id = ?
            ORDER BY mc.created_at DESC LIMIT ? OFFSET ?
        ''', (mid, limit, offset)).fetchall()
        warn_legacy_fact_rows("material_consumptions", rows)
        return rows

    @staticmethod
    def find_consumption_by_id(cid, db=None):
        """Find one material consumption record by ID."""
        db = resolve_db(db)
        return db.execute(
            'SELECT * FROM material_consumptions WHERE id = ?', (cid,)
        ).fetchone()

    @staticmethod
    def find_consumptions_by_work_record(work_record_id, db=None):
        """Return automatic deductions already linked to a work report."""
        db = resolve_db(db)
        return db.execute(
            'SELECT id, material_id FROM material_consumptions '
            'WHERE source_work_record_id = ? ORDER BY id',
            (work_record_id,),
        ).fetchall()

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
        return sum(MaterialRepository.reference_counts(mid, db=db).values())

    @staticmethod
    def reference_counts(mid, db=None):
        """Return material references grouped by business source."""
        db = resolve_db(db)
        row = db.execute(
            'SELECT '
            '(SELECT COUNT(*) FROM material_consumptions WHERE material_id = ?) AS consumptions, '
            '(SELECT COUNT(*) FROM product_bom WHERE material_id = ?) AS product_bom, '
            '(SELECT COUNT(*) FROM order_materials WHERE material_id = ?) AS order_materials, '
            '(SELECT COUNT(*) FROM quality_inspection_tasks WHERE material_id = ?) AS inspection_tasks, '
            '(SELECT COUNT(*) FROM quality_nonconformances WHERE material_id = ?) AS nonconformances, '
            '(SELECT COUNT(*) FROM quality_supplier_inspections WHERE material_id = ?) AS supplier_inspections',
            (mid, mid, mid, mid, mid, mid),
        ).fetchone()
        return dict(row) if row else {}

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
                           user_id, operator_name, notes,
                           source_work_record_id=None, db=None):
        """Insert a material consumption record."""
        db = resolve_db(db)
        columns = {
            row[1] for row in db.execute("PRAGMA table_info(material_consumptions)")
        }
        if "process_version_id" not in columns:
            cursor = db.execute(
                "INSERT INTO material_consumptions "
                "(material_id,order_id,process_id,quantity,operator_id,operator_name,"
                "notes,source_work_record_id) VALUES (?,?,?,?,?,?,?,?)",
                (
                    material_id,
                    order_id or None,
                    process_id or None,
                    quantity,
                    user_id,
                    operator_name,
                    notes,
                    source_work_record_id,
                ),
            )
            return cursor.lastrowid
        binding = capture_process_fact_binding(
            db,
            order_id=order_id or None,
            process_id=process_id or None,
            source_work_record_id=source_work_record_id,
        )
        cursor = db.execute(
            'INSERT INTO material_consumptions '
            '(material_id, order_id, process_id, quantity, '
            'operator_id,operator_name,notes,source_work_record_id,'
            'process_version_id,process_code_snapshot,process_name_snapshot,'
            'process_category_snapshot,route_id,route_version_id,route_name_snapshot,'
            'version_binding_source) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)',
            (material_id, order_id or None, process_id or None, quantity,
             user_id, operator_name, notes, source_work_record_id,
             binding["process_version_id"], binding["process_code_snapshot"],
             binding["process_name_snapshot"], binding["process_category_snapshot"],
             binding["route_id"], binding["route_version_id"],
             binding["route_name_snapshot"], binding["version_binding_source"])
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
    def count_filtered(keyword='', db=None):
        """Count suppliers matching name or contact details."""
        db = resolve_db(db)
        keyword = (keyword or '').strip().lower()
        if not keyword:
            return SupplierRepository.count_all(db=db)
        pattern = f'%{keyword}%'
        return db.execute('''
            SELECT COUNT(*) FROM suppliers
            WHERE LOWER(COALESCE(name, '')) LIKE ?
               OR LOWER(COALESCE(contact, '')) LIKE ?
               OR LOWER(COALESCE(phone, '')) LIKE ?
        ''', (pattern, pattern, pattern)).fetchone()[0]

    @staticmethod
    def find_all(db=None):
        """Return all suppliers ordered by name."""
        db = resolve_db(db)
        return db.execute('SELECT * FROM suppliers ORDER BY name').fetchall()

    @staticmethod
    def find_all_paginated(limit, offset, keyword='', db=None):
        """Return filtered, paginated suppliers ordered by name."""
        db = resolve_db(db)
        keyword = (keyword or '').strip().lower()
        if keyword:
            pattern = f'%{keyword}%'
            return db.execute('''
                SELECT * FROM suppliers
                WHERE LOWER(COALESCE(name, '')) LIKE ?
                   OR LOWER(COALESCE(contact, '')) LIKE ?
                   OR LOWER(COALESCE(phone, '')) LIKE ?
                ORDER BY name LIMIT ? OFFSET ?
            ''', (pattern, pattern, pattern, limit, offset)).fetchall()
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
        return sum(SupplierRepository.reference_counts(sid, db=db).values())

    @staticmethod
    def reference_counts(sid, db=None):
        """Return supplier references grouped by business source."""
        db = resolve_db(db)
        row = db.execute(
            'SELECT '
            '(SELECT COUNT(*) FROM materials WHERE supplier_id = ?) AS materials, '
            '(SELECT COUNT(*) FROM quality_inspection_tasks WHERE supplier_id = ?) AS inspection_tasks, '
            '(SELECT COUNT(*) FROM quality_nonconformances WHERE supplier_id = ?) AS nonconformances, '
            '(SELECT COUNT(*) FROM quality_supplier_inspections WHERE supplier_id = ?) AS supplier_inspections',
            (sid, sid, sid, sid),
        ).fetchone()
        return dict(row) if row else {}

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
