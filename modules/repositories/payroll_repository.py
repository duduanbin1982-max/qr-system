"""SQL access for the versioned payroll ledger."""

import json

from modules.domain.payroll_policy import PayrollConflictError
from modules.domain.price_versioning import StaleRowVersionError
from modules.repositories.context import resolve_db
from modules.process_fact_projection import (
    process_value_sql,
    process_version_join,
    route_name_sql,
    route_version_join,
    warn_legacy_fact_rows,
)


class PayrollRepository:
    @staticmethod
    def get_batch(batch_id, db=None):
        db = resolve_db(db)
        row = db.execute("SELECT * FROM payroll_batches WHERE id=?", (batch_id,)).fetchone()
        return dict(row) if row else None

    @staticmethod
    def get_batch_by_idempotency(key, db=None):
        db = resolve_db(db)
        row = db.execute("SELECT * FROM payroll_batches WHERE idempotency_key=?", (key,)).fetchone()
        return dict(row) if row else None

    @staticmethod
    def list_batches(month="", status="", db=None):
        db = resolve_db(db)
        clauses, params = ["1=1"], []
        if month:
            clauses.append("pb.payroll_month=?")
            params.append(month)
        if status:
            clauses.append("pb.status=?")
            params.append(status)
        return [dict(row) for row in db.execute(
            "SELECT pb.*, prepared.name AS prepared_user_name, locked.name AS locked_user_name, "
            "confirmed.name AS confirmed_user_name "
            "FROM payroll_batches pb "
            "LEFT JOIN users prepared ON prepared.id=pb.prepared_by "
            "LEFT JOIN users locked ON locked.id=pb.locked_by "
            "LEFT JOIN users confirmed ON confirmed.id=pb.confirmed_by "
            "WHERE " + " AND ".join(clauses) + " ORDER BY pb.payroll_month DESC,pb.version DESC",
            params,
        ).fetchall()]

    @staticmethod
    def next_version(month, db=None):
        db = resolve_db(db)
        return int(db.execute(
            "SELECT COALESCE(MAX(version),0)+1 FROM payroll_batches WHERE payroll_month=?", (month,)
        ).fetchone()[0])

    @staticmethod
    def current_confirmed(month, db=None):
        db = resolve_db(db)
        row = db.execute(
            "SELECT * FROM payroll_batches WHERE payroll_month=? AND status='confirmed' "
            "AND superseded_by_batch_id IS NULL ORDER BY version DESC LIMIT 1", (month,)
        ).fetchone()
        return dict(row) if row else None

    @staticmethod
    def insert_batch(payload, db):
        columns = (
            "payroll_month", "version", "period_start", "period_end", "status", "source_cutoff_at",
            "input_digest", "idempotency_key", "prepared_by", "prepared_by_name", "revision_reason",
            "supersedes_batch_id", "legacy_imported",
        )
        values = [payload.get(column) for column in columns]
        cursor = db.execute(
            "INSERT INTO payroll_batches (" + ",".join(columns) + ") VALUES (" + ",".join("?" for _ in columns) + ")",
            values,
        )
        return cursor.lastrowid

    @staticmethod
    def delete_draft_calculation(batch_id, db):
        db.execute(
            "DELETE FROM payroll_detail_lines WHERE batch_id=?", (batch_id,)
        )
        db.execute("DELETE FROM payroll_employee_lines WHERE batch_id=?", (batch_id,))
        db.execute(
            "DELETE FROM payroll_exceptions WHERE batch_id=? AND status IN ('pending','proposed','rejected')",
            (batch_id,),
        )

    @staticmethod
    def source_work_records(period_start, period_end, cutoff, db=None):
        db = resolve_db(db)
        process_name = process_value_sql("wr", "process_version", "proc")
        process_code = process_value_sql(
            "wr", "process_version", "proc", field="code"
        )
        process_category = process_value_sql(
            "wr", "process_version", "proc", field="category"
        )
        route_name = route_name_sql("wr", "route_version", "route")
        rows = db.execute(
            "SELECT wr.id AS work_record_id,wr.order_id,wr.process_id,wr.user_id,"
            "wr.type AS work_type,wr.quantity,wr.created_at AS work_recorded_at,"
            "wr.process_version_id,u.name AS employee_name,u.employee_no,"
            "COALESCE(pos.name,'') AS position_name,o.order_no,o.product_code,o.product_name,"
            "COALESCE(wr.route_id,o.route_id) AS route_id,wr.route_version_id,"
            + route_name + " AS route_name," + process_name + " AS process_name,"
            + process_code + " AS process_code," + process_category + " AS process_category "
            "FROM work_records wr JOIN users u ON u.id=wr.user_id "
            "LEFT JOIN positions pos ON pos.id=u.position_id "
            "LEFT JOIN orders o ON o.id=wr.order_id "
            "LEFT JOIN process_routes route ON route.id=COALESCE(wr.route_id,o.route_id) "
            + route_version_join("wr", "route_version")
            + "LEFT JOIN processes proc ON proc.id=wr.process_id "
            + process_version_join("wr", "process_version")
            + "WHERE wr.status='approved' AND wr.type IN ('normal','rework') "
            "AND wr.created_at>=? AND wr.created_at<? AND wr.created_at<=? "
            "ORDER BY wr.created_at,wr.id",
            (period_start, period_end, cutoff),
        ).fetchall()
        warn_legacy_fact_rows("work_records", rows)
        return [dict(row) for row in rows]

    @staticmethod
    def price_candidates(
        route_id,
        process_id,
        at,
        db=None,
        *,
        route_version_id=None,
        process_version_id=None,
    ):
        db = resolve_db(db)
        if route_version_id is not None and process_version_id is not None:
            where = "route_version_id=? AND process_version_id=?"
            params = (route_version_id, process_version_id, at, at)
        else:
            where = "route_id=? AND process_id=?"
            params = (route_id, process_id, at, at)
        return [dict(row) for row in db.execute(
            f"""
            SELECT * FROM route_price_versions
            WHERE {where} AND status='approved'
              AND valid_from<=? AND (COALESCE(valid_to,'')='' OR valid_to>?)
            ORDER BY valid_from DESC,id DESC
            """, params
        ).fetchall()]

    @staticmethod
    def price_resolution(work_record_id, db=None):
        db = resolve_db(db)
        row = db.execute(
            "SELECT r.*,"
            "COALESCE(r.override_unit_price_micros,p.normal_unit_price_micros) AS normal_unit_price_micros,"
            "COALESCE(r.override_rework_rate_basis_points,p.rework_rate_basis_points,0) AS rework_rate_basis_points,"
            "CASE WHEN r.override_rework_rate_basis_points IS NOT NULL THEN 1 "
            "ELSE COALESCE(p.rework_rate_configured,0) END AS rework_rate_configured "
            "FROM payroll_work_price_resolutions r "
            "LEFT JOIN route_price_versions p ON p.id=r.price_version_id "
            "WHERE r.work_record_id=?", (work_record_id,)
        ).fetchone()
        return dict(row) if row else None

    @staticmethod
    def insert_price_resolution(payload, db):
        cursor = db.execute(
            """
            INSERT INTO payroll_work_price_resolutions (
                work_record_id,price_version_id,override_unit_price_micros,
                override_rework_rate_basis_points,resolution_method,resolution_reason,
                policy_code,resolved_by,resolved_by_name
            ) VALUES (?,?,?,?,?,?,?,?,?)
            """,
            (
                payload["work_record_id"], payload.get("price_version_id"),
                payload.get("override_unit_price_micros"),
                payload.get("override_rework_rate_basis_points"), payload["resolution_method"],
                payload["resolution_reason"], payload.get("policy_code", ""),
                payload.get("resolved_by"), payload.get("resolved_by_name", ""),
            ),
        )
        return cursor.lastrowid

    @staticmethod
    def approved_exception(work_record_id, batch_id, db=None):
        db = resolve_db(db)
        row = db.execute(
            "SELECT * FROM payroll_exceptions WHERE batch_id=? AND work_record_id=? AND status='approved' "
            "ORDER BY id DESC LIMIT 1", (batch_id, work_record_id)
        ).fetchone()
        return dict(row) if row else None

    @staticmethod
    def insert_exception(payload, db):
        db.execute(
            """
            INSERT OR IGNORE INTO payroll_exceptions (
                batch_id,work_record_id,employee_id,exception_type,snapshot_json
            ) VALUES (?,?,?,?,?)
            """,
            (
                payload["batch_id"], payload["work_record_id"], payload.get("employee_id"),
                payload["exception_type"], json.dumps(payload.get("snapshot", {}), ensure_ascii=False),
            ),
        )

    @staticmethod
    def insert_employee_line(payload, db):
        cursor = db.execute(
            """
            INSERT INTO payroll_employee_lines (
                batch_id,employee_id,employee_name_snapshot,employee_no_snapshot,position_name_snapshot,
                normal_quantity,rework_quantity,normal_wage_cents,rework_wage_cents,
                bonus_cents,allowance_cents,deduction_cents,payable_wage_cents,exception_count
            ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            """,
            (
                payload["batch_id"], payload.get("employee_id"), payload["employee_name_snapshot"],
                payload.get("employee_no_snapshot", ""), payload.get("position_name_snapshot", ""),
                payload.get("normal_quantity", 0), payload.get("rework_quantity", 0),
                payload.get("normal_wage_cents", 0), payload.get("rework_wage_cents", 0),
                payload.get("bonus_cents", 0), payload.get("allowance_cents", 0),
                payload.get("deduction_cents", 0), payload.get("payable_wage_cents", 0),
                payload.get("exception_count", 0),
            ),
        )
        return cursor.lastrowid

    @staticmethod
    def insert_detail_line(payload, db):
        columns = (
            "batch_id", "employee_line_id", "source_type", "source_id", "work_record_id",
            "work_recorded_at", "order_id", "order_no_snapshot", "product_code_snapshot",
            "product_name_snapshot", "route_id", "route_version_id", "route_name_snapshot",
            "process_id", "process_version_id", "process_name_snapshot", "quantity",
            "price_version_id", "unit_price_micros",
            "rework_rate_basis_points", "amount_cents", "resolution_method", "resolution_reason",
            "resolved_by", "resolved_by_name", "resolved_at", "source_snapshot_json",
        )
        db.execute(
            "INSERT INTO payroll_detail_lines (" + ",".join(columns) + ") VALUES (" + ",".join("?" for _ in columns) + ")",
            [payload.get(column) for column in columns],
        )

    @staticmethod
    def insert_adjustment_detail(payload, db):
        PayrollRepository.insert_detail_line(payload, db)

    @staticmethod
    def update_batch_calculation(batch_id, expected_row_version, payload, db):
        assignments = (
            "status", "input_digest", "source_cutoff_at", "normal_wage_cents", "rework_wage_cents",
            "bonus_cents", "allowance_cents", "deduction_cents", "payable_wage_cents",
            "source_record_count", "priced_record_count", "exception_count",
        )
        values = [payload.get(key, 0) for key in assignments]
        values.extend([batch_id, expected_row_version])
        cursor = db.execute(
            "UPDATE payroll_batches SET " + ",".join(f"{key}=?" for key in assignments) +
            ",row_version=row_version+1,updated_at=datetime('now','localtime') "
            "WHERE id=? AND row_version=? AND status IN ('draft','exceptions_pending')",
            values,
        )
        if cursor.rowcount != 1:
            raise PayrollConflictError("工资批次版本冲突，请刷新后重试")

    @staticmethod
    def update_line_exception_counts(batch_id, db):
        db.execute(
            """
            UPDATE payroll_employee_lines SET exception_count=(
                SELECT COUNT(*) FROM payroll_exceptions e
                WHERE e.batch_id=payroll_employee_lines.batch_id
                  AND e.employee_id=payroll_employee_lines.employee_id
                  AND e.status IN ('pending','proposed')
            ) WHERE batch_id=?
            """, (batch_id,)
        )

    @staticmethod
    def transition_batch(batch_id, expected_row_version, status, fields, db):
        allowed = {
            "status", "submitted_at", "locked_by", "locked_by_name", "locked_at",
            "confirmed_by", "confirmed_by_name", "confirmed_at", "voided_by", "voided_by_name",
            "voided_at", "void_reason", "superseded_by_batch_id", "row_version", "updated_at",
        }
        if not set(fields).issubset(allowed):
            raise ValueError("非法工资批次更新字段")
        fields = dict(fields)
        assignments = ["status=?"]
        values = [status]
        for key, value in fields.items():
            if key == "status":
                continue
            assignments.append(key + "=?")
            values.append(value)
        assignments.extend(["row_version=row_version+1", "updated_at=datetime('now','localtime')"])
        values.extend([batch_id, expected_row_version])
        cursor = db.execute(
            "UPDATE payroll_batches SET " + ",".join(assignments) +
            " WHERE id=? AND row_version=?",
            values,
        )
        if cursor.rowcount != 1:
            raise PayrollConflictError("工资批次版本冲突，请刷新后重试")

    @staticmethod
    def mark_superseded(batch_id, successor_id, db):
        db.execute(
            "UPDATE payroll_batches SET superseded_by_batch_id=?,row_version=row_version+1,updated_at=datetime('now','localtime') "
            "WHERE id=? AND superseded_by_batch_id IS NULL", (successor_id, batch_id)
        )

    @staticmethod
    def insert_event(payload, db):
        key = str(payload.get("idempotency_key") or "")
        if key:
            existing = PayrollRepository.event_by_idempotency_key(key, db=db)
            if existing is not None:
                return existing
        db.execute(
            """
            INSERT INTO payroll_events (
                batch_id,event_type,from_status,to_status,operator_id,operator_name,reason,
                payload_json,request_id,idempotency_key
            ) VALUES (?,?,?,?,?,?,?,?,?,?)
            """,
            (
                payload.get("batch_id"), payload["event_type"], payload.get("from_status", ""),
                payload.get("to_status", ""), payload.get("operator_id"), payload.get("operator_name", ""),
                payload.get("reason", ""), json.dumps(payload.get("payload", {}), ensure_ascii=False),
                payload.get("request_id", ""), payload.get("idempotency_key", ""),
            ),
        )
        return PayrollRepository.event_by_idempotency_key(key, db=db) if key else None

    @staticmethod
    def event_by_idempotency_key(idempotency_key, db=None):
        key = str(idempotency_key or "")
        if not key:
            return None
        db = resolve_db(db)
        row = db.execute(
            "SELECT * FROM payroll_events WHERE idempotency_key=? ORDER BY id LIMIT 1",
            (key,),
        ).fetchone()
        return dict(row) if row else None

    @staticmethod
    def list_lines(batch_id, employee_id=None, db=None):
        db = resolve_db(db)
        clauses, params = ["el.batch_id=?"], [batch_id]
        if employee_id is not None:
            clauses.append("el.employee_id=?")
            params.append(employee_id)
        return [dict(row) for row in db.execute(
            "SELECT el.* FROM payroll_employee_lines el WHERE " + " AND ".join(clauses) +
            " ORDER BY el.payable_wage_cents DESC,el.id", params
        ).fetchall()]

    @staticmethod
    def list_details(batch_id, employee_id=None, db=None):
        db = resolve_db(db)
        clauses, params = ["d.batch_id=?"], [batch_id]
        if employee_id is not None:
            clauses.append("el.employee_id=?")
            params.append(employee_id)
        return [dict(row) for row in db.execute(
            "SELECT d.*,el.employee_id,el.employee_name_snapshot,el.employee_no_snapshot "
            "FROM payroll_detail_lines d JOIN payroll_employee_lines el ON el.id=d.employee_line_id "
            "WHERE " + " AND ".join(clauses) + " ORDER BY d.id", params
        ).fetchall()]

    @staticmethod
    def list_events(batch_id, db=None):
        db = resolve_db(db)
        return [dict(row) for row in db.execute(
            "SELECT * FROM payroll_events WHERE batch_id=? ORDER BY id", (batch_id,)
        ).fetchall()]

    @staticmethod
    def list_exceptions(month="", batch_id=None, status="", db=None):
        db = resolve_db(db)
        clauses, params = ["1=1"], []
        if month:
            clauses.append("pb.payroll_month=?")
            params.append(month)
        if batch_id is not None:
            clauses.append("e.batch_id=?")
            params.append(batch_id)
        if status:
            clauses.append("e.status=?")
            params.append(status)
        return [dict(row) for row in db.execute(
            "SELECT e.*,pb.payroll_month,pb.version,u.name AS employee_name,u.employee_no "
            "FROM payroll_exceptions e JOIN payroll_batches pb ON pb.id=e.batch_id "
            "LEFT JOIN users u ON u.id=e.employee_id WHERE " + " AND ".join(clauses) + " ORDER BY e.id", params
        ).fetchall()]

    @staticmethod
    def update_exception_proposal(exception_id, expected_status, payload, db):
        assignments = ["status='proposed'", "proposed_price_micros=?", "proposed_rework_rate_basis_points=?",
                       "proposed_by=?", "proposed_by_name=?", "proposed_at=datetime('now','localtime')",
                       "resolution_reason=?", "updated_at=datetime('now','localtime')"]
        cursor = db.execute(
            "UPDATE payroll_exceptions SET " + ",".join(assignments) +
            " WHERE id=? AND status=?",
            (
                payload.get("proposed_price_micros"), payload.get("proposed_rework_rate_basis_points"),
                payload.get("proposed_by"), payload.get("proposed_by_name", ""), payload.get("resolution_reason", ""),
                exception_id, expected_status,
            ),
        )
        if cursor.rowcount != 1:
            raise PayrollConflictError("工资异常状态已变化，请刷新")

    @staticmethod
    def approve_exception(exception_id, expected_status, payload, db):
        cursor = db.execute(
            """
            UPDATE payroll_exceptions SET status='approved',approved_by=?,approved_by_name=?,
                   approved_at=datetime('now','localtime'),updated_at=datetime('now','localtime')
            WHERE id=? AND status=?
            """,
            (payload.get("approved_by"), payload.get("approved_by_name", ""), exception_id, expected_status),
        )
        if cursor.rowcount != 1:
            raise PayrollConflictError("工资异常状态已变化，请刷新")

    @staticmethod
    def create_adjustment(payload, db):
        cursor = db.execute(
            """
            INSERT INTO payroll_adjustments (
                employee_id,employee_name_snapshot,employee_no_snapshot,payroll_month,adjustment_type,
                amount_cents,reason,created_by,created_by_name,reversal_of_id,replacement_for_id
            ) VALUES (?,?,?,?,?,?,?,?,?,?,?)
            """,
            (
                payload.get("employee_id"), payload["employee_name_snapshot"], payload.get("employee_no_snapshot", ""),
                payload["payroll_month"], payload["adjustment_type"], payload["amount_cents"], payload["reason"],
                payload.get("created_by"), payload.get("created_by_name", ""), payload.get("reversal_of_id"),
                payload.get("replacement_for_id"),
            ),
        )
        return cursor.lastrowid

    @staticmethod
    def get_adjustment(adjustment_id, db=None):
        db = resolve_db(db)
        row = db.execute("SELECT * FROM payroll_adjustments WHERE id=?", (adjustment_id,)).fetchone()
        return dict(row) if row else None

    @staticmethod
    def has_adjustment_reversal(adjustment_id, db=None):
        db = resolve_db(db)
        return bool(db.execute(
            "SELECT 1 FROM payroll_adjustments WHERE reversal_of_id=?",
            (adjustment_id,),
        ).fetchone())

    @staticmethod
    def list_adjustments(month="", employee_id=None, db=None):
        db = resolve_db(db)
        clauses, params = ["1=1"], []
        if month:
            clauses.append("payroll_month=?")
            params.append(month)
        if employee_id is not None:
            clauses.append("employee_id=?")
            params.append(employee_id)
        return [dict(row) for row in db.execute(
            "SELECT * FROM payroll_adjustments WHERE " + " AND ".join(clauses) + " ORDER BY id DESC", params
        ).fetchall()]

    @staticmethod
    def adjustments_for_month(month, cutoff, db=None):
        db = resolve_db(db)
        return [dict(row) for row in db.execute(
            "SELECT * FROM payroll_adjustments WHERE payroll_month=? AND created_at<=? ORDER BY id", (month, cutoff)
        ).fetchall()]

    @staticmethod
    def user_snapshot(employee_id, db=None):
        db = resolve_db(db)
        row = db.execute(
            "SELECT u.id,u.name,u.employee_no,COALESCE(p.name,'') AS position_name "
            "FROM users u LEFT JOIN positions p ON p.id=u.position_id WHERE u.id=?", (employee_id,)
        ).fetchone()
        return dict(row) if row else None

    @staticmethod
    def my_confirmed_lines(employee_id, month="", db=None):
        db = resolve_db(db)
        clauses, params = ["el.employee_id=?", "pb.status='confirmed'", "pb.superseded_by_batch_id IS NULL"], [employee_id]
        if month:
            clauses.append("pb.payroll_month=?")
            params.append(month)
        return [dict(row) for row in db.execute(
            "SELECT pb.id AS batch_id,pb.payroll_month,pb.version,pb.status,el.* "
            "FROM payroll_employee_lines el JOIN payroll_batches pb ON pb.id=el.batch_id "
            "WHERE " + " AND ".join(clauses) + " ORDER BY pb.payroll_month DESC,pb.version DESC", params
        ).fetchall()]

    @staticmethod
    def compare_batches(batch_a, batch_b, db=None):
        db = resolve_db(db)
        return [dict(row) for row in db.execute(
            """
            SELECT a.employee_id,
                   a.employee_name_snapshot AS employee_name,
                   a.payable_wage_cents AS wage_a,
                   COALESCE(b.payable_wage_cents,0) AS wage_b,
                   COALESCE(b.payable_wage_cents,0)-a.payable_wage_cents AS difference_cents
            FROM payroll_employee_lines a
            LEFT JOIN payroll_employee_lines b
              ON b.batch_id=? AND b.employee_id=a.employee_id
            WHERE a.batch_id=?
            UNION ALL
            SELECT b.employee_id,
                   b.employee_name_snapshot AS employee_name,
                   0 AS wage_a,
                   b.payable_wage_cents AS wage_b,
                   b.payable_wage_cents AS difference_cents
            FROM payroll_employee_lines b
            LEFT JOIN payroll_employee_lines a
              ON a.batch_id=? AND a.employee_id=b.employee_id
            WHERE b.batch_id=? AND a.id IS NULL
            ORDER BY employee_name,employee_id
            """, (batch_b, batch_a, batch_a, batch_b)
        ).fetchall()]

    @staticmethod
    def create_price_version(payload, db):
        cursor = db.execute(
            """
            INSERT INTO route_price_versions (
                route_id,route_version_id,process_id,process_version_id,
                normal_unit_price_micros,rework_rate_basis_points,
                rework_rate_configured,valid_from,status,created_by,created_by_name,remark,
                idempotency_key,request_digest,route_content_digest_snapshot,
                process_content_digest_snapshot
            ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            """,
            (
                payload["route_id"], payload["route_version_id"],
                payload["process_id"], payload["process_version_id"],
                payload["normal_unit_price_micros"],
                payload.get("rework_rate_basis_points", 0), payload.get("rework_rate_configured", 0),
                payload["valid_from"], "draft", payload.get("created_by"), payload.get("created_by_name", ""),
                payload.get("remark", ""),
                payload.get("idempotency_key"), payload.get("request_digest", ""),
                payload.get("route_content_digest_snapshot", ""),
                payload.get("process_content_digest_snapshot", ""),
            ),
        )
        return cursor.lastrowid

    @staticmethod
    def price_version(version_id, db=None):
        db = resolve_db(db)
        row = db.execute("SELECT * FROM route_price_versions WHERE id=?", (version_id,)).fetchone()
        return dict(row) if row else None

    @staticmethod
    def list_price_versions(
        route_id=None,
        status="",
        route_version_id=None,
        process_version_id=None,
        db=None,
    ):
        db = resolve_db(db)
        clauses, params = ["1=1"], []
        if route_id is not None:
            clauses.append("v.route_id=?")
            params.append(route_id)
        if status:
            clauses.append("v.status=?")
            params.append(status)
        if route_version_id is not None:
            clauses.append("v.route_version_id=?")
            params.append(route_version_id)
        if process_version_id is not None:
            clauses.append("v.process_version_id=?")
            params.append(process_version_id)
        return [dict(row) for row in db.execute(
            "SELECT v.*,COALESCE(rv.name,r.name) AS route_name,"
            "COALESCE(pv.name,p.name) AS process_name FROM route_price_versions v "
            "LEFT JOIN process_routes r ON r.id=v.route_id "
            "LEFT JOIN process_route_versions rv ON rv.id=v.route_version_id "
            "LEFT JOIN processes p ON p.id=v.process_id "
            "LEFT JOIN process_versions pv ON pv.id=v.process_version_id "
            "WHERE " + " AND ".join(clauses) + " ORDER BY v.route_id,v.process_id,v.valid_from DESC,v.id DESC", params
        ).fetchall()]

    @staticmethod
    def list_route_process_references(include_pending=False, db=None):
        db = resolve_db(db)
        rows = db.execute(
            "WITH candidate_route_versions AS ("
            "SELECT route.id AS route_id,version.id AS route_version_id "
            "FROM process_routes route JOIN process_route_versions version "
            "ON version.id=route.current_effective_version_id "
            "WHERE route.lifecycle_status='active' AND version.status='published' "
            "UNION ALL "
            "SELECT route.id AS route_id,version.id AS route_version_id "
            "FROM process_routes route JOIN process_route_versions version "
            "ON version.process_route_id=route.id "
            "WHERE ?=1 AND route.lifecycle_status='active' "
            "AND version.status='pending_approval') "
            "SELECT route.id AS route_id,route_version.id AS route_version_id,"
            "route_version.version AS route_version,"
            "route_version.name AS route_name,route_version.category AS route_category,"
            "route_version.status AS route_version_status,"
            "route_version.content_digest AS route_content_digest,"
            "process.id AS process_id,process_version.id AS process_version_id,"
            "process_version.version AS process_version,"
            "process_version.name AS process_name,"
            "process_version.status AS process_version_status,"
            "process_version.content_digest AS process_content_digest,item.seq_order,"
            "CAST(route_version.id AS TEXT)||':'||CAST(process_version.id AS TEXT) "
            "AS reference_key,"
            "CASE route_version.status WHEN 'published' THEN 'published_adjustment' "
            "ELSE 'pending_group_release' END AS pricing_mode "
            "FROM candidate_route_versions candidate "
            "JOIN process_routes route ON route.id=candidate.route_id "
            "JOIN process_route_versions route_version "
            "ON route_version.id=candidate.route_version_id "
            "JOIN process_route_version_items item "
            "ON item.route_version_id=route_version.id "
            "JOIN processes process ON process.id=item.process_id "
            "JOIN process_versions process_version "
            "ON process_version.id=item.process_version_id "
            "WHERE process.lifecycle_status='active' AND ("
            "(route_version.status='published' AND process_version.status='published') OR "
            "(route_version.status='pending_approval' "
            "AND process_version.status IN ('published','pending_approval'))) "
            "ORDER BY route_version.category,route_version.name,"
            "route_version.version,item.seq_order,item.id",
            (int(bool(include_pending)),),
        ).fetchall()
        return [dict(row) for row in rows]

    @staticmethod
    def route_process_exists(route_id, process_id, db=None):
        db = resolve_db(db)
        return bool(db.execute(
            "SELECT 1 FROM process_route_items WHERE route_id=? AND process_id=?", (route_id, process_id)
        ).fetchone())

    @staticmethod
    def exact_price_binding(route_version_id, process_version_id, db=None):
        db = resolve_db(db)
        row = db.execute(
            "SELECT route_version.id AS route_version_id,"
            "route_version.process_route_id AS route_id,"
            "route_version.status AS route_version_status,"
            "route_version.version AS route_version,"
            "route_version.content_digest AS route_content_digest,"
            "process_version.id AS process_version_id,"
            "process_version.process_id AS process_id,"
            "process_version.status AS process_version_status,"
            "process_version.version AS process_version,"
            "process_version.content_digest AS process_content_digest "
            "FROM process_route_versions route_version "
            "JOIN process_route_version_items item "
            "ON item.route_version_id=route_version.id "
            "JOIN process_versions process_version "
            "ON process_version.id=item.process_version_id "
            "WHERE route_version.id=? AND process_version.id=?",
            (route_version_id, process_version_id),
        ).fetchone()
        return dict(row) if row else None

    @staticmethod
    def price_version_by_idempotency_key(idempotency_key, db=None):
        key = str(idempotency_key or "")
        if not key:
            return None
        db = resolve_db(db)
        row = db.execute(
            "SELECT * FROM route_price_versions WHERE idempotency_key=?", (key,)
        ).fetchone()
        return dict(row) if row else None

    @staticmethod
    def draft_price_for_binding(route_version_id, process_version_id, db=None):
        db = resolve_db(db)
        row = db.execute(
            "SELECT * FROM route_price_versions WHERE route_version_id=? "
            "AND process_version_id=? AND status='draft' ORDER BY id DESC LIMIT 1",
            (route_version_id, process_version_id),
        ).fetchone()
        return dict(row) if row else None

    @staticmethod
    def void_price_version(version_id, expected_row_version, payload, db):
        cursor = db.execute(
            "UPDATE route_price_versions SET status='voided',"
            "voided_at=COALESCE(?,datetime('now','localtime')),voided_by=?,"
            "voided_by_name=?,void_reason=?,row_version=row_version+1 "
            "WHERE id=? AND status='draft' AND row_version=?",
            (
                payload.get("voided_at"), payload.get("voided_by"),
                payload.get("voided_by_name", ""), payload.get("void_reason", ""),
                version_id, expected_row_version,
            ),
        )
        if cursor.rowcount != 1:
            raise StaleRowVersionError(
                "工价版本状态已变化，请刷新后重试",
                details={"price_version_id": version_id},
            )
        return PayrollRepository.price_version(version_id, db=db)

    @staticmethod
    def void_draft_prices_for_route(route_version_id, payload, db):
        drafts = [dict(row) for row in db.execute(
            "SELECT id,row_version FROM route_price_versions "
            "WHERE route_version_id=? AND status='draft' ORDER BY id",
            (route_version_id,),
        ).fetchall()]
        return [
            PayrollRepository.void_price_version(
                row["id"], row["row_version"], payload, db
            )
            for row in drafts
        ]

    @staticmethod
    def record_reference_compat_audit(
        legacy_published_digest, versioned_published_digest, db
    ):
        rows = db.execute(
            "SELECT price.id AS price_version_id,"
            "route_version.content_digest AS route_content_digest,"
            "process_version.content_digest AS process_content_digest,"
            "price.route_content_digest_snapshot,"
            "price.process_content_digest_snapshot "
            "FROM route_price_versions price "
            "JOIN process_routes route ON route.id=price.route_id "
            "JOIN process_route_versions route_version "
            "ON route_version.id=route.current_effective_version_id "
            "AND route_version.id=price.route_version_id "
            "JOIN process_route_version_items item "
            "ON item.route_version_id=route_version.id "
            "AND item.process_version_id=price.process_version_id "
            "JOIN process_versions process_version "
            "ON process_version.id=price.process_version_id "
            "WHERE route_version.status='published' "
            "AND process_version.status='published' "
            "AND price.status<>'voided' ORDER BY price.id"
        ).fetchall()
        for row in rows:
            mismatch = int(
                legacy_published_digest != versioned_published_digest
                or row["route_content_digest"] != row["route_content_digest_snapshot"]
                or row["process_content_digest"] != row["process_content_digest_snapshot"]
            )
            db.execute(
                "INSERT OR IGNORE INTO route_price_reference_compat_audit ("
                "price_version_id,published_route_content_digest,"
                "published_process_content_digest,price_route_content_digest_snapshot,"
                "price_process_content_digest_snapshot,mismatch,detail_json) "
                "VALUES (?,?,?,?,?,?,?)",
                (
                    row["price_version_id"], row["route_content_digest"],
                    row["process_content_digest"],
                    row["route_content_digest_snapshot"],
                    row["process_content_digest_snapshot"], mismatch,
                    json.dumps(
                        {
                            "legacy_published_digest": legacy_published_digest,
                            "versioned_published_digest": versioned_published_digest,
                        },
                        ensure_ascii=False,
                        sort_keys=True,
                    ),
                ),
            )

    @staticmethod
    def approve_price_version(version_id, expected_row_version, payload, db):
        cursor = db.execute(
            """
            UPDATE route_price_versions SET status='approved',approved_by=?,approved_by_name=?,
                   approved_at=datetime('now','localtime'),row_version=row_version+1
            WHERE id=? AND status='draft' AND row_version=?
            """,
            (payload.get("approved_by"), payload.get("approved_by_name", ""), version_id, expected_row_version),
        )
        if cursor.rowcount != 1:
            raise PayrollConflictError("工价版本状态已变化，请刷新")

    @staticmethod
    def close_prior_price_version(
        version_id, route_version_id, process_version_id, valid_to, db
    ):
        db.execute(
            """
            UPDATE route_price_versions SET valid_to=?,row_version=row_version+1
            WHERE id<>? AND route_version_id=? AND process_version_id=?
              AND status='approved'
              AND COALESCE(valid_to,'')='' AND valid_from<?
            """, (
                valid_to,
                version_id,
                route_version_id,
                process_version_id,
                valid_to,
            )
        )

    @staticmethod
    def price_version_references(version_id, db=None):
        db = resolve_db(db)
        return int(db.execute(
            "SELECT (SELECT COUNT(*) FROM payroll_detail_lines WHERE price_version_id=?) + "
            "(SELECT COUNT(*) FROM payroll_work_price_resolutions WHERE price_version_id=?)", (version_id, version_id)
        ).fetchone()[0])
