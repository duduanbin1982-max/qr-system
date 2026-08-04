"""SQL access for versioned performance assignment history."""

from modules.domain.errors import ConflictError
from modules.repositories.context import resolve_db


class PerformanceAssignmentRepository:
    """Persist and query immutable employee assignment snapshots."""

    @staticmethod
    def user_snapshot(user_id, db=None):
        db = resolve_db(db)
        row = db.execute(
            """
            SELECT u.id AS user_id,u.name AS employee_name_snapshot,
                   COALESCE(u.employee_no,'') AS employee_no_snapshot,
                   u.position_id,COALESCE(p.name,'') AS position_name_snapshot,
                   u.department_id,COALESCE(d.name,'') AS department_name_snapshot,
                   u.status
            FROM users u
            LEFT JOIN positions p ON p.id=u.position_id
            LEFT JOIN departments d ON d.id=u.department_id
            WHERE u.id=?
            """,
            (user_id,),
        ).fetchone()
        return dict(row) if row else None

    @staticmethod
    def list_for_user(user_id, db=None):
        db = resolve_db(db)
        return [
            dict(row)
            for row in db.execute(
                "SELECT * FROM performance_assignment_history "
                "WHERE user_id=? ORDER BY valid_from,id",
                (user_id,),
            ).fetchall()
        ]

    @staticmethod
    def list_for_period(user_id, period_start, period_end, db=None):
        if not period_start or not period_end or period_start >= period_end:
            raise ValueError("Invalid assignment period")
        db = resolve_db(db)
        return [
            dict(row)
            for row in db.execute(
                """
                SELECT * FROM performance_assignment_history
                WHERE user_id=? AND valid_from<?
                  AND (valid_to='' OR valid_to>?)
                ORDER BY valid_from,id
                """,
                (user_id, period_end, period_start),
            ).fetchall()
        ]

    @staticmethod
    def open_assignment(user_id, db=None):
        db = resolve_db(db)
        rows = db.execute(
            "SELECT * FROM performance_assignment_history "
            "WHERE user_id=? AND valid_to='' ORDER BY valid_from,id",
            (user_id,),
        ).fetchall()
        if len(rows) > 1:
            raise ConflictError("Performance assignment history has multiple open intervals")
        return dict(rows[0]) if rows else None

    @staticmethod
    def has_overlap(user_id, valid_from, valid_to="", exclude_id=None, db=None):
        db = resolve_db(db)
        clauses = [
            "user_id=?",
            "(?='' OR valid_from<?)",
            "(valid_to='' OR valid_to>?)",
        ]
        params = [user_id, valid_to, valid_to, valid_from]
        if exclude_id is not None:
            clauses.append("id<>?")
            params.append(exclude_id)
        row = db.execute(
            "SELECT 1 FROM performance_assignment_history WHERE "
            + " AND ".join(clauses)
            + " LIMIT 1",
            params,
        ).fetchone()
        return row is not None

    @staticmethod
    def insert_assignment(payload, db=None):
        db = resolve_db(db)
        valid_from = str(payload.get("valid_from") or "").strip()
        valid_to = str(payload.get("valid_to") or "").strip()
        if not valid_from:
            raise ValueError("Assignment valid_from is required")
        if valid_to and valid_to <= valid_from:
            raise ValueError("Assignment valid_to must be after valid_from")
        user_id = payload["user_id"]
        if PerformanceAssignmentRepository.has_overlap(
            user_id, valid_from, valid_to, db=db
        ):
            raise ConflictError("Performance assignment interval overlaps existing history")
        cursor = db.execute(
            """
            INSERT INTO performance_assignment_history (
                user_id,employee_name_snapshot,employee_no_snapshot,
                position_id,position_name_snapshot,department_id,
                department_name_snapshot,valid_from,valid_to,source_type,
                source_key,created_by
            ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)
            """,
            (
                user_id,
                payload.get("employee_name_snapshot", ""),
                payload.get("employee_no_snapshot", ""),
                payload.get("position_id"),
                payload.get("position_name_snapshot", ""),
                payload.get("department_id"),
                payload.get("department_name_snapshot", ""),
                valid_from,
                valid_to,
                payload.get("source_type", "application"),
                payload["source_key"],
                payload.get("created_by"),
            ),
        )
        return cursor.lastrowid

    @staticmethod
    def close_open_assignment(user_id, valid_to, db=None):
        db = resolve_db(db)
        current = PerformanceAssignmentRepository.open_assignment(user_id, db=db)
        if not current:
            return 0
        if valid_to <= current["valid_from"]:
            raise ConflictError("Assignment close time must be after valid_from")
        cursor = db.execute(
            "UPDATE performance_assignment_history SET valid_to=? "
            "WHERE id=? AND valid_to=''",
            (valid_to, current["id"]),
        )
        return cursor.rowcount

    @staticmethod
    def has_assignment_history(user_id, db=None):
        db = resolve_db(db)
        return db.execute(
            "SELECT 1 FROM performance_assignment_history WHERE user_id=? LIMIT 1",
            (user_id,),
        ).fetchone() is not None

    @staticmethod
    def candidate_user_ids(period_start, period_end, db=None):
        if not period_start or not period_end or period_start >= period_end:
            raise ValueError("Invalid assignment period")
        db = resolve_db(db)
        rows = db.execute(
            """
            SELECT DISTINCT candidate.user_id
            FROM (
                SELECT user_id
                FROM performance_assignment_history
                WHERE valid_from<? AND (valid_to='' OR valid_to>?)
                UNION
                SELECT facts.user_id
                FROM performance_source_facts facts
                JOIN performance_batches batches ON batches.id=facts.batch_id
                WHERE facts.user_id IS NOT NULL
                  AND batches.period_start<? AND batches.period_end>?
            ) candidate
            ORDER BY candidate.user_id
            """,
            (period_end, period_start, period_end, period_start),
        ).fetchall()
        return [int(row["user_id"]) for row in rows]
