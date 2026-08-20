"""qr-system — PositionRepository（岗位数据访问层）
All raw SQL lives here. Methods accept optional db for transaction sharing.
"""
from modules.repositories.context import resolve_db
from modules.master_data_references import POSITION_REFERENCES


class PositionRepository:
    """Position database operations — queries + writes, no business logic."""

    @staticmethod
    def count_positions(db=None):
        db = resolve_db(db)
        return db.execute('SELECT COUNT(*) FROM positions').fetchone()[0]

    @staticmethod
    def find_positions_paginated(limit, offset, db=None):
        db = resolve_db(db)
        return db.execute(
            'SELECT * FROM positions ORDER BY id LIMIT ? OFFSET ?',
            (limit, offset)
        ).fetchall()

    @staticmethod
    def find_position_processes(pos_ids, db=None):
        db = resolve_db(db)
        if not pos_ids:
            return []
        placeholders = ','.join('?' for _ in pos_ids)
        return db.execute(
            'SELECT pp.position_id, pp.process_id, p.name as process_name'
            ' FROM position_processes pp'
            ' JOIN processes p ON pp.process_id = p.id'
            ' WHERE pp.position_id IN (' + placeholders + ')'
            ' ORDER BY pp.position_id, pp.id',
            pos_ids
        ).fetchall()

    @staticmethod
    def find_position_by_name(name, db=None):
        db = resolve_db(db)
        return db.execute(
            'SELECT id FROM positions WHERE name = ?', (name,)
        ).fetchone()

    @staticmethod
    def find_position_by_name_excluding(name, exclude_id, db=None):
        db = resolve_db(db)
        return db.execute(
            'SELECT id FROM positions WHERE name = ? AND id != ?', (name, exclude_id)
        ).fetchone()

    @staticmethod
    def insert_position(name, description, status, db=None):
        db = resolve_db(db)
        return db.execute(
            'INSERT INTO positions (name, description, status) VALUES (?, ?, ?)',
            (name, description, status)
        )

    @staticmethod
    def insert_position_process(pos_id, process_id, db=None):
        db = resolve_db(db)
        db.execute(
            'INSERT OR IGNORE INTO position_processes (position_id, process_id) '
            'VALUES (?, ?)', (pos_id, process_id)
        )

    @staticmethod
    def find_position_by_id(pos_id, db=None):
        db = resolve_db(db)
        return db.execute(
            'SELECT * FROM positions WHERE id = ?', (pos_id,)
        ).fetchone()

    @staticmethod
    def update_position_fields(pos_id, set_clause, params, db=None):
        db = resolve_db(db)
        db.execute(
            'UPDATE positions SET ' + set_clause + ' WHERE id = ?',
            params + [pos_id]
        )

    @staticmethod
    def delete_position_processes_by_pos(pos_id, db=None):
        db = resolve_db(db)
        db.execute(
            'DELETE FROM position_processes WHERE position_id = ?', (pos_id,)
        )

    @staticmethod
    def find_valid_process_ids(process_ids, db=None, active_only=False):
        db = resolve_db(db)
        placeholders = ','.join('?' for _ in process_ids)
        status_clause = " AND status = 'active'" if active_only else ""
        rows = db.execute(
            'SELECT id FROM processes WHERE id IN (' + placeholders + ')' + status_clause,
            process_ids
        ).fetchall()
        return {r[0] for r in rows}

    @staticmethod
    def find_process_ids_by_position(pos_id, db=None):
        db = resolve_db(db)
        return {
            row["process_id"]
            for row in db.execute(
                "SELECT process_id FROM position_processes WHERE position_id = ?",
                (pos_id,),
            ).fetchall()
        }

    @staticmethod
    def count_users_by_position(pos_id, db=None):
        db = resolve_db(db)
        return db.execute(
            'SELECT COUNT(*) FROM users WHERE position_id = ?', (pos_id,)
        ).fetchone()[0]

    @staticmethod
    def delete_position_by_id(pos_id, db=None):
        db = resolve_db(db)
        db.execute('DELETE FROM positions WHERE id = ?', (pos_id,))

    @staticmethod
    def find_position_name_by_id(pos_id, db=None):
        db = resolve_db(db)
        row = db.execute(
            "SELECT id, name FROM positions WHERE id = ?", (pos_id,)
        ).fetchone()
        return row

    @staticmethod
    def find_active_positions_for_process_ids(process_ids, db=None):
        db = resolve_db(db)
        if process_ids is None:
            return db.execute(
                "SELECT * FROM positions WHERE status = 'active' ORDER BY id"
            ).fetchall()
        if not process_ids:
            return []
        placeholders = ",".join("?" for _ in process_ids)
        return db.execute(
            "SELECT DISTINCT p.* FROM positions p "
            "JOIN position_processes pp ON pp.position_id = p.id "
            f"WHERE p.status = 'active' AND pp.process_id IN ({placeholders}) "
            "ORDER BY p.id",
            list(process_ids),
        ).fetchall()

    @staticmethod
    def position_reference_counts(position_id, db=None):
        """Return de-duplicated row counts for every registered reference."""
        db = resolve_db(db)
        version_subquery = "SELECT id FROM position_versions WHERE position_id = ?"
        table_columns = {}
        counts = []
        for reference in POSITION_REFERENCES:
            exists = db.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",
                (reference.table,),
            ).fetchone()
            if not exists:
                continue
            available = table_columns.setdefault(
                reference.table,
                {
                    row[1]
                    for row in db.execute(
                        f'PRAGMA table_info("{reference.table}")'
                    ).fetchall()
                },
            )
            if not set(reference.required_columns).issubset(available):
                continue
            predicates = []
            params = []
            for column in reference.root_columns:
                if column in available:
                    predicates.append(f'"{column}" = ?')
                    params.append(position_id)
            for column in reference.version_columns:
                if column in available:
                    predicates.append(f'"{column}" IN ({version_subquery})')
                    params.append(position_id)
            if not predicates:
                continue
            where = "(" + " OR ".join(predicates) + ")"
            if reference.where_clause:
                where += " AND (" + reference.where_clause + ")"
            count = db.execute(
                f'SELECT COUNT(*) FROM "{reference.table}" WHERE {where}',
                params,
            ).fetchone()[0]
            counts.append((reference, int(count)))
        return counts

    @staticmethod
    def position_indirect_counts(position_id, db=None):
        """Count only open orders and current routes reached by this position."""
        db = resolve_db(db)
        process_scope = (
            "SELECT process_id FROM position_processes WHERE position_id = ?"
        )
        open_orders = db.execute(
            "SELECT COUNT(DISTINCT orders.id) FROM orders "
            "JOIN order_processes ON order_processes.order_id = orders.id "
            f"WHERE order_processes.process_id IN ({process_scope}) "
            "AND orders.deleted_at IS NULL "
            "AND orders.status NOT IN ('completed','cancelled')",
            (position_id,),
        ).fetchone()[0]
        current_routes = db.execute(
            "SELECT COUNT(DISTINCT route.id) FROM process_routes route "
            "WHERE COALESCE(route.status,'active')='active' "
            "AND COALESCE(route.lifecycle_status,'active')='active' AND ("
            "EXISTS (SELECT 1 FROM process_route_version_items item "
            "WHERE item.route_version_id=route.current_effective_version_id "
            f"AND item.process_id IN ({process_scope})) OR "
            "(route.current_effective_version_id IS NULL AND EXISTS ("
            "SELECT 1 FROM process_route_items legacy_item "
            "WHERE legacy_item.route_id=route.id "
            f"AND legacy_item.process_id IN ({process_scope}))))",
            (position_id, position_id),
        ).fetchone()[0]
        return {
            "open_orders": int(open_orders),
            "current_routes": int(current_routes),
        }
