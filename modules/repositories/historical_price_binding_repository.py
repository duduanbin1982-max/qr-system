"""SQL persistence for controlled historical exact-price confirmations."""

from modules.repositories.context import resolve_db


class HistoricalPriceBindingRepository:
    """Database access for the V083 historical-price repair workflow."""

    @staticmethod
    def parent_item(review_id, db=None, *, include_resolved=False):
        db = resolve_db(db)
        conditions = [
            "item.id=?",
            "item.action='manual'",
            "COALESCE(item.manual_parent_item_key,'')=''",
        ]
        if not include_resolved:
            conditions.append("item.target_price_version_id IS NULL")
        row = db.execute(
            "SELECT item.*,run.id AS source_run_id,run.status AS source_run_status,"
            "run.manifest_json AS source_manifest_json "
            "FROM historical_price_binding_repair_items item "
            "JOIN historical_price_binding_repair_runs run ON run.id=item.run_id "
            "WHERE " + " AND ".join(conditions),
            (int(review_id),),
        ).fetchone()
        return dict(row) if row else None

    @staticmethod
    def current_fact_rows(item, db=None):
        db = resolve_db(db)
        rows = db.execute(
            """
            SELECT wr.id AS work_record_id,o.id AS order_id,o.order_no,
                   COALESCE(o.product_code,'') AS product_code,
                   COALESCE(o.product_name,'') AS product_name,
                   COALESCE(wr.route_id,o.route_id) AS route_id,wr.route_version_id,
                   wr.process_id,wr.process_version_id,wr.quantity,wr.created_at
            FROM work_records wr
            JOIN orders o ON o.id=wr.order_id
            WHERE wr.status='approved' AND wr.type='normal'
              AND COALESCE(wr.route_id,o.route_id)=?
              AND wr.route_version_id=?
              AND wr.process_id=? AND wr.process_version_id=?
              AND NOT EXISTS (
                SELECT 1 FROM route_price_versions price
                WHERE price.route_version_id=wr.route_version_id
                  AND price.process_version_id=wr.process_version_id
                  AND price.status='approved'
                  AND price.valid_from<=wr.created_at
                  AND (COALESCE(price.valid_to,'')='' OR price.valid_to>wr.created_at)
              )
            ORDER BY wr.id
            """,
            (
                item["target_route_id"], item["target_route_version_id"],
                item["target_process_id"], item["target_process_version_id"],
            ),
        ).fetchall()
        return [dict(row) for row in rows]

    @staticmethod
    def candidates(item, db=None):
        db = resolve_db(db)
        rows = db.execute(
            """
            SELECT price.normal_unit_price_micros,price.rework_rate_basis_points,
                   price.rework_rate_configured,price.valid_from,price.valid_to,
                   COALESCE(route_version.name,route.name,'') AS route_name,
                   route_version.version AS route_version,
                   COALESCE(process_version.name,process.name,'') AS process_name,
                   process_version.version AS process_version
            FROM route_price_versions price
            LEFT JOIN process_routes route ON route.id=price.route_id
            LEFT JOIN process_route_versions route_version ON route_version.id=price.route_version_id
            LEFT JOIN processes process ON process.id=price.process_id
            LEFT JOIN process_versions process_version ON process_version.id=price.process_version_id
            WHERE price.route_id=? AND price.process_id=? AND price.status='approved'
            ORDER BY price.valid_from DESC,price.id DESC
            """,
            (item["target_route_id"], item["target_process_id"]),
        ).fetchall()
        return [dict(row) for row in rows]

    @staticmethod
    def drafts(review_id, db=None):
        db = resolve_db(db)
        rows = db.execute(
            """
            SELECT id,status,normal_unit_price_micros,rework_rate_basis_points,
                   rework_rate_configured,valid_from,valid_to,confirmation_reason,
                   created_by,created_by_name,created_at,approved_by,approved_by_name,
                   approved_at,voided_by,voided_by_name,voided_at,void_reason,row_version,
                   price_version_id
            FROM historical_price_manual_price_drafts
            WHERE repair_item_id=? ORDER BY id DESC
            """,
            (int(review_id),),
        ).fetchall()
        return [dict(row) for row in rows]

    @staticmethod
    def route_version(route_version_id, db=None):
        db = resolve_db(db)
        row = db.execute(
            "SELECT name,version,category FROM process_route_versions WHERE id=?",
            (int(route_version_id),),
        ).fetchone()
        return dict(row) if row else None

    @staticmethod
    def process_version(process_version_id, db=None):
        db = resolve_db(db)
        row = db.execute(
            "SELECT name,version FROM process_versions WHERE id=?",
            (int(process_version_id),),
        ).fetchone()
        return dict(row) if row else None

    @staticmethod
    def list_manual_items(db=None):
        db = resolve_db(db)
        rows = db.execute(
            """
            SELECT item.*,run.status AS source_run_status,run.manifest_json AS source_manifest_json
            FROM historical_price_binding_repair_items item
            JOIN historical_price_binding_repair_runs run ON run.id=item.run_id
            WHERE item.action='manual'
              AND COALESCE(item.manual_parent_item_key,'')=''
              AND item.target_price_version_id IS NULL
              AND run.status IN ('partially_applied','applied')
            ORDER BY item.id
            """
        ).fetchall()
        return [dict(row) for row in rows]

    @staticmethod
    def draft_by_idempotency(key, db=None):
        db = resolve_db(db)
        row = db.execute(
            "SELECT * FROM historical_price_manual_price_drafts WHERE idempotency_key=?",
            (key,),
        ).fetchone()
        return dict(row) if row else None

    @staticmethod
    def open_draft(review_id, db=None):
        db = resolve_db(db)
        row = db.execute(
            "SELECT id FROM historical_price_manual_price_drafts "
            "WHERE repair_item_id=? AND status='draft'",
            (int(review_id),),
        ).fetchone()
        return dict(row) if row else None

    @staticmethod
    def insert_draft(values, actor_id, actor_name, db=None):
        db = resolve_db(db)
        cursor = db.execute(
            """
            INSERT INTO historical_price_manual_price_drafts (
                repair_item_id,status,normal_unit_price_micros,rework_rate_basis_points,
                rework_rate_configured,valid_from,valid_to,confirmation_reason,
                created_by,created_by_name,idempotency_key,request_digest
            ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)
            """,
            (
                values["repair_item_id"], "draft", values["normal_unit_price_micros"],
                values["rework_rate_basis_points"], values["rework_rate_configured"],
                values["valid_from"], values["valid_to"], values["confirmation_reason"],
                actor_id, actor_name, values["idempotency_key"], values["request_digest"],
            ),
        )
        return int(cursor.lastrowid)

    @staticmethod
    def draft(draft_id, db=None):
        db = resolve_db(db)
        row = db.execute(
            "SELECT * FROM historical_price_manual_price_drafts WHERE id=?",
            (int(draft_id),),
        ).fetchone()
        return dict(row) if row else None

    @staticmethod
    def void_draft(draft_id, actor_id, actor_name, now, reason, expected_row_version, db=None):
        db = resolve_db(db)
        cursor = db.execute(
            """
            UPDATE historical_price_manual_price_drafts
            SET status='voided',voided_by=?,voided_by_name=?,voided_at=?,
                void_reason=?,row_version=row_version+1
            WHERE id=? AND status='draft' AND row_version=?
            """,
            (actor_id, actor_name, now, reason, int(draft_id), expected_row_version),
        )
        return cursor.rowcount

    @staticmethod
    def overlap(item, draft, db=None):
        db = resolve_db(db)
        row = db.execute(
            """
            SELECT id,valid_from,valid_to FROM route_price_versions
            WHERE route_version_id=? AND process_version_id=? AND status='approved'
              AND COALESCE(valid_to,'9999-12-31 23:59:59')>?
              AND COALESCE(?,'9999-12-31 23:59:59')>valid_from
            ORDER BY id LIMIT 1
            """,
            (
                item["target_route_version_id"], item["target_process_version_id"],
                draft["valid_from"], draft["valid_to"],
            ),
        ).fetchone()
        return dict(row) if row else None

    @staticmethod
    def repair_run_by_idempotency(key, db=None):
        db = resolve_db(db)
        row = db.execute(
            "SELECT * FROM historical_price_binding_repair_runs WHERE idempotency_key=?",
            (key,),
        ).fetchone()
        return dict(row) if row else None

    @staticmethod
    def user_version(db=None):
        db = resolve_db(db)
        return int(db.execute("PRAGMA user_version").fetchone()[0])

    @staticmethod
    def insert_repair_run(payload, db=None):
        db = resolve_db(db)
        cursor = db.execute(
            """
            INSERT INTO historical_price_binding_repair_runs (
                idempotency_key,manifest_digest,status,operator_id,operator_name,
                approver_id,approver_name,approved_at,reason,source_user_version,
                target_user_version,before_summary_json,after_summary_json,manifest_json
            ) VALUES (?,?, 'approved',?,?,?,?,?,?,?,?,?,?,?)
            """,
            (
                payload["idempotency_key"], payload["manifest_digest"],
                payload["operator_id"], payload["operator_name"],
                payload["approver_id"], payload["approver_name"], payload["approved_at"],
                payload["reason"], payload["source_user_version"],
                payload["target_user_version"], payload["before_summary_json"],
                payload["after_summary_json"], payload["manifest_json"],
            ),
        )
        return int(cursor.lastrowid)

    @staticmethod
    def insert_repair_item(payload, db=None):
        db = resolve_db(db)
        cursor = db.execute(
            """
            INSERT INTO historical_price_binding_repair_items (
                run_id,item_key,action,source_price_version_id,target_route_id,
                target_route_version_id,target_process_id,target_process_version_id,
                normal_unit_price_micros,rework_rate_basis_points,rework_rate_configured,
                valid_from,valid_to,target_route_content_digest,target_process_content_digest,
                affected_work_record_count,affected_quantity,affected_work_record_digest,
                manual_decision_reason,manual_decision_by,manual_decision_at,manual_parent_item_key
            ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            """,
            (
                payload["run_id"], payload["item_key"], payload["action"],
                payload.get("source_price_version_id"), payload["target_route_id"],
                payload["target_route_version_id"], payload["target_process_id"],
                payload["target_process_version_id"], payload.get("normal_unit_price_micros"),
                payload.get("rework_rate_basis_points"), payload.get("rework_rate_configured"),
                payload.get("valid_from"), payload.get("valid_to"),
                payload["target_route_content_digest"], payload["target_process_content_digest"],
                payload["affected_work_record_count"], payload["affected_quantity"],
                payload["affected_work_record_digest"], payload.get("manual_decision_reason", ""),
                payload.get("manual_decision_by"), payload.get("manual_decision_at", ""),
                payload.get("manual_parent_item_key", ""),
            ),
        )
        return int(cursor.lastrowid)

    @staticmethod
    def insert_price_version(payload, db=None):
        db = resolve_db(db)
        cursor = db.execute(
            """
            INSERT INTO route_price_versions (
                route_id,route_version_id,process_id,process_version_id,
                normal_unit_price_micros,rework_rate_basis_points,rework_rate_configured,
                valid_from,valid_to,status,created_by,created_by_name,approved_by,
                approved_by_name,approved_at,remark,row_version,legacy_binding_unavailable,
                idempotency_key,request_digest,route_content_digest_snapshot,
                process_content_digest_snapshot,historical_price_repair_item_id
            ) VALUES (?,?,?,?,?,?,?, ?,?,'approved',?,?,?,?,?,?,0,0,?,?,?,?,?)
            """,
            (
                payload["route_id"], payload["route_version_id"], payload["process_id"],
                payload["process_version_id"], payload["normal_unit_price_micros"],
                payload["rework_rate_basis_points"], payload["rework_rate_configured"],
                payload["valid_from"], payload.get("valid_to"), payload["created_by"],
                payload["created_by_name"], payload["approved_by"], payload["approved_by_name"],
                payload["approved_at"], payload["remark"], payload["idempotency_key"],
                payload["request_digest"], payload["route_content_digest_snapshot"],
                payload["process_content_digest_snapshot"], payload["historical_price_repair_item_id"],
            ),
        )
        return int(cursor.lastrowid)

    @staticmethod
    def mark_repair_item_applied(item_id, price_id, now, db=None):
        db = resolve_db(db)
        db.execute(
            "UPDATE historical_price_binding_repair_items SET target_price_version_id=?,applied_at=? WHERE id=?",
            (price_id, now, int(item_id)),
        )

    @staticmethod
    def approve_draft(draft_id, approver_id, approver_name, now, price_id, expected_row_version, db=None):
        db = resolve_db(db)
        cursor = db.execute(
            """
            UPDATE historical_price_manual_price_drafts
            SET status='approved',approved_by=?,approved_by_name=?,approved_at=?,
                price_version_id=?,row_version=row_version+1
            WHERE id=? AND status='draft' AND row_version=?
            """,
            (approver_id, approver_name, now, price_id, int(draft_id), expected_row_version),
        )
        return cursor.rowcount

    @staticmethod
    def mark_repair_run_applied(run_id, after_summary_json, now, db=None):
        db = resolve_db(db)
        db.execute(
            "UPDATE historical_price_binding_repair_runs SET status='applied',after_summary_json=?,applied_at=? "
            "WHERE id=? AND status='approved'",
            (after_summary_json, now, int(run_id)),
        )
