"""Persistence for evidence-backed performance improvement plans."""

from modules.repositories.context import resolve_db


class PerformanceImprovementRepository:
    @staticmethod
    def database_now(db=None):
        db = resolve_db(db)
        return db.execute("SELECT datetime('now','localtime')").fetchone()[0]

    @staticmethod
    def user_snapshot(user_id, db=None):
        db = resolve_db(db)
        row = db.execute(
            "SELECT u.id AS user_id,COALESCE(u.name,'') AS employee_name_snapshot,"
            "COALESCE(u.employee_no,'') AS employee_no_snapshot,"
            "u.department_id AS department_id_snapshot,"
            "COALESCE(d.name,'') AS department_name_snapshot "
            "FROM users u LEFT JOIN departments d ON d.id=u.department_id "
            "WHERE u.id=?",
            (user_id,),
        ).fetchone()
        return dict(row) if row else None

    @staticmethod
    def score_revision(score_revision_id, db=None):
        db = resolve_db(db)
        row = db.execute(
            "SELECT revision.*,batch.production_month AS batch_production_month "
            "FROM performance_score_revisions revision "
            "JOIN performance_batches batch ON batch.id=revision.batch_id "
            "WHERE revision.id=?",
            (score_revision_id,),
        ).fetchone()
        return dict(row) if row else None

    @staticmethod
    def plan(plan_id, db=None):
        db = resolve_db(db)
        row = db.execute(
            "SELECT * FROM performance_improvement_plans_v2 WHERE id=?",
            (plan_id,),
        ).fetchone()
        return dict(row) if row else None

    @staticmethod
    def plan_summary(plan_id, db=None):
        db = resolve_db(db)
        plan = PerformanceImprovementRepository.plan(plan_id, db=db)
        if not plan:
            return None
        events = PerformanceImprovementRepository.list_events(plan_id, db=db)
        evidence = PerformanceImprovementRepository.list_evidence(plan_id, db=db)
        reassessments = PerformanceImprovementRepository.list_reassessments(
            plan_id, db=db
        )
        return {
            "plan": plan,
            "plan_id": plan["id"],
            "status": plan["status"],
            "row_version": plan["row_version"],
            "production_month": plan["production_month"],
            "reassessment_round": plan["reassessment_round"],
            "events": events,
            "evidence": evidence,
            "reassessments": reassessments,
        }

    @staticmethod
    def list_plans(filters=None, scope=None, db=None):
        db = resolve_db(db)
        filters = filters or {}
        scope = scope or {"all": True, "self_user_id": None, "department_ids": []}
        where = []
        params = []
        if filters.get("production_month"):
            where.append("plan.production_month=?")
            params.append(filters["production_month"])
        if filters.get("status"):
            where.append("plan.status=?")
            params.append(filters["status"])
        if filters.get("user_id") is not None:
            where.append("plan.user_id=?")
            params.append(filters["user_id"])
        if not scope.get("all"):
            visible = []
            if scope.get("self_user_id") is not None:
                visible.append("plan.user_id=?")
                params.append(scope["self_user_id"])
            department_ids = sorted(
                {int(value) for value in scope.get("department_ids", [])}
            )
            if department_ids:
                visible.append(
                    "plan.department_id_snapshot IN ("
                    + ",".join("?" for _ in department_ids)
                    + ")"
                )
                params.extend(department_ids)
            if not visible:
                return []
            where.append("(" + " OR ".join(visible) + ")")
        rows = db.execute(
            "SELECT plan.*,COALESCE(owner.name,'') AS owner_name "
            "FROM performance_improvement_plans_v2 plan "
            "LEFT JOIN users owner ON owner.id=plan.owner_id "
            "WHERE "
            + (" AND ".join(where) if where else "1=1")
            + " ORDER BY plan.production_month DESC,plan.id DESC",
            params,
        ).fetchall()
        return [dict(row) for row in rows]

    @staticmethod
    def insert_plan(payload, db):
        columns = [
            "score_revision_id",
            "user_id",
            "employee_name_snapshot",
            "employee_no_snapshot",
            "department_id_snapshot",
            "department_name_snapshot",
            "production_month",
            "warning_level_snapshot",
            "reason",
            "goal",
            "actions",
            "owner_id",
            "owner_name_snapshot",
            "due_date",
            "created_by",
            "created_by_name",
        ]
        for timestamp_field in ("created_at", "updated_at"):
            if payload.get(timestamp_field):
                columns.append(timestamp_field)
        cursor = db.execute(
            "INSERT INTO performance_improvement_plans_v2 ("
            + ",".join(columns)
            + ") VALUES ("
            + ",".join("?" for _ in columns)
            + ")",
            [payload.get(column) for column in columns],
        )
        return cursor.lastrowid

    @staticmethod
    def transition_plan(
        plan_id,
        expected_row_version,
        current_status,
        target_status,
        fields,
        db,
    ):
        allowed_fields = {
            "reason",
            "goal",
            "actions",
            "owner_id",
            "owner_name_snapshot",
            "due_date",
            "closed_at",
            "cancelled_at",
            "cancellation_reason",
            "reassessment_round",
        }
        invalid = set(fields) - allowed_fields
        if invalid:
            raise ValueError("不允许更新绩效改进计划字段")
        assignments = ["status=?", "row_version=row_version+1"]
        params = [target_status]
        for field in sorted(fields):
            assignments.append(field + "=?")
            params.append(fields[field])
        assignments.append("updated_at=datetime('now','localtime')")
        params.extend([plan_id, expected_row_version, current_status])
        cursor = db.execute(
            "UPDATE performance_improvement_plans_v2 SET "
            + ",".join(assignments)
            + " WHERE id=? AND row_version=? AND status=?",
            params,
        )
        return cursor.rowcount == 1

    @staticmethod
    def insert_event(payload, db):
        fields = [
            "plan_id",
            "event_type",
            "from_status",
            "to_status",
            "reassessment_round",
            "operator_id",
            "operator_name",
            "reason",
            "payload_json",
            "idempotency_key",
        ]
        values = [payload.get(field) for field in fields]
        if payload.get("created_at"):
            fields.append("created_at")
            values.append(payload["created_at"])
        cursor = db.execute(
            "INSERT INTO performance_plan_events ("
            + ",".join(fields)
            + ") VALUES ("
            + ",".join("?" for _ in fields)
            + ")",
            values,
        )
        return cursor.lastrowid

    @staticmethod
    def event_by_idempotency_key(idempotency_key, db=None):
        db = resolve_db(db)
        row = db.execute(
            "SELECT * FROM performance_plan_events WHERE idempotency_key=?",
            (idempotency_key,),
        ).fetchone()
        return dict(row) if row else None

    @staticmethod
    def list_events(plan_id, db=None):
        db = resolve_db(db)
        rows = db.execute(
            "SELECT * FROM performance_plan_events WHERE plan_id=? "
            "ORDER BY created_at,id",
            (plan_id,),
        ).fetchall()
        return [dict(row) for row in rows]

    @staticmethod
    def insert_evidence(payload, db):
        cursor = db.execute(
            "INSERT INTO performance_plan_evidence ("
            "plan_id,reassessment_round,evidence_type,description,file_name,"
            "file_path,source_url,submitted_by,submitted_by_name"
            ") VALUES (?,?,?,?,?,?,?,?,?)",
            (
                payload["plan_id"],
                payload.get("reassessment_round", 0),
                payload.get("evidence_type", "note"),
                payload.get("description", ""),
                payload.get("file_name", ""),
                payload.get("file_path", ""),
                payload.get("source_url", ""),
                payload.get("submitted_by"),
                payload.get("submitted_by_name", ""),
            ),
        )
        return cursor.lastrowid

    @staticmethod
    def evidence(evidence_id, db=None):
        db = resolve_db(db)
        row = db.execute(
            "SELECT * FROM performance_plan_evidence WHERE id=?",
            (evidence_id,),
        ).fetchone()
        return dict(row) if row else None

    @staticmethod
    def list_evidence(plan_id, reassessment_round=None, db=None):
        db = resolve_db(db)
        where = ["plan_id=?"]
        params = [plan_id]
        if reassessment_round is not None:
            where.append("reassessment_round=?")
            params.append(reassessment_round)
        rows = db.execute(
            "SELECT * FROM performance_plan_evidence WHERE "
            + " AND ".join(where)
            + " ORDER BY created_at,id",
            params,
        ).fetchall()
        return [dict(row) for row in rows]

    @staticmethod
    def reassessment_by_idempotency_key(idempotency_key, db=None):
        db = resolve_db(db)
        row = db.execute(
            "SELECT * FROM performance_plan_reassessments "
            "WHERE idempotency_key=?",
            (idempotency_key,),
        ).fetchone()
        return dict(row) if row else None

    @staticmethod
    def reassessment_by_round(plan_id, reassessment_round, db=None):
        db = resolve_db(db)
        row = db.execute(
            "SELECT * FROM performance_plan_reassessments "
            "WHERE plan_id=? AND reassessment_round=?",
            (plan_id, reassessment_round),
        ).fetchone()
        return dict(row) if row else None

    @staticmethod
    def insert_reassessment(payload, db):
        fields = [
            "plan_id",
            "reassessment_round",
            "result",
            "notes",
            "evidence_ids_json",
            "reassessed_by",
            "reassessed_by_name",
            "idempotency_key",
        ]
        values = [payload.get(field) for field in fields]
        if payload.get("reassessed_at"):
            fields.append("reassessed_at")
            values.append(payload["reassessed_at"])
        cursor = db.execute(
            "INSERT INTO performance_plan_reassessments ("
            + ",".join(fields)
            + ") VALUES ("
            + ",".join("?" for _ in fields)
            + ")",
            values,
        )
        return cursor.lastrowid

    @staticmethod
    def reassessment(reassessment_id, db=None):
        db = resolve_db(db)
        row = db.execute(
            "SELECT * FROM performance_plan_reassessments WHERE id=?",
            (reassessment_id,),
        ).fetchone()
        return dict(row) if row else None

    @staticmethod
    def list_reassessments(plan_id, db=None):
        db = resolve_db(db)
        rows = db.execute(
            "SELECT * FROM performance_plan_reassessments WHERE plan_id=? "
            "ORDER BY reassessment_round,id",
            (plan_id,),
        ).fetchall()
        return [dict(row) for row in rows]
