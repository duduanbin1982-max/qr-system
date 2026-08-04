"""SQL access for performance authorization scopes and scoped results."""

from modules.repositories.context import resolve_db


class PerformanceAuthorizationRepository:
    @staticmethod
    def user_exists(user_id, db=None):
        db = resolve_db(db)
        return db.execute(
            "SELECT 1 FROM users WHERE id=? LIMIT 1", (user_id,)
        ).fetchone() is not None

    @staticmethod
    def existing_department_ids(department_ids, db=None):
        db = resolve_db(db)
        if not department_ids:
            return set()
        placeholders = ",".join("?" for _ in department_ids)
        rows = db.execute(
            "SELECT id FROM departments WHERE id IN (" + placeholders + ")",
            department_ids,
        ).fetchall()
        return {int(row["id"]) for row in rows}

    @staticmethod
    def list_department_scopes(user_id, db=None):
        db = resolve_db(db)
        return [
            dict(row)
            for row in db.execute(
                """
                SELECT d.id,d.name,d.status,scopes.granted_by,
                       scopes.granted_by_name,scopes.created_at
                FROM performance_department_scopes scopes
                JOIN departments d ON d.id=scopes.department_id
                WHERE scopes.user_id=?
                ORDER BY d.id
                """,
                (user_id,),
            ).fetchall()
        ]

    @staticmethod
    def replace_department_scopes(
        user_id, department_ids, granted_by, granted_by_name, db
    ):
        db.execute(
            "DELETE FROM performance_department_scopes WHERE user_id=?", (user_id,)
        )
        for department_id in department_ids:
            db.execute(
                """
                INSERT INTO performance_department_scopes (
                    user_id,department_id,granted_by,granted_by_name
                ) VALUES (?,?,?,?)
                """,
                (user_id, department_id, granted_by, granted_by_name),
            )

    @staticmethod
    def insert_scope_audit(user_id, target_user_id, detail, db):
        db.execute(
            "INSERT INTO audit_logs (user_id,action,target_type,target_id,detail) "
            "VALUES (?,'replace_performance_department_scopes','user',?,?)",
            (user_id, target_user_id, detail),
        )

    @staticmethod
    def latest_score_member(batch_id, user_id, db=None):
        db = resolve_db(db)
        row = db.execute(
            """
            SELECT score.* FROM performance_score_revisions score
            WHERE score.batch_id=? AND score.user_id=?
            ORDER BY score.revision DESC,score.id DESC LIMIT 1
            """,
            (batch_id, user_id),
        ).fetchone()
        return dict(row) if row else None

    @staticmethod
    def _scope_sql(scope, alias="score"):
        if scope.get("all"):
            return "1=1", []
        clauses = []
        params = []
        self_user_id = scope.get("self_user_id")
        if self_user_id is not None:
            clauses.append(alias + ".user_id=?")
            params.append(self_user_id)
        department_ids = list(scope.get("department_ids") or [])
        if department_ids:
            placeholders = ",".join("?" for _ in department_ids)
            clauses.append(
                alias + ".department_id_snapshot IN (" + placeholders + ")"
            )
            params.extend(department_ids)
        if not clauses:
            return "0=1", []
        return "(" + " OR ".join(clauses) + ")", params

    @staticmethod
    def list_score_revisions(
        scope,
        batch_id=None,
        user_id=None,
        department_id=None,
        page=1,
        limit=20,
        db=None,
    ):
        db = resolve_db(db)
        scope_sql, params = PerformanceAuthorizationRepository._scope_sql(scope)
        clauses = [
            scope_sql,
            "NOT EXISTS (SELECT 1 FROM performance_score_revisions newer "
            "WHERE newer.batch_id=score.batch_id AND newer.user_id=score.user_id "
            "AND newer.revision>score.revision)",
        ]
        if batch_id is not None:
            clauses.append("score.batch_id=?")
            params.append(batch_id)
        if user_id is not None:
            clauses.append("score.user_id=?")
            params.append(user_id)
        if department_id is not None:
            clauses.append("score.department_id_snapshot=?")
            params.append(department_id)
        where_sql = " AND ".join(clauses)
        total = db.execute(
            "SELECT COUNT(*) FROM performance_score_revisions score WHERE "
            + where_sql,
            params,
        ).fetchone()[0]
        rows = db.execute(
            "SELECT score.* FROM performance_score_revisions score WHERE "
            + where_sql
            + " ORDER BY score.user_id,score.id LIMIT ? OFFSET ?",
            params + [limit, (page - 1) * limit],
        ).fetchall()
        return {
            "items": [dict(row) for row in rows],
            "total": int(total),
            "page": page,
            "limit": limit,
        }
