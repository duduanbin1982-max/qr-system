"""qr-system — PositionRepository（岗位数据访问层）
All raw SQL lives here. Methods accept optional db for transaction sharing.
"""
from modules.services import BaseService


class PositionRepository:
    """Position database operations — queries + writes, no business logic."""

    @staticmethod
    def count_positions(db=None):
        db = db or BaseService.db()
        return db.execute('SELECT COUNT(*) FROM positions').fetchone()[0]

    @staticmethod
    def find_positions_paginated(limit, offset, db=None):
        db = db or BaseService.db()
        return db.execute(
            'SELECT * FROM positions ORDER BY id LIMIT ? OFFSET ?',
            (limit, offset)
        ).fetchall()

    @staticmethod
    def find_position_processes(pos_ids, db=None):
        db = db or BaseService.db()
        if not pos_ids:
            return []
        placeholders = ','.join('?' for _ in pos_ids)
        return db.execute(
            'SELECT pp.position_id, pp.process_id, p.name as process_name'
            ' FROM position_processes pp'
            ' JOIN processes p ON pp.process_id = p.id'
            ' WHERE pp.position_id IN (' + placeholders + ')',
            pos_ids
        ).fetchall()

    @staticmethod
    def find_position_by_name(name, db=None):
        db = db or BaseService.db()
        return db.execute(
            'SELECT id FROM positions WHERE name = ?', (name,)
        ).fetchone()

    @staticmethod
    def find_position_by_name_excluding(name, exclude_id, db=None):
        db = db or BaseService.db()
        return db.execute(
            'SELECT id FROM positions WHERE name = ? AND id != ?', (name, exclude_id)
        ).fetchone()

    @staticmethod
    def insert_position(name, description, status, db=None):
        db = db or BaseService.db()
        return db.execute(
            'INSERT INTO positions (name, description, status) VALUES (?, ?, ?)',
            (name, description, status)
        )

    @staticmethod
    def insert_position_process(pos_id, process_id, db=None):
        db = db or BaseService.db()
        db.execute(
            'INSERT OR IGNORE INTO position_processes (position_id, process_id) '
            'VALUES (?, ?)', (pos_id, process_id)
        )

    @staticmethod
    def find_position_by_id(pos_id, db=None):
        db = db or BaseService.db()
        return db.execute(
            'SELECT * FROM positions WHERE id = ?', (pos_id,)
        ).fetchone()

    @staticmethod
    def update_position_fields(pos_id, set_clause, params, db=None):
        db = db or BaseService.db()
        db.execute(
            'UPDATE positions SET ' + set_clause + ' WHERE id = ?',
            params + [pos_id]
        )

    @staticmethod
    def delete_position_processes_by_pos(pos_id, db=None):
        db = db or BaseService.db()
        db.execute(
            'DELETE FROM position_processes WHERE position_id = ?', (pos_id,)
        )

    @staticmethod
    def find_valid_process_ids(process_ids, db=None):
        db = db or BaseService.db()
        placeholders = ','.join('?' for _ in process_ids)
        rows = db.execute(
            'SELECT id FROM processes WHERE id IN (' + placeholders + ')', process_ids
        ).fetchall()
        return {r[0] for r in rows}

    @staticmethod
    def count_users_by_position(pos_id, db=None):
        db = db or BaseService.db()
        return db.execute(
            'SELECT COUNT(*) FROM users WHERE position_id = ?', (pos_id,)
        ).fetchone()[0]

    @staticmethod
    def delete_position_by_id(pos_id, db=None):
        db = db or BaseService.db()
        db.execute('DELETE FROM positions WHERE id = ?', (pos_id,))

    @staticmethod
    def find_position_name_by_id(pos_id, db=None):
        db = db or BaseService.db()
        row = db.execute(
            "SELECT id, name FROM positions WHERE id = ?", (pos_id,)
        ).fetchone()
        return row
