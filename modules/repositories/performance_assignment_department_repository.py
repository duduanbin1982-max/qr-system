"""Persistence for versioned performance assignment department supplements."""

from modules.repositories.context import resolve_db


class PerformanceAssignmentDepartmentRepository:
    @staticmethod
    def assignment(assignment_id, db=None):
        db = resolve_db(db)
        row = db.execute(
            "SELECT * FROM performance_assignment_history WHERE id=?",
            (assignment_id,),
        ).fetchone()
        return dict(row) if row else None

    @staticmethod
    def department(department_id, db=None):
        db = resolve_db(db)
        row = db.execute(
            "SELECT id,name,status FROM departments WHERE id=?",
            (department_id,),
        ).fetchone()
        return dict(row) if row else None

    @staticmethod
    def revision(revision_id, db=None):
        db = resolve_db(db)
        row = db.execute(
            "SELECT * FROM performance_assignment_department_revisions WHERE id=?",
            (revision_id,),
        ).fetchone()
        return dict(row) if row else None

    @staticmethod
    def revision_by_source_key(source_key, db=None):
        db = resolve_db(db)
        row = db.execute(
            "SELECT * FROM performance_assignment_department_revisions "
            "WHERE source_key=?",
            (source_key,),
        ).fetchone()
        return dict(row) if row else None

    @staticmethod
    def list_for_assignment(assignment_id, db=None):
        db = resolve_db(db)
        return [
            dict(row)
            for row in db.execute(
                "SELECT * FROM performance_assignment_department_revisions "
                "WHERE assignment_id=? ORDER BY revision,id",
                (assignment_id,),
            ).fetchall()
        ]

    @staticmethod
    def current_approved(assignment_id, db=None):
        db = resolve_db(db)
        row = db.execute(
            "SELECT * FROM performance_assignment_department_revisions "
            "WHERE assignment_id=? AND status='approved' ORDER BY revision DESC,id DESC LIMIT 1",
            (assignment_id,),
        ).fetchone()
        return dict(row) if row else None

    @staticmethod
    def next_revision(assignment_id, db=None):
        db = resolve_db(db)
        return int(
            db.execute(
                "SELECT COALESCE(MAX(revision),0)+1 "
                "FROM performance_assignment_department_revisions WHERE assignment_id=?",
                (assignment_id,),
            ).fetchone()[0]
        )

    @staticmethod
    def insert_revision(payload, db):
        cursor = db.execute(
            """
            INSERT INTO performance_assignment_department_revisions (
                assignment_id,revision,user_id,department_id,
                department_name_snapshot,valid_from_snapshot,valid_to_snapshot,
                reason,source_type,source_key,created_by,created_by_name
            ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)
            """,
            (
                payload["assignment_id"],
                payload["revision"],
                payload["user_id"],
                payload["department_id"],
                payload["department_name_snapshot"],
                payload["valid_from_snapshot"],
                payload.get("valid_to_snapshot", ""),
                payload["reason"],
                payload.get("source_type", "manual_confirmation"),
                payload["source_key"],
                payload["created_by"],
                payload.get("created_by_name", ""),
            ),
        )
        return cursor.lastrowid

    @staticmethod
    def supersede(revision_id, successor_id, expected_row_version, db):
        cursor = db.execute(
            "UPDATE performance_assignment_department_revisions "
            "SET status='superseded',superseded_by_revision_id=?,row_version=row_version+1 "
            "WHERE id=? AND status='approved' AND row_version=?",
            (successor_id, revision_id, expected_row_version),
        )
        return cursor.rowcount == 1

    @staticmethod
    def approve(
        revision_id,
        expected_row_version,
        approved_by,
        approved_by_name,
        supersedes_revision_id,
        db,
    ):
        cursor = db.execute(
            "UPDATE performance_assignment_department_revisions "
            "SET status='approved',approved_by=?,approved_by_name=?,"
            "approved_at=datetime('now','localtime'),supersedes_revision_id=?,"
            "row_version=row_version+1 "
            "WHERE id=? AND status='draft' AND row_version=?",
            (
                approved_by,
                approved_by_name,
                supersedes_revision_id,
                revision_id,
                expected_row_version,
            ),
        )
        return cursor.rowcount == 1
