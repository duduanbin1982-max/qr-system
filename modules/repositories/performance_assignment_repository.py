"""SQL access for versioned performance assignment history."""

from modules.domain.errors import ConflictError
from modules.repositories.context import resolve_db


class PerformanceAssignmentRepository:
    """Persist and query immutable employee assignment snapshots."""

    @staticmethod
    def _supports_department_revisions(db):
        return db.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' "
            "AND name='performance_assignment_department_revisions'"
        ).fetchone() is not None

    @staticmethod
    def _supports_position_versions(db):
        return any(
            row[1] == "position_version_id"
            for row in db.execute(
                "PRAGMA table_info(performance_assignment_history)"
            ).fetchall()
        )

    @staticmethod
    def _effective_select(db):
        base = (
            "SELECT assignment.id,assignment.user_id,"
            "assignment.employee_name_snapshot,assignment.employee_no_snapshot,"
            "assignment.position_id,assignment.position_name_snapshot,"
        )
        if PerformanceAssignmentRepository._supports_position_versions(db):
            base += "assignment.position_version_id,"
        else:
            base += "NULL AS position_version_id,"
        tail = (
            "assignment.valid_from,assignment.valid_to,assignment.source_type,"
            "assignment.source_key,assignment.created_by,assignment.created_at,"
            "assignment.department_id AS original_department_id,"
            "assignment.department_name_snapshot AS original_department_name_snapshot,"
        )
        if not PerformanceAssignmentRepository._supports_department_revisions(db):
            return (
                base
                + "assignment.department_id,assignment.department_name_snapshot,"
                + tail
                + "NULL AS department_revision_id,NULL AS department_revision,"
                "'' AS department_revision_source_key,'' AS department_revision_approved_at "
                "FROM performance_assignment_history assignment "
            )
        return (
            base
            + "CASE WHEN department_revision.id IS NULL THEN assignment.department_id "
            "ELSE department_revision.department_id END AS department_id,"
            "CASE WHEN department_revision.id IS NULL "
            "THEN assignment.department_name_snapshot "
            "ELSE department_revision.department_name_snapshot "
            "END AS department_name_snapshot,"
            + tail
            + "department_revision.id AS department_revision_id,"
            "department_revision.revision AS department_revision,"
            "COALESCE(department_revision.source_key,'') AS department_revision_source_key,"
            "COALESCE(department_revision.approved_at,'') AS department_revision_approved_at "
            "FROM performance_assignment_history assignment "
            "LEFT JOIN performance_assignment_department_revisions department_revision "
            "ON department_revision.assignment_id=assignment.id "
            "AND department_revision.status='approved' "
        )

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
                PerformanceAssignmentRepository._effective_select(db)
                + "WHERE assignment.user_id=? "
                "ORDER BY assignment.valid_from,assignment.id",
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
                PerformanceAssignmentRepository._effective_select(db)
                + "WHERE assignment.user_id=? AND assignment.valid_from<? "
                "AND (assignment.valid_to='' OR assignment.valid_to>?) "
                "ORDER BY assignment.valid_from,assignment.id",
                (user_id, period_end, period_start),
            ).fetchall()
        ]

    @staticmethod
    def assignment_at(user_id, business_at, db=None):
        """Return the single assignment effective at one business timestamp."""
        if not business_at:
            raise ValueError("Assignment business_at is required")
        db = resolve_db(db)
        rows = db.execute(
            PerformanceAssignmentRepository._effective_select(db)
            + "WHERE assignment.user_id=? AND assignment.valid_from<=? "
            "AND (assignment.valid_to='' OR assignment.valid_to>?) "
            "ORDER BY assignment.valid_from DESC,assignment.id DESC",
            (user_id, business_at, business_at),
        ).fetchall()
        if len(rows) > 1:
            raise ConflictError(
                "Performance assignment history has overlapping effective intervals"
            )
        return dict(rows[0]) if rows else None

    @staticmethod
    def list_for_collection(period_start, period_end, source_cutoff_at, db=None):
        """List historical assignment intervals effective in the period."""
        if not period_start or not period_end or period_start >= period_end:
            raise ValueError("Invalid assignment collection period")
        if not source_cutoff_at:
            raise ValueError("Assignment collection cutoff is required")
        db = resolve_db(db)
        return [
            dict(row)
            for row in db.execute(
                PerformanceAssignmentRepository._effective_select(db)
                + "WHERE assignment.valid_from<? "
                "AND (assignment.valid_to='' OR assignment.valid_to>?) "
                "AND assignment.valid_from<=? "
                "ORDER BY assignment.user_id,assignment.valid_from,assignment.id",
                (
                    period_end,
                    period_start,
                    source_cutoff_at,
                ),
            ).fetchall()
        ]

    @staticmethod
    def open_assignment(user_id, db=None):
        db = resolve_db(db)
        rows = db.execute(
            PerformanceAssignmentRepository._effective_select(db)
            + "WHERE assignment.user_id=? AND assignment.valid_to='' "
            "ORDER BY assignment.valid_from,assignment.id",
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
        columns = [
            "user_id",
            "employee_name_snapshot",
            "employee_no_snapshot",
            "position_id",
            "position_name_snapshot",
            "department_id",
            "department_name_snapshot",
            "valid_from",
            "valid_to",
            "source_type",
            "source_key",
            "created_by",
        ]
        values = [
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
        ]
        if PerformanceAssignmentRepository._supports_position_versions(db):
            columns.insert(4, "position_version_id")
            values.insert(4, payload.get("position_version_id"))
        cursor = db.execute(
            "INSERT INTO performance_assignment_history ("
            + ",".join(columns)
            + ") VALUES ("
            + ",".join("?" for _ in values)
            + ")",
            values,
        )
        return cursor.lastrowid

    @staticmethod
    def open_assignments_for_position(position_id, db=None):
        db = resolve_db(db)
        return [
            dict(row)
            for row in db.execute(
                PerformanceAssignmentRepository._effective_select(db)
                + "JOIN users active_user ON active_user.id=assignment.user_id "
                "AND active_user.status='active' AND active_user.deleted_at IS NULL "
                "WHERE assignment.position_id=? AND assignment.valid_to='' "
                "ORDER BY assignment.user_id,assignment.id",
                (position_id,),
            ).fetchall()
        ]

    @staticmethod
    def close_assignment(assignment_id, valid_to, db=None):
        db = resolve_db(db)
        cursor = db.execute(
            "UPDATE performance_assignment_history SET valid_to=? "
            "WHERE id=? AND valid_to=''",
            (valid_to, assignment_id),
        )
        return cursor.rowcount

    @staticmethod
    def create_assignment(payload, db=None):
        return PerformanceAssignmentRepository.insert_assignment(payload, db=db)

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
