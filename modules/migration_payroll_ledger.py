"""Versioned payroll ledger, price versions, and workflow protections."""

from datetime import datetime
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
import json


def _month_bounds(year_month):
    start = datetime.strptime(year_month, "%Y-%m").replace(day=1, hour=7)
    if start.month == 12:
        end = start.replace(year=start.year + 1, month=1)
    else:
        end = start.replace(month=start.month + 1)
    return start.strftime("%Y-%m-%d %H:%M:%S"), end.strftime("%Y-%m-%d %H:%M:%S")


def _cents(value):
    try:
        return int(Decimal(str(value or 0)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP) * 100)
    except (InvalidOperation, TypeError, ValueError) as exc:
        raise ValueError(f"invalid legacy wage amount: {value}") from exc


def _create_tables(db):
    db.execute(
        """
        CREATE TABLE IF NOT EXISTS route_price_versions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            route_id INTEGER NOT NULL,
            process_id INTEGER NOT NULL,
            normal_unit_price_micros INTEGER NOT NULL CHECK(normal_unit_price_micros >= 0),
            rework_rate_basis_points INTEGER NOT NULL DEFAULT 0
                CHECK(rework_rate_basis_points BETWEEN 0 AND 10000),
            rework_rate_configured INTEGER NOT NULL DEFAULT 0 CHECK(rework_rate_configured IN (0,1)),
            valid_from TEXT NOT NULL,
            valid_to TEXT,
            status TEXT NOT NULL DEFAULT 'draft' CHECK(status IN ('draft','approved','retired')),
            created_by INTEGER,
            created_by_name TEXT NOT NULL DEFAULT '',
            created_at TEXT NOT NULL DEFAULT (datetime('now','localtime')),
            approved_by INTEGER,
            approved_by_name TEXT NOT NULL DEFAULT '',
            approved_at TEXT NOT NULL DEFAULT '',
            remark TEXT NOT NULL DEFAULT '',
            legacy_route_price_id INTEGER,
            row_version INTEGER NOT NULL DEFAULT 0,
            FOREIGN KEY(route_id) REFERENCES process_routes(id) ON DELETE RESTRICT,
            FOREIGN KEY(process_id) REFERENCES processes(id) ON DELETE RESTRICT,
            FOREIGN KEY(created_by) REFERENCES users(id) ON DELETE SET NULL,
            FOREIGN KEY(approved_by) REFERENCES users(id) ON DELETE SET NULL,
            UNIQUE(legacy_route_price_id),
            CHECK(valid_to IS NULL OR valid_to = '' OR valid_to > valid_from)
        )
        """
    )
    db.execute(
        """
        CREATE TABLE IF NOT EXISTS payroll_batches (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            payroll_month TEXT NOT NULL,
            version INTEGER NOT NULL CHECK(version > 0),
            period_start TEXT NOT NULL,
            period_end TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'draft'
                CHECK(status IN ('draft','exceptions_pending','review_pending','locked','confirmed','voided')),
            source_cutoff_at TEXT NOT NULL,
            input_digest TEXT NOT NULL DEFAULT '',
            idempotency_key TEXT NOT NULL DEFAULT '',
            normal_wage_cents INTEGER NOT NULL DEFAULT 0,
            rework_wage_cents INTEGER NOT NULL DEFAULT 0,
            bonus_cents INTEGER NOT NULL DEFAULT 0,
            allowance_cents INTEGER NOT NULL DEFAULT 0,
            deduction_cents INTEGER NOT NULL DEFAULT 0,
            payable_wage_cents INTEGER NOT NULL DEFAULT 0,
            source_record_count INTEGER NOT NULL DEFAULT 0,
            priced_record_count INTEGER NOT NULL DEFAULT 0,
            exception_count INTEGER NOT NULL DEFAULT 0,
            prepared_by INTEGER,
            prepared_by_name TEXT NOT NULL DEFAULT '',
            prepared_at TEXT NOT NULL DEFAULT (datetime('now','localtime')),
            submitted_at TEXT NOT NULL DEFAULT '',
            locked_by INTEGER,
            locked_by_name TEXT NOT NULL DEFAULT '',
            locked_at TEXT NOT NULL DEFAULT '',
            confirmed_by INTEGER,
            confirmed_by_name TEXT NOT NULL DEFAULT '',
            confirmed_at TEXT NOT NULL DEFAULT '',
            voided_by INTEGER,
            voided_by_name TEXT NOT NULL DEFAULT '',
            voided_at TEXT NOT NULL DEFAULT '',
            void_reason TEXT NOT NULL DEFAULT '',
            supersedes_batch_id INTEGER,
            superseded_by_batch_id INTEGER,
            revision_reason TEXT NOT NULL DEFAULT '',
            legacy_imported INTEGER NOT NULL DEFAULT 0 CHECK(legacy_imported IN (0,1)),
            row_version INTEGER NOT NULL DEFAULT 0,
            created_at TEXT NOT NULL DEFAULT (datetime('now','localtime')),
            updated_at TEXT NOT NULL DEFAULT (datetime('now','localtime')),
            FOREIGN KEY(prepared_by) REFERENCES users(id) ON DELETE SET NULL,
            FOREIGN KEY(locked_by) REFERENCES users(id) ON DELETE SET NULL,
            FOREIGN KEY(confirmed_by) REFERENCES users(id) ON DELETE SET NULL,
            FOREIGN KEY(voided_by) REFERENCES users(id) ON DELETE SET NULL,
            FOREIGN KEY(supersedes_batch_id) REFERENCES payroll_batches(id) ON DELETE RESTRICT,
            FOREIGN KEY(superseded_by_batch_id) REFERENCES payroll_batches(id) ON DELETE RESTRICT,
            UNIQUE(payroll_month, version),
            CHECK(period_end > period_start)
        )
        """
    )
    db.execute(
        """
        CREATE TABLE IF NOT EXISTS payroll_employee_lines (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            batch_id INTEGER NOT NULL,
            employee_id INTEGER,
            employee_name_snapshot TEXT NOT NULL,
            employee_no_snapshot TEXT NOT NULL DEFAULT '',
            position_name_snapshot TEXT NOT NULL DEFAULT '',
            normal_quantity INTEGER NOT NULL DEFAULT 0,
            rework_quantity INTEGER NOT NULL DEFAULT 0,
            normal_wage_cents INTEGER NOT NULL DEFAULT 0,
            rework_wage_cents INTEGER NOT NULL DEFAULT 0,
            bonus_cents INTEGER NOT NULL DEFAULT 0,
            allowance_cents INTEGER NOT NULL DEFAULT 0,
            deduction_cents INTEGER NOT NULL DEFAULT 0,
            payable_wage_cents INTEGER NOT NULL DEFAULT 0,
            exception_count INTEGER NOT NULL DEFAULT 0,
            created_at TEXT NOT NULL DEFAULT (datetime('now','localtime')),
            FOREIGN KEY(batch_id) REFERENCES payroll_batches(id) ON DELETE RESTRICT,
            FOREIGN KEY(employee_id) REFERENCES users(id) ON DELETE SET NULL,
            UNIQUE(batch_id, employee_id)
        )
        """
    )
    db.execute(
        """
        CREATE TABLE IF NOT EXISTS payroll_adjustments (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            employee_id INTEGER,
            employee_name_snapshot TEXT NOT NULL,
            employee_no_snapshot TEXT NOT NULL DEFAULT '',
            payroll_month TEXT NOT NULL,
            adjustment_type TEXT NOT NULL CHECK(adjustment_type IN ('bonus','allowance','deduction')),
            amount_cents INTEGER NOT NULL CHECK(amount_cents > 0),
            reason TEXT NOT NULL,
            created_by INTEGER,
            created_by_name TEXT NOT NULL DEFAULT '',
            created_at TEXT NOT NULL DEFAULT (datetime('now','localtime')),
            reversal_of_id INTEGER,
            replacement_for_id INTEGER,
            legacy_wage_adjustment_id INTEGER,
            FOREIGN KEY(employee_id) REFERENCES users(id) ON DELETE SET NULL,
            FOREIGN KEY(created_by) REFERENCES users(id) ON DELETE SET NULL,
            FOREIGN KEY(reversal_of_id) REFERENCES payroll_adjustments(id) ON DELETE RESTRICT,
            FOREIGN KEY(replacement_for_id) REFERENCES payroll_adjustments(id) ON DELETE RESTRICT,
            UNIQUE(reversal_of_id),
            UNIQUE(legacy_wage_adjustment_id)
        )
        """
    )
    db.execute(
        """
        CREATE TABLE IF NOT EXISTS payroll_detail_lines (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            batch_id INTEGER NOT NULL,
            employee_line_id INTEGER NOT NULL,
            source_type TEXT NOT NULL CHECK(source_type IN (
                'normal_work','rework_work','bonus','allowance','deduction','legacy_snapshot'
            )),
            source_id INTEGER NOT NULL,
            work_record_id INTEGER,
            work_recorded_at TEXT NOT NULL DEFAULT '',
            order_id INTEGER,
            order_no_snapshot TEXT NOT NULL DEFAULT '',
            product_code_snapshot TEXT NOT NULL DEFAULT '',
            product_name_snapshot TEXT NOT NULL DEFAULT '',
            route_id INTEGER,
            route_name_snapshot TEXT NOT NULL DEFAULT '',
            process_id INTEGER,
            process_name_snapshot TEXT NOT NULL DEFAULT '',
            quantity INTEGER NOT NULL DEFAULT 0,
            price_version_id INTEGER,
            unit_price_micros INTEGER NOT NULL DEFAULT 0,
            rework_rate_basis_points INTEGER NOT NULL DEFAULT 0,
            amount_cents INTEGER NOT NULL DEFAULT 0,
            resolution_method TEXT NOT NULL DEFAULT '',
            resolution_reason TEXT NOT NULL DEFAULT '',
            resolved_by INTEGER,
            resolved_by_name TEXT NOT NULL DEFAULT '',
            resolved_at TEXT NOT NULL DEFAULT '',
            source_snapshot_json TEXT NOT NULL DEFAULT '{}',
            created_at TEXT NOT NULL DEFAULT (datetime('now','localtime')),
            FOREIGN KEY(batch_id) REFERENCES payroll_batches(id) ON DELETE RESTRICT,
            FOREIGN KEY(employee_line_id) REFERENCES payroll_employee_lines(id) ON DELETE RESTRICT,
            FOREIGN KEY(work_record_id) REFERENCES work_records(id) ON DELETE RESTRICT,
            FOREIGN KEY(price_version_id) REFERENCES route_price_versions(id) ON DELETE RESTRICT,
            FOREIGN KEY(resolved_by) REFERENCES users(id) ON DELETE SET NULL,
            UNIQUE(batch_id, source_type, source_id)
        )
        """
    )
    db.execute(
        """
        CREATE TABLE IF NOT EXISTS payroll_exceptions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            batch_id INTEGER NOT NULL,
            work_record_id INTEGER NOT NULL,
            employee_id INTEGER,
            exception_type TEXT NOT NULL CHECK(exception_type IN (
                'missing_route','missing_price','zero_price','overlapping_price',
                'missing_rework_rate','invalid_amount'
            )),
            snapshot_json TEXT NOT NULL DEFAULT '{}',
            status TEXT NOT NULL DEFAULT 'pending' CHECK(status IN ('pending','proposed','approved','rejected')),
            proposed_price_micros INTEGER,
            proposed_rework_rate_basis_points INTEGER,
            proposed_by INTEGER,
            proposed_by_name TEXT NOT NULL DEFAULT '',
            proposed_at TEXT NOT NULL DEFAULT '',
            approved_by INTEGER,
            approved_by_name TEXT NOT NULL DEFAULT '',
            approved_at TEXT NOT NULL DEFAULT '',
            resolution_reason TEXT NOT NULL DEFAULT '',
            created_at TEXT NOT NULL DEFAULT (datetime('now','localtime')),
            updated_at TEXT NOT NULL DEFAULT (datetime('now','localtime')),
            FOREIGN KEY(batch_id) REFERENCES payroll_batches(id) ON DELETE RESTRICT,
            FOREIGN KEY(work_record_id) REFERENCES work_records(id) ON DELETE RESTRICT,
            FOREIGN KEY(employee_id) REFERENCES users(id) ON DELETE SET NULL,
            FOREIGN KEY(proposed_by) REFERENCES users(id) ON DELETE SET NULL,
            FOREIGN KEY(approved_by) REFERENCES users(id) ON DELETE SET NULL,
            UNIQUE(batch_id, work_record_id, exception_type)
        )
        """
    )
    db.execute(
        """
        CREATE TABLE IF NOT EXISTS payroll_work_price_resolutions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            work_record_id INTEGER NOT NULL UNIQUE,
            price_version_id INTEGER,
            override_unit_price_micros INTEGER CHECK(override_unit_price_micros >= 0),
            override_rework_rate_basis_points INTEGER
                CHECK(override_rework_rate_basis_points BETWEEN 0 AND 10000),
            resolution_method TEXT NOT NULL CHECK(resolution_method IN (
                'current_price_migration','manual_exception_resolution'
            )),
            resolution_reason TEXT NOT NULL,
            policy_code TEXT NOT NULL DEFAULT '',
            resolved_by INTEGER,
            resolved_by_name TEXT NOT NULL DEFAULT '',
            resolved_at TEXT NOT NULL DEFAULT (datetime('now','localtime')),
            FOREIGN KEY(work_record_id) REFERENCES work_records(id) ON DELETE RESTRICT,
            FOREIGN KEY(price_version_id) REFERENCES route_price_versions(id) ON DELETE RESTRICT,
            FOREIGN KEY(resolved_by) REFERENCES users(id) ON DELETE SET NULL,
            CHECK(price_version_id IS NOT NULL OR override_unit_price_micros IS NOT NULL)
        )
        """
    )
    db.execute(
        """
        CREATE TABLE IF NOT EXISTS payroll_events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            batch_id INTEGER,
            event_type TEXT NOT NULL,
            from_status TEXT NOT NULL DEFAULT '',
            to_status TEXT NOT NULL DEFAULT '',
            operator_id INTEGER,
            operator_name TEXT NOT NULL DEFAULT '',
            reason TEXT NOT NULL DEFAULT '',
            payload_json TEXT NOT NULL DEFAULT '{}',
            request_id TEXT NOT NULL DEFAULT '',
            idempotency_key TEXT NOT NULL DEFAULT '',
            created_at TEXT NOT NULL DEFAULT (datetime('now','localtime')),
            FOREIGN KEY(batch_id) REFERENCES payroll_batches(id) ON DELETE RESTRICT,
            FOREIGN KEY(operator_id) REFERENCES users(id) ON DELETE SET NULL
        )
        """
    )
    db.execute(
        """
        CREATE TABLE IF NOT EXISTS payroll_migration_manifests (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            payroll_month TEXT NOT NULL,
            policy_code TEXT NOT NULL,
            period_start TEXT NOT NULL,
            period_end TEXT NOT NULL,
            source_record_count INTEGER NOT NULL CHECK(source_record_count >= 0),
            resolved_record_count INTEGER NOT NULL CHECK(resolved_record_count >= 0),
            unresolved_record_count INTEGER NOT NULL CHECK(unresolved_record_count >= 0),
            records_json TEXT NOT NULL,
            manifest_sha256 TEXT NOT NULL,
            prepared_by INTEGER NOT NULL,
            prepared_by_name TEXT NOT NULL DEFAULT '',
            batch_id INTEGER,
            created_at TEXT NOT NULL DEFAULT (datetime('now','localtime')),
            FOREIGN KEY(prepared_by) REFERENCES users(id) ON DELETE RESTRICT,
            FOREIGN KEY(batch_id) REFERENCES payroll_batches(id) ON DELETE RESTRICT,
            UNIQUE(payroll_month, policy_code),
            UNIQUE(manifest_sha256),
            CHECK(period_end > period_start),
            CHECK(source_record_count = resolved_record_count + unresolved_record_count)
        )
        """
    )
    db.execute(
        """
        CREATE TABLE IF NOT EXISTS payroll_permission_migration_report (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            role_id INTEGER NOT NULL,
            role_code TEXT NOT NULL,
            role_name TEXT NOT NULL,
            old_permissions_json TEXT NOT NULL,
            assigned_user_count INTEGER NOT NULL DEFAULT 0,
            requires_manual_mapping INTEGER NOT NULL DEFAULT 1,
            created_at TEXT NOT NULL DEFAULT (datetime('now','localtime')),
            FOREIGN KEY(role_id) REFERENCES roles(id) ON DELETE RESTRICT,
            UNIQUE(role_id)
        )
        """
    )


def _create_indexes(db):
    statements = (
        "CREATE INDEX IF NOT EXISTS idx_price_versions_lookup ON route_price_versions(route_id,process_id,status,valid_from,valid_to)",
        "CREATE INDEX IF NOT EXISTS idx_payroll_batches_month ON payroll_batches(payroll_month,version DESC)",
        "CREATE UNIQUE INDEX IF NOT EXISTS idx_payroll_batch_idempotency ON payroll_batches(idempotency_key) WHERE idempotency_key<>''",
        "CREATE UNIQUE INDEX IF NOT EXISTS idx_payroll_one_current_confirmed ON payroll_batches(payroll_month) WHERE status='confirmed' AND superseded_by_batch_id IS NULL",
        "CREATE INDEX IF NOT EXISTS idx_payroll_employee_batch ON payroll_employee_lines(batch_id,employee_id)",
        "CREATE INDEX IF NOT EXISTS idx_payroll_detail_batch_employee ON payroll_detail_lines(batch_id,employee_line_id)",
        "CREATE INDEX IF NOT EXISTS idx_payroll_detail_work ON payroll_detail_lines(work_record_id)",
        "CREATE INDEX IF NOT EXISTS idx_payroll_exception_batch_status ON payroll_exceptions(batch_id,status,exception_type)",
        "CREATE INDEX IF NOT EXISTS idx_payroll_adjustment_month_employee ON payroll_adjustments(payroll_month,employee_id,created_at)",
        "CREATE UNIQUE INDEX IF NOT EXISTS idx_payroll_adjustment_legacy ON payroll_adjustments(legacy_wage_adjustment_id) WHERE legacy_wage_adjustment_id IS NOT NULL",
        "CREATE INDEX IF NOT EXISTS idx_payroll_events_batch ON payroll_events(batch_id,created_at,id)",
        "CREATE INDEX IF NOT EXISTS idx_payroll_manifest_batch ON payroll_migration_manifests(batch_id)",
    )
    for statement in statements:
        db.execute(statement)


def _create_triggers(db):
    names = (
        "prevent_price_version_overlap_insert",
        "prevent_price_version_overlap_update",
        "protect_approved_price_version",
        "prevent_referenced_price_version_delete",
        "prevent_payroll_batch_delete",
        "prevent_invalid_payroll_batch_transition",
        "protect_payroll_batch_amounts",
        "protect_payroll_employee_line_update",
        "protect_payroll_employee_line_delete",
        "protect_payroll_detail_update",
        "protect_payroll_detail_delete",
        "protect_payroll_exception_update",
        "protect_payroll_exception_delete",
        "prevent_payroll_adjustment_update",
        "prevent_payroll_adjustment_delete",
        "prevent_payroll_resolution_update",
        "prevent_payroll_resolution_delete",
        "prevent_payroll_event_update",
        "prevent_payroll_event_delete",
        "prevent_payroll_manifest_update",
        "prevent_payroll_manifest_delete",
        "prevent_legacy_route_price_insert",
        "prevent_legacy_route_price_update",
        "prevent_legacy_route_price_delete",
        "prevent_legacy_wage_snapshot_insert",
        "prevent_legacy_wage_snapshot_update",
        "prevent_legacy_wage_snapshot_delete",
        "prevent_legacy_wage_adjustment_insert",
        "prevent_legacy_wage_adjustment_update",
        "prevent_legacy_wage_adjustment_delete",
    )
    for name in names:
        db.execute("DROP TRIGGER IF EXISTS " + name)
    db.execute(
        """
        CREATE TRIGGER prevent_price_version_overlap_insert
        BEFORE INSERT ON route_price_versions
        WHEN NEW.status='approved' AND EXISTS (
            SELECT 1 FROM route_price_versions current
            WHERE current.route_id=NEW.route_id AND current.process_id=NEW.process_id
              AND current.status='approved'
              AND COALESCE(current.valid_to,'9999-12-31 23:59:59') > NEW.valid_from
              AND COALESCE(NEW.valid_to,'9999-12-31 23:59:59') > current.valid_from
        )
        BEGIN SELECT RAISE(ABORT,'approved price version intervals overlap'); END
        """
    )
    db.execute(
        """
        CREATE TRIGGER prevent_price_version_overlap_update
        BEFORE UPDATE ON route_price_versions
        WHEN NEW.status='approved' AND EXISTS (
            SELECT 1 FROM route_price_versions current
            WHERE current.id<>NEW.id AND current.route_id=NEW.route_id AND current.process_id=NEW.process_id
              AND current.status='approved'
              AND COALESCE(current.valid_to,'9999-12-31 23:59:59') > NEW.valid_from
              AND COALESCE(NEW.valid_to,'9999-12-31 23:59:59') > current.valid_from
        )
        BEGIN SELECT RAISE(ABORT,'approved price version intervals overlap'); END
        """
    )
    db.execute(
        """
        CREATE TRIGGER protect_approved_price_version
        BEFORE UPDATE ON route_price_versions
        WHEN OLD.status IN ('approved','retired') AND NOT (
            OLD.status='approved' AND NEW.status='approved'
            AND OLD.route_id=NEW.route_id AND OLD.process_id=NEW.process_id
            AND OLD.normal_unit_price_micros=NEW.normal_unit_price_micros
            AND OLD.rework_rate_basis_points=NEW.rework_rate_basis_points
            AND OLD.rework_rate_configured=NEW.rework_rate_configured
            AND OLD.valid_from=NEW.valid_from
            AND COALESCE(OLD.valid_to,'')='' AND COALESCE(NEW.valid_to,'')<>''
        )
        BEGIN SELECT RAISE(ABORT,'approved price versions are immutable'); END
        """
    )
    db.execute(
        """
        CREATE TRIGGER prevent_referenced_price_version_delete
        BEFORE DELETE ON route_price_versions
        WHEN OLD.status<>'draft' OR EXISTS (
            SELECT 1 FROM payroll_detail_lines WHERE price_version_id=OLD.id
        ) OR EXISTS (
            SELECT 1 FROM payroll_work_price_resolutions WHERE price_version_id=OLD.id
        )
        BEGIN SELECT RAISE(ABORT,'referenced price versions cannot be deleted'); END
        """
    )
    db.execute(
        """
        CREATE TRIGGER prevent_payroll_batch_delete
        BEFORE DELETE ON payroll_batches
        BEGIN SELECT RAISE(ABORT,'payroll batches are auditable and cannot be deleted'); END
        """
    )
    db.execute(
        """
        CREATE TRIGGER prevent_invalid_payroll_batch_transition
        BEFORE UPDATE OF status ON payroll_batches
        WHEN OLD.status<>NEW.status AND NOT (
            (OLD.status='draft' AND NEW.status IN ('exceptions_pending','review_pending','voided')) OR
            (OLD.status='exceptions_pending' AND NEW.status IN ('draft','review_pending','voided')) OR
            (OLD.status='review_pending' AND NEW.status IN ('locked','voided')) OR
            (OLD.status='locked' AND NEW.status IN ('confirmed','voided')) OR
            (OLD.status='confirmed' AND NEW.status='voided')
        )
        BEGIN SELECT RAISE(ABORT,'invalid payroll batch status transition'); END
        """
    )
    db.execute(
        """
        CREATE TRIGGER protect_payroll_batch_amounts
        BEFORE UPDATE OF payroll_month,version,period_start,period_end,source_cutoff_at,input_digest,
            normal_wage_cents,rework_wage_cents,bonus_cents,allowance_cents,deduction_cents,
            payable_wage_cents,source_record_count,priced_record_count,exception_count,prepared_by,prepared_at
        ON payroll_batches
        WHEN OLD.status IN ('locked','confirmed','voided') OR OLD.legacy_imported=1
        BEGIN SELECT RAISE(ABORT,'locked payroll batches are immutable'); END
        """
    )
    for table, update_name, delete_name in (
        ("payroll_employee_lines", "protect_payroll_employee_line_update", "protect_payroll_employee_line_delete"),
        ("payroll_detail_lines", "protect_payroll_detail_update", "protect_payroll_detail_delete"),
        ("payroll_exceptions", "protect_payroll_exception_update", "protect_payroll_exception_delete"),
    ):
        db.execute(
            f"""
            CREATE TRIGGER {update_name}
            BEFORE UPDATE ON {table}
            WHEN (SELECT status FROM payroll_batches WHERE id=OLD.batch_id) IN ('locked','confirmed','voided')
              OR (SELECT legacy_imported FROM payroll_batches WHERE id=OLD.batch_id)=1
            BEGIN SELECT RAISE(ABORT,'locked payroll records are immutable'); END
            """
        )
        db.execute(
            f"""
            CREATE TRIGGER {delete_name}
            BEFORE DELETE ON {table}
            WHEN (SELECT status FROM payroll_batches WHERE id=OLD.batch_id) IN ('locked','confirmed','voided')
              OR (SELECT legacy_imported FROM payroll_batches WHERE id=OLD.batch_id)=1
            BEGIN SELECT RAISE(ABORT,'locked payroll records are immutable'); END
            """
        )
    for table, update_name, delete_name, message in (
        ("payroll_adjustments", "prevent_payroll_adjustment_update", "prevent_payroll_adjustment_delete", "payroll adjustments are immutable"),
        ("payroll_work_price_resolutions", "prevent_payroll_resolution_update", "prevent_payroll_resolution_delete", "payroll price resolutions are immutable"),
        ("payroll_events", "prevent_payroll_event_update", "prevent_payroll_event_delete", "payroll events are immutable"),
        ("payroll_migration_manifests", "prevent_payroll_manifest_update", "prevent_payroll_manifest_delete", "payroll migration manifests are immutable"),
    ):
        db.execute(f"CREATE TRIGGER {update_name} BEFORE UPDATE ON {table} BEGIN SELECT RAISE(ABORT,'{message}'); END")
        db.execute(f"CREATE TRIGGER {delete_name} BEFORE DELETE ON {table} BEGIN SELECT RAISE(ABORT,'{message}'); END")
    for table, label in (
        ("route_prices", "legacy route prices"),
        ("wage_snapshots", "legacy wage snapshots"),
        ("wage_adjustments", "legacy wage adjustments"),
    ):
        for action in ("INSERT", "UPDATE", "DELETE"):
            trigger = f"prevent_legacy_{table.removesuffix('s')}_{action.lower()}"
            db.execute(
                f"CREATE TRIGGER {trigger} BEFORE {action} ON {table} "
                f"BEGIN SELECT RAISE(ABORT,'{label} are read-only after payroll ledger migration'); END"
            )


def _migrate_current_prices(db):
    db.execute(
        """
        INSERT OR IGNORE INTO route_price_versions (
            route_id,process_id,normal_unit_price_micros,rework_rate_basis_points,
            rework_rate_configured,valid_from,status,created_by_name,approved_by_name,
            approved_at,remark,legacy_route_price_id
        )
        SELECT route_id,process_id,CAST(ROUND(COALESCE(unit_price,0)*10000) AS INTEGER),0,0,
               CASE WHEN COALESCE(effective_date,'')='' THEN '1970-01-01 00:00:00'
                    ELSE effective_date||' 00:00:00' END,
               'approved','migration','migration',datetime('now','localtime'),
               'Imported from route_prices; rework rate requires explicit approval',id
        FROM route_prices WHERE status='active'
        """
    )


def _import_legacy_snapshots(db):
    months = db.execute(
        "SELECT DISTINCT year_month FROM wage_snapshots WHERE COALESCE(year_month,'')<>'' ORDER BY year_month"
    ).fetchall()
    for month_row in months:
        month = month_row[0]
        existing = db.execute(
            "SELECT id FROM payroll_batches WHERE payroll_month=? AND legacy_imported=1",
            (month,),
        ).fetchone()
        if existing:
            continue
        snapshots = db.execute(
            "SELECT * FROM wage_snapshots WHERE year_month=? ORDER BY id", (month,)
        ).fetchall()
        if not snapshots:
            continue
        statuses = {row["status"] for row in snapshots}
        status = "confirmed" if "confirmed" in statuses else "locked" if "locked" in statuses else "draft"
        period_start, period_end = _month_bounds(month)
        total_wage = sum(_cents(row["total_wage"]) for row in snapshots)
        rework_wage = sum(_cents(row["rework_wage"]) for row in snapshots)
        normal_wage = total_wage - rework_wage
        cursor = db.execute(
            """
            INSERT INTO payroll_batches (
                payroll_month,version,period_start,period_end,status,source_cutoff_at,input_digest,
                idempotency_key,normal_wage_cents,rework_wage_cents,payable_wage_cents,
                source_record_count,priced_record_count,prepared_by_name,locked_by_name,locked_at,
                confirmed_by_name,confirmed_at,legacy_imported
            ) VALUES (?,?,?,?,?,datetime('now','localtime'),'legacy-wage-snapshots',?,?,?,?,?,?,
                      'legacy import','legacy import',CASE WHEN ? IN ('locked','confirmed') THEN datetime('now','localtime') ELSE '' END,
                      'legacy import',CASE WHEN ?='confirmed' THEN datetime('now','localtime') ELSE '' END,1)
            """,
            (
                month, 1, period_start, period_end, status,
                "legacy:wage_snapshots:" + month, normal_wage, rework_wage, total_wage,
                len(snapshots), len(snapshots), status, status,
            ),
        )
        batch_id = cursor.lastrowid
        for snapshot in snapshots:
            total_cents = _cents(snapshot["total_wage"])
            rework_cents = _cents(snapshot["rework_wage"])
            normal_cents = total_cents - rework_cents
            employee_cursor = db.execute(
                """
                INSERT INTO payroll_employee_lines (
                    batch_id,employee_id,employee_name_snapshot,employee_no_snapshot,
                    normal_quantity,normal_wage_cents,rework_wage_cents,payable_wage_cents
                ) VALUES (?,?,?,?,?,?,?,?)
                """,
                (
                    batch_id, snapshot["employee_id"], snapshot["employee_name"],
                    snapshot["employee_no"] or "", snapshot["total_quantity"] or 0,
                    normal_cents, rework_cents, total_cents,
                ),
            )
            db.execute(
                """
                INSERT INTO payroll_detail_lines (
                    batch_id,employee_line_id,source_type,source_id,quantity,amount_cents,
                    resolution_method,resolution_reason,source_snapshot_json
                ) VALUES (?,?,?,?,?,?,?,?,?)
                """,
                (
                    batch_id, employee_cursor.lastrowid, "legacy_snapshot", snapshot["id"],
                    snapshot["total_quantity"] or 0, total_cents, "legacy_snapshot",
                    "Imported without recalculation; original wage_snapshots row preserved",
                    json.dumps(dict(snapshot), ensure_ascii=False, default=str),
                ),
            )
        db.execute(
            "INSERT INTO payroll_events (batch_id,event_type,to_status,operator_name,reason,payload_json,idempotency_key) VALUES (?,?,?,?,?,?,?)",
            (
                batch_id, "legacy_imported", status, "migration",
                "Imported immutable wage_snapshots as Legacy V1",
                json.dumps({"snapshot_count": len(snapshots), "total_cents": total_wage}),
                "legacy:wage_snapshots:event:" + month,
            ),
        )


def _migrate_legacy_adjustments(db):
    rows = db.execute(
        "SELECT a.*,u.name AS employee_name,u.employee_no "
        "FROM wage_adjustments a LEFT JOIN users u ON u.id=a.user_id ORDER BY a.id"
    ).fetchall()
    imported = 0
    for row in rows:
        reason = str(row["reason"] or "").strip() or "Legacy wage adjustment"
        cursor = db.execute(
            """
            INSERT OR IGNORE INTO payroll_adjustments (
                employee_id,employee_name_snapshot,employee_no_snapshot,payroll_month,
                adjustment_type,amount_cents,reason,created_by_name,created_at,
                legacy_wage_adjustment_id
            ) VALUES (?,?,?,?,?,?,?,?,?,?)
            """,
            (
                row["user_id"], row["employee_name"] or "", row["employee_no"] or "",
                row["year_month"], row["type"], _cents(row["amount"]), reason,
                row["created_by"] or "legacy import", row["created_at"], row["id"],
            ),
        )
        imported += cursor.rowcount
    if imported:
        db.execute(
            "INSERT INTO payroll_events (event_type,operator_name,reason,payload_json,idempotency_key) "
            "VALUES ('legacy_adjustments_imported','migration',?,?,?)",
            (
                "Imported immutable wage_adjustments",
                json.dumps({"adjustment_count": imported}),
                "legacy:wage_adjustments:import",
            ),
        )


def _record_permission_impact(db):
    rows = db.execute(
        "SELECT id,code,name,permissions FROM roles "
        "WHERE permissions LIKE '%wages:view%' OR permissions LIKE '%wages:edit%' "
        "OR permissions LIKE '%prices:edit%'"
    ).fetchall()
    for row in rows:
        count = db.execute(
            "SELECT COUNT(*) FROM user_roles WHERE role_id=?", (row["id"],)
        ).fetchone()[0]
        db.execute(
            """
            INSERT OR IGNORE INTO payroll_permission_migration_report (
                role_id,role_code,role_name,old_permissions_json,assigned_user_count
            ) VALUES (?,?,?,?,?)
            """,
            (row["id"], row["code"], row["name"], row["permissions"] or "[]", count),
        )


def m055_versioned_payroll_ledger(db):
    _create_tables(db)
    _create_indexes(db)
    _migrate_current_prices(db)
    _migrate_legacy_adjustments(db)
    _import_legacy_snapshots(db)
    _record_permission_impact(db)
    _create_triggers(db)


MIGRATIONS = [
    (55, "Add versioned payroll ledger and dual-control workflow", m055_versioned_payroll_ledger),
]
