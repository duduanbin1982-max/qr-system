"""SQL access for versioned performance rules and position targets."""

from modules.domain.performance_policy import PerformanceConflictError
from modules.repositories.context import resolve_db


class PerformanceConfigurationRepository:
    @staticmethod
    def list_rules(status="", db=None):
        db = resolve_db(db)
        clauses, params = ["1=1"], []
        if status:
            clauses.append("status=?")
            params.append(status)
        return [
            dict(row)
            for row in db.execute(
                "SELECT * FROM performance_rule_versions WHERE "
                + " AND ".join(clauses)
                + " ORDER BY effective_from_month DESC,id DESC",
                params,
            ).fetchall()
        ]

    @staticmethod
    def rule(rule_id, db=None):
        db = resolve_db(db)
        row = db.execute(
            "SELECT * FROM performance_rule_versions WHERE id=?", (rule_id,)
        ).fetchone()
        return dict(row) if row else None

    @staticmethod
    def rule_by_code(version_code, db=None):
        db = resolve_db(db)
        row = db.execute(
            "SELECT * FROM performance_rule_versions WHERE version_code=?",
            (version_code,),
        ).fetchone()
        return dict(row) if row else None

    @staticmethod
    def insert_rule(payload, db):
        cursor = db.execute(
            """
            INSERT INTO performance_rule_versions (
                version_code,name,weights_json,warning_levels_json,
                scoring_parameters_json,effective_from_month,effective_to_month,
                created_by,created_by_name,status
            ) VALUES (?,?,?,?,?,?,?,?,?,'draft')
            """,
            (
                payload["version_code"],
                payload.get("name", ""),
                payload["weights_json"],
                payload["warning_levels_json"],
                payload["scoring_parameters_json"],
                payload.get("effective_from_month", ""),
                payload.get("effective_to_month", ""),
                payload.get("created_by"),
                payload.get("created_by_name", ""),
            ),
        )
        return cursor.lastrowid

    @staticmethod
    def update_rule_draft(rule_id, expected_row_version, fields, db):
        allowed = (
            "name",
            "weights_json",
            "warning_levels_json",
            "scoring_parameters_json",
            "effective_from_month",
            "effective_to_month",
        )
        updates = [(field, fields[field]) for field in allowed if field in fields]
        if not updates:
            raise ValueError("没有可更新的规则字段")
        assignments = ",".join(field + "=?" for field, _ in updates)
        values = [value for _, value in updates]
        values.extend([rule_id, expected_row_version])
        cursor = db.execute(
            "UPDATE performance_rule_versions SET "
            + assignments
            + ",row_version=row_version+1 WHERE id=? AND status='draft' AND row_version=?",
            values,
        )
        if cursor.rowcount == 1:
            return
        row = PerformanceConfigurationRepository.rule(rule_id, db=db)
        if not row:
            raise ValueError("绩效规则版本不存在")
        if row["status"] != "draft":
            raise PerformanceConflictError("published performance rules are immutable")
        raise PerformanceConflictError("绩效规则版本已被其他操作修改，请刷新后重试")

    @staticmethod
    def publish_rule(rule_id, expected_row_version, actor_id, actor_name, db):
        cursor = db.execute(
            """
            UPDATE performance_rule_versions
            SET status='published',published_by=?,published_by_name=?,
                published_at=datetime('now','localtime'),row_version=row_version+1
            WHERE id=? AND status='draft' AND row_version=?
            """,
            (actor_id, actor_name, rule_id, expected_row_version),
        )
        if cursor.rowcount == 1:
            return
        row = PerformanceConfigurationRepository.rule(rule_id, db=db)
        if not row:
            raise ValueError("绩效规则版本不存在")
        if row["status"] != "draft":
            raise PerformanceConflictError("绩效规则状态已变化或已发布")
        raise PerformanceConflictError("绩效规则版本已被其他操作修改，请刷新后重试")

    @staticmethod
    def rule_reference_count(rule_id, db=None):
        db = resolve_db(db)
        return int(
            db.execute(
                "SELECT COUNT(*) FROM performance_batches WHERE rule_version_id=?",
                (rule_id,),
            ).fetchone()[0]
        )

    @staticmethod
    def delete_rule(rule_id, db):
        cursor = db.execute(
            "DELETE FROM performance_rule_versions WHERE id=? AND status='draft'",
            (rule_id,),
        )
        if cursor.rowcount == 1:
            return
        row = PerformanceConfigurationRepository.rule(rule_id, db=db)
        if not row:
            raise ValueError("绩效规则版本不存在")
        raise PerformanceConflictError("只有未发布且未引用的规则草稿可以删除")

    @staticmethod
    def published_rule_for_month(production_month, db=None):
        db = resolve_db(db)
        rows = db.execute(
            """
            SELECT * FROM performance_rule_versions
            WHERE status='published' AND effective_from_month<=?
              AND (effective_to_month='' OR effective_to_month>?)
            ORDER BY effective_from_month DESC,id DESC
            """,
            (production_month, production_month),
        ).fetchall()
        if len(rows) > 1:
            raise PerformanceConflictError("同一生产月份存在多个生效绩效规则版本")
        return dict(rows[0]) if rows else None

    @staticmethod
    def published_rule_overlap(
        effective_from_month, effective_to_month, exclude_id=None, db=None
    ):
        """Return whether a published rule overlaps a half-open month interval."""
        db = resolve_db(db)
        clauses = [
            "status='published'",
            "effective_from_month < CASE WHEN ?='' THEN '9999-99' ELSE ? END",
            "(effective_to_month='' OR effective_to_month>?)",
        ]
        params = [
            effective_to_month or "",
            effective_to_month or "",
            effective_from_month,
        ]
        if exclude_id is not None:
            clauses.append("id<>?")
            params.append(exclude_id)
        return (
            db.execute(
                "SELECT 1 FROM performance_rule_versions WHERE "
                + " AND ".join(clauses)
                + " LIMIT 1",
                params,
            ).fetchone()
            is not None
        )

    @staticmethod
    def list_targets(position_id=None, status="", db=None):
        db = resolve_db(db)
        clauses, params = ["1=1"], []
        if position_id is not None:
            clauses.append("t.position_id=?")
            params.append(position_id)
        if status:
            clauses.append("t.status=?")
            params.append(status)
        return [
            dict(row)
            for row in db.execute(
                "SELECT t.*,p.status AS position_status FROM "
                "performance_position_target_versions t "
                "LEFT JOIN positions p ON p.id=t.position_id WHERE "
                + " AND ".join(clauses)
                + " ORDER BY t.position_id,t.effective_from_month DESC,t.id DESC",
                params,
            ).fetchall()
        ]

    @staticmethod
    def target(target_id, db=None):
        db = resolve_db(db)
        row = db.execute(
            "SELECT t.*,p.status AS position_status FROM "
            "performance_position_target_versions t "
            "LEFT JOIN positions p ON p.id=t.position_id WHERE t.id=?",
            (target_id,),
        ).fetchone()
        return dict(row) if row else None

    @staticmethod
    def position(position_id, db=None):
        db = resolve_db(db)
        row = db.execute(
            "SELECT id,name,status,lifecycle_status,current_effective_version_id "
            "FROM positions WHERE id=?",
            (position_id,),
        ).fetchone()
        return dict(row) if row else None

    @staticmethod
    def insert_target(payload, db):
        cursor = db.execute(
            """
            INSERT INTO performance_position_target_versions (
                position_id,position_version_id_snapshot,position_name_snapshot,target_output_qty,
                minimum_effective_work_days,effective_from_month,effective_to_month,
                created_by,created_by_name,status
            ) VALUES (?,?,?,?,?,?,?,?,?, 'draft')
            """,
            (
                payload["position_id"],
                payload.get("position_version_id_snapshot"),
                payload.get("position_name_snapshot", ""),
                payload["target_output_qty"],
                payload["minimum_effective_work_days"],
                payload["effective_from_month"],
                payload.get("effective_to_month", ""),
                payload.get("created_by"),
                payload.get("created_by_name", ""),
            ),
        )
        return cursor.lastrowid

    @staticmethod
    def update_target_draft(target_id, expected_row_version, fields, db):
        allowed = (
            "position_id",
            "position_version_id_snapshot",
            "position_name_snapshot",
            "target_output_qty",
            "minimum_effective_work_days",
            "effective_from_month",
            "effective_to_month",
        )
        updates = [(field, fields[field]) for field in allowed if field in fields]
        if not updates:
            raise ValueError("没有可更新的岗位目标字段")
        assignments = ",".join(field + "=?" for field, _ in updates)
        values = [value for _, value in updates]
        values.extend([target_id, expected_row_version])
        cursor = db.execute(
            "UPDATE performance_position_target_versions SET "
            + assignments
            + ",row_version=row_version+1 WHERE id=? AND status='draft' AND row_version=?",
            values,
        )
        if cursor.rowcount == 1:
            return
        row = PerformanceConfigurationRepository.target(target_id, db=db)
        if not row:
            raise ValueError("岗位目标版本不存在")
        if row["status"] != "draft":
            raise PerformanceConflictError("approved performance targets are immutable")
        raise PerformanceConflictError("岗位目标版本已被其他操作修改，请刷新后重试")

    @staticmethod
    def approved_target_overlap(
        position_id, effective_from_month, effective_to_month, exclude_id=None, db=None
    ):
        db = resolve_db(db)
        clauses = ["position_id=?", "status='approved'"]
        params = [position_id]
        if effective_to_month:
            clauses.append("effective_from_month<?")
            params.append(effective_to_month)
        clauses.append("(effective_to_month='' OR effective_to_month>?)")
        params.append(effective_from_month)
        if exclude_id is not None:
            clauses.append("id<>?")
            params.append(exclude_id)
        return db.execute(
            "SELECT 1 FROM performance_position_target_versions WHERE "
            + " AND ".join(clauses)
            + " LIMIT 1",
            params,
        ).fetchone() is not None

    @staticmethod
    def approve_target(target_id, expected_row_version, actor_id, actor_name, db):
        cursor = db.execute(
            """
            UPDATE performance_position_target_versions
            SET status='approved',approved_by=?,approved_by_name=?,
                approved_at=datetime('now','localtime'),row_version=row_version+1
            WHERE id=? AND status='draft' AND row_version=?
            """,
            (actor_id, actor_name, target_id, expected_row_version),
        )
        if cursor.rowcount == 1:
            return
        row = PerformanceConfigurationRepository.target(target_id, db=db)
        if not row:
            raise ValueError("岗位目标版本不存在")
        if row["status"] != "draft":
            raise PerformanceConflictError("岗位目标状态已变化或已批准")
        raise PerformanceConflictError("岗位目标版本已被其他操作修改，请刷新后重试")

    @staticmethod
    def target_reference_count(target_id, db=None):
        db = resolve_db(db)
        return int(
            db.execute(
                "SELECT COUNT(*) FROM performance_score_revisions "
                "WHERE position_target_version_id=?",
                (target_id,),
            ).fetchone()[0]
        )

    @staticmethod
    def delete_target(target_id, db):
        cursor = db.execute(
            "DELETE FROM performance_position_target_versions "
            "WHERE id=? AND status='draft'",
            (target_id,),
        )
        if cursor.rowcount == 1:
            return
        row = PerformanceConfigurationRepository.target(target_id, db=db)
        if not row:
            raise ValueError("岗位目标版本不存在")
        raise PerformanceConflictError("只有未批准且未引用的岗位目标草稿可以删除")

    @staticmethod
    def approved_target_for_month(position_id, production_month, db=None):
        db = resolve_db(db)
        rows = db.execute(
            """
            SELECT * FROM performance_position_target_versions
            WHERE position_id=? AND status='approved'
              AND effective_from_month<=?
              AND (effective_to_month='' OR effective_to_month>?)
            ORDER BY effective_from_month DESC,id DESC
            """,
            (position_id, production_month, production_month),
        ).fetchall()
        if len(rows) > 1:
            raise PerformanceConflictError("同一岗位和生产月份存在多个生效岗位目标")
        return dict(rows[0]) if rows else None
