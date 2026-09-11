"""V083 controlled repair evidence for historical exact price bindings."""

from modules.migration_helpers import add_column_if_missing
from modules.migration_process_versioning_v062 import (
    PRICE_VERSION_MUTATION_TRIGGERS,
    _create_price_binding_triggers,
)


def _create_repair_tables(db):
    db.execute(
        """
        CREATE TABLE IF NOT EXISTS historical_price_binding_repair_runs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            idempotency_key TEXT NOT NULL UNIQUE,
            manifest_digest TEXT NOT NULL UNIQUE,
            status TEXT NOT NULL CHECK(status IN ('approved','partially_applied','applied')),
            operator_id INTEGER NOT NULL,
            operator_name TEXT NOT NULL,
            approver_id INTEGER NOT NULL,
            approver_name TEXT NOT NULL,
            approved_at TEXT NOT NULL,
            reason TEXT NOT NULL,
            source_user_version INTEGER NOT NULL,
            target_user_version INTEGER NOT NULL,
            before_summary_json TEXT NOT NULL DEFAULT '{}',
            after_summary_json TEXT NOT NULL DEFAULT '{}',
            manifest_json TEXT NOT NULL,
            created_at TEXT NOT NULL DEFAULT (datetime('now','localtime')),
            applied_at TEXT NOT NULL DEFAULT '',
            CHECK(operator_id <> approver_id),
            CHECK(length(trim(operator_name)) > 0),
            CHECK(length(trim(approver_name)) > 0),
            CHECK(length(trim(reason)) > 0)
        )
        """
    )
    db.execute(
        """
        CREATE TABLE IF NOT EXISTS historical_price_binding_repair_items (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            run_id INTEGER NOT NULL,
            item_key TEXT NOT NULL UNIQUE,
            action TEXT NOT NULL CHECK(action IN ('clone','manual')),
            source_price_version_id INTEGER,
            target_route_id INTEGER NOT NULL,
            target_route_version_id INTEGER NOT NULL,
            target_process_id INTEGER NOT NULL,
            target_process_version_id INTEGER NOT NULL,
            normal_unit_price_micros INTEGER CHECK(normal_unit_price_micros IS NULL OR normal_unit_price_micros >= 0),
            rework_rate_basis_points INTEGER DEFAULT 0
                CHECK(rework_rate_basis_points IS NULL OR rework_rate_basis_points BETWEEN 0 AND 10000),
            rework_rate_configured INTEGER
                CHECK(rework_rate_configured IS NULL OR rework_rate_configured IN (0,1)),
            valid_from TEXT,
            valid_to TEXT,
            target_route_content_digest TEXT NOT NULL,
            target_process_content_digest TEXT NOT NULL,
            affected_work_record_count INTEGER NOT NULL DEFAULT 0,
            affected_quantity INTEGER NOT NULL DEFAULT 0,
            affected_work_record_digest TEXT NOT NULL,
            manual_decision_reason TEXT NOT NULL DEFAULT '',
            manual_decision_by INTEGER,
            manual_decision_at TEXT NOT NULL DEFAULT '',
            manual_parent_item_key TEXT NOT NULL DEFAULT '',
            target_price_version_id INTEGER UNIQUE,
            created_at TEXT NOT NULL DEFAULT (datetime('now','localtime')),
            applied_at TEXT NOT NULL DEFAULT '',
            FOREIGN KEY(run_id) REFERENCES historical_price_binding_repair_runs(id)
                ON DELETE RESTRICT,
            FOREIGN KEY(source_price_version_id) REFERENCES route_price_versions(id)
                ON DELETE RESTRICT,
            FOREIGN KEY(target_route_version_id) REFERENCES process_route_versions(id)
                ON DELETE RESTRICT,
            FOREIGN KEY(target_process_version_id) REFERENCES process_versions(id)
                ON DELETE RESTRICT,
            FOREIGN KEY(target_price_version_id) REFERENCES route_price_versions(id)
                ON DELETE RESTRICT,
            CHECK(
                (action='clone' AND source_price_version_id IS NOT NULL
                 AND normal_unit_price_micros IS NOT NULL
                 AND rework_rate_basis_points IS NOT NULL
                 AND rework_rate_configured IS NOT NULL
                 AND valid_from IS NOT NULL)
                OR (action='manual' AND source_price_version_id IS NULL
                    AND ((normal_unit_price_micros IS NULL
                          AND rework_rate_basis_points IS NULL
                          AND rework_rate_configured IS NULL
                          AND valid_from IS NULL)
                         OR (normal_unit_price_micros IS NOT NULL
                             AND rework_rate_basis_points IS NOT NULL
                             AND rework_rate_configured IS NOT NULL
                             AND valid_from IS NOT NULL)))
            ),
            CHECK(action='manual' OR COALESCE(valid_to,'')='' OR valid_to>valid_from),
            CHECK(action='clone' OR (
                (normal_unit_price_micros IS NULL AND rework_rate_basis_points IS NULL
                 AND rework_rate_configured IS NULL AND valid_from IS NULL
                 AND length(trim(manual_decision_reason))=0
                 AND manual_decision_by IS NULL AND length(trim(manual_decision_at))=0)
                OR
                (normal_unit_price_micros IS NOT NULL AND rework_rate_basis_points IS NOT NULL
                 AND rework_rate_configured IS NOT NULL AND valid_from IS NOT NULL
                 AND length(trim(manual_decision_reason))>0
                 AND manual_decision_by IS NOT NULL AND length(trim(manual_decision_at))>0
                 AND length(trim(manual_parent_item_key))>0)
            ))
        )
        """
    )
    db.execute(
        "CREATE INDEX IF NOT EXISTS idx_historical_price_repair_items_run "
        "ON historical_price_binding_repair_items(run_id,id)"
    )
    db.execute(
        "CREATE INDEX IF NOT EXISTS idx_historical_price_repair_items_target "
        "ON historical_price_binding_repair_items("
        "target_route_version_id,target_process_version_id,valid_from,valid_to)"
    )
    # V083.1: keep the business meaning of a zero-price decision separate from
    # an explicit no-settlement decision.  The original V083 repair-item
    # constraints intentionally remain unchanged; this additive column lets
    # an approved parent item be resolved without fabricating a price row.
    add_column_if_missing(
        db,
        "historical_price_binding_repair_items",
        "settlement_decision",
        "TEXT NOT NULL DEFAULT 'settle'",
    )
    db.execute(
        """
        CREATE TABLE IF NOT EXISTS historical_price_binding_settlements (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            repair_item_id INTEGER NOT NULL UNIQUE,
            decision TEXT NOT NULL CHECK(decision IN ('zero_price','no_settlement')),
            price_version_id INTEGER UNIQUE,
            reason TEXT NOT NULL,
            decided_by INTEGER NOT NULL,
            decided_by_name TEXT NOT NULL,
            decided_at TEXT NOT NULL,
            idempotency_key TEXT NOT NULL UNIQUE,
            evidence_digest TEXT NOT NULL,
            created_at TEXT NOT NULL DEFAULT (datetime('now','localtime')),
            FOREIGN KEY(repair_item_id) REFERENCES historical_price_binding_repair_items(id)
                ON DELETE RESTRICT,
            FOREIGN KEY(price_version_id) REFERENCES route_price_versions(id)
                ON DELETE RESTRICT,
            FOREIGN KEY(decided_by) REFERENCES users(id) ON DELETE RESTRICT,
            CHECK(length(trim(reason)) >= 2),
            CHECK(length(trim(decided_by_name)) > 0),
            CHECK(length(trim(decided_at)) > 0),
            CHECK(length(trim(idempotency_key)) > 0),
            CHECK(length(trim(evidence_digest)) > 0),
            CHECK((decision='no_settlement' AND price_version_id IS NULL)
                  OR (decision='zero_price' AND price_version_id IS NOT NULL))
        )
        """
    )
    db.execute(
        """
        CREATE TABLE IF NOT EXISTS historical_price_binding_settlement_facts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            settlement_id INTEGER NOT NULL,
            work_record_id INTEGER NOT NULL UNIQUE,
            quantity INTEGER NOT NULL,
            created_at TEXT NOT NULL,
            snapshot_json TEXT NOT NULL DEFAULT '{}',
            FOREIGN KEY(settlement_id) REFERENCES historical_price_binding_settlements(id)
                ON DELETE RESTRICT,
            FOREIGN KEY(work_record_id) REFERENCES work_records(id) ON DELETE RESTRICT,
            CHECK(quantity > 0),
            CHECK(length(trim(created_at)) > 0)
        )
        """
    )
    db.execute(
        "CREATE INDEX IF NOT EXISTS idx_historical_price_settlement_fact_settlement "
        "ON historical_price_binding_settlement_facts(settlement_id,work_record_id)"
    )
    for name in (
        "protect_historical_price_binding_settlement",
        "protect_historical_price_binding_settlement_delete",
        "protect_historical_price_binding_settlement_fact",
        "protect_historical_price_binding_settlement_fact_delete",
    ):
        db.execute(f"DROP TRIGGER IF EXISTS {name}")
    db.execute(
        """
        CREATE TRIGGER protect_historical_price_binding_settlement
        BEFORE UPDATE ON historical_price_binding_settlements
        BEGIN SELECT RAISE(ABORT,'historical settlement decision is immutable'); END
        """
    )
    db.execute(
        """
        CREATE TRIGGER protect_historical_price_binding_settlement_delete
        BEFORE DELETE ON historical_price_binding_settlements
        BEGIN SELECT RAISE(ABORT,'historical settlement decision cannot be deleted'); END
        """
    )
    db.execute(
        """
        CREATE TRIGGER protect_historical_price_binding_settlement_fact
        BEFORE UPDATE ON historical_price_binding_settlement_facts
        BEGIN SELECT RAISE(ABORT,'historical settlement fact is immutable'); END
        """
    )
    db.execute(
        """
        CREATE TRIGGER protect_historical_price_binding_settlement_fact_delete
        BEFORE DELETE ON historical_price_binding_settlement_facts
        BEGIN SELECT RAISE(ABORT,'historical settlement fact cannot be deleted'); END
        """
    )
    # A manual item is an evidence record, not an operator-facing identifier.
    # Keep the editable proposal in its own append-only workflow table so a
    # price preparer can use a readable business screen without mutating the
    # original preflight item or bypassing the independent approval gate.
    db.execute(
        """
        CREATE TABLE IF NOT EXISTS historical_price_manual_price_drafts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            repair_item_id INTEGER NOT NULL,
            status TEXT NOT NULL CHECK(status IN ('draft','approved','voided')),
            normal_unit_price_micros INTEGER NOT NULL CHECK(normal_unit_price_micros > 0),
            rework_rate_basis_points INTEGER NOT NULL DEFAULT 0
                CHECK(rework_rate_basis_points BETWEEN 0 AND 10000),
            rework_rate_configured INTEGER NOT NULL DEFAULT 0
                CHECK(rework_rate_configured IN (0,1)),
            valid_from TEXT NOT NULL,
            valid_to TEXT,
            confirmation_reason TEXT NOT NULL,
            created_by INTEGER NOT NULL,
            created_by_name TEXT NOT NULL,
            created_at TEXT NOT NULL DEFAULT (datetime('now','localtime')),
            approved_by INTEGER,
            approved_by_name TEXT NOT NULL DEFAULT '',
            approved_at TEXT NOT NULL DEFAULT '',
            voided_by INTEGER,
            voided_by_name TEXT NOT NULL DEFAULT '',
            voided_at TEXT NOT NULL DEFAULT '',
            void_reason TEXT NOT NULL DEFAULT '',
            row_version INTEGER NOT NULL DEFAULT 0,
            idempotency_key TEXT NOT NULL UNIQUE,
            request_digest TEXT NOT NULL,
            price_version_id INTEGER UNIQUE,
            FOREIGN KEY(repair_item_id) REFERENCES historical_price_binding_repair_items(id)
                ON DELETE RESTRICT,
            FOREIGN KEY(created_by) REFERENCES users(id) ON DELETE RESTRICT,
            FOREIGN KEY(approved_by) REFERENCES users(id) ON DELETE RESTRICT,
            FOREIGN KEY(voided_by) REFERENCES users(id) ON DELETE RESTRICT,
            FOREIGN KEY(price_version_id) REFERENCES route_price_versions(id)
                ON DELETE RESTRICT,
            CHECK(COALESCE(valid_to,'')='' OR valid_to>valid_from),
            CHECK(length(trim(confirmation_reason)) >= 2),
            CHECK(length(trim(created_by_name)) > 0),
            CHECK(
                (status='draft' AND approved_by IS NULL AND length(trim(approved_at))=0
                 AND voided_by IS NULL AND length(trim(voided_at))=0
                 AND price_version_id IS NULL)
                OR
                (status='approved' AND approved_by IS NOT NULL
                 AND length(trim(approved_by_name))>0 AND length(trim(approved_at))>0
                 AND price_version_id IS NOT NULL AND voided_by IS NULL)
                OR
                (status='voided' AND voided_by IS NOT NULL
                 AND length(trim(voided_by_name))>0 AND length(trim(voided_at))>0
                 AND length(trim(void_reason))>=2 AND approved_by IS NULL
                 AND price_version_id IS NULL)
            )
        )
        """
    )
    db.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS idx_historical_manual_price_one_open_draft "
        "ON historical_price_manual_price_drafts(repair_item_id) WHERE status='draft'"
    )
    db.execute(
        "CREATE INDEX IF NOT EXISTS idx_historical_manual_price_draft_item "
        "ON historical_price_manual_price_drafts(repair_item_id,id DESC)"
    )


def _add_price_repair_reference(db):
    add_column_if_missing(
        db,
        "route_price_versions",
        "historical_price_repair_item_id",
        "INTEGER REFERENCES historical_price_binding_repair_items(id) ON DELETE RESTRICT",
    )
    # These columns were introduced nullable so manual items can remain an
    # explicit, unpriced exception until a human supplies a decision.
    add_column_if_missing(
        db, "historical_price_binding_repair_items", "manual_decision_reason",
        "TEXT NOT NULL DEFAULT ''",
    )
    add_column_if_missing(
        db, "historical_price_binding_repair_items", "manual_decision_by",
        "INTEGER",
    )
    add_column_if_missing(
        db, "historical_price_binding_repair_items", "manual_decision_at",
        "TEXT NOT NULL DEFAULT ''",
    )
    add_column_if_missing(
        db, "historical_price_binding_repair_items", "manual_parent_item_key",
        "TEXT NOT NULL DEFAULT ''",
    )
    db.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS idx_price_historical_repair_item "
        "ON route_price_versions(historical_price_repair_item_id) "
        "WHERE historical_price_repair_item_id IS NOT NULL"
    )


def _create_repair_guards(db):
    for name in (*PRICE_VERSION_MUTATION_TRIGGERS,
        "validate_historical_price_repair_insert",
        "validate_historical_price_repair_update",
        "protect_applied_historical_price_repair_run",
        "protect_applied_historical_price_repair_run_delete",
        "protect_applied_historical_price_repair_item",
        "protect_applied_historical_price_repair_item_delete",
        "protect_historical_manual_price_draft",
        "protect_historical_manual_price_draft_delete",
    ):
        db.execute(f"DROP TRIGGER IF EXISTS {name}")

    # Re-install the complete V062/V074 trigger set first.  V083 then narrows
    # only the approval gate for an explicitly authorized historical clone.
    # This prevents the repair migration from accidentally dropping overlap,
    # binding, immutability, or legacy-payroll protections.
    _create_price_binding_triggers(db)
    for name in ("validate_approved_price_version_insert", "validate_approved_price_version_update",
                 "prevent_price_version_overlap_insert", "prevent_price_version_overlap_update",
                 "protect_approved_price_version"):
        db.execute(f"DROP TRIGGER IF EXISTS {name}")

    historical_authorization = """
        EXISTS (
            SELECT 1
            FROM historical_price_binding_repair_items item
            JOIN historical_price_binding_repair_runs run ON run.id=item.run_id
            JOIN process_route_versions route_version
              ON route_version.id=item.target_route_version_id
            JOIN process_versions process_version
              ON process_version.id=item.target_process_version_id
            WHERE item.id=NEW.historical_price_repair_item_id
              AND run.status IN ('approved','partially_applied','applied')
              AND run.operator_id<>run.approver_id
              AND route_version.status='superseded'
              AND process_version.status='published'
              AND item.target_route_id=NEW.route_id
              AND item.target_route_version_id=NEW.route_version_id
              AND item.target_process_id=NEW.process_id
              AND item.target_process_version_id=NEW.process_version_id
              AND item.normal_unit_price_micros=NEW.normal_unit_price_micros
              AND item.rework_rate_basis_points=NEW.rework_rate_basis_points
              AND item.rework_rate_configured=NEW.rework_rate_configured
              AND item.valid_from=NEW.valid_from
              AND COALESCE(item.valid_to,'')=COALESCE(NEW.valid_to,'')
              AND item.target_route_content_digest=route_version.content_digest
              AND item.target_process_content_digest=process_version.content_digest
        )
    """
    normal_authorization = """
        EXISTS (
            SELECT 1 FROM process_route_versions route_version
            JOIN process_versions process_version
              ON process_version.id=NEW.process_version_id
            WHERE route_version.id=NEW.route_version_id
              AND route_version.status='published'
              AND process_version.status='published'
        )
    """
    insert_historical_authorization = historical_authorization.replace(
        "AND run.status IN ('approved','partially_applied','applied')",
        "AND run.status IN ('approved','partially_applied')\n              AND item.target_price_version_id IS NULL",
    )
    db.execute(
        """
        CREATE TRIGGER prevent_price_version_overlap_insert
        BEFORE INSERT ON route_price_versions
        WHEN NEW.status='approved' AND EXISTS (
            SELECT 1 FROM route_price_versions current
            WHERE current.route_version_id=NEW.route_version_id
              AND current.process_version_id=NEW.process_version_id
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
            WHERE current.id<>NEW.id
              AND current.route_version_id=NEW.route_version_id
              AND current.process_version_id=NEW.process_version_id
              AND current.status='approved'
              AND COALESCE(current.valid_to,'9999-12-31 23:59:59') > NEW.valid_from
              AND COALESCE(NEW.valid_to,'9999-12-31 23:59:59') > current.valid_from
        )
        BEGIN SELECT RAISE(ABORT,'approved price version intervals overlap'); END
        """
    )
    db.execute(
        f"""
        CREATE TRIGGER validate_approved_price_version_insert
        BEFORE INSERT ON route_price_versions
        WHEN NEW.status='approved' AND NOT (
            ({normal_authorization}) OR ({insert_historical_authorization})
        )
        BEGIN SELECT RAISE(ABORT,'approved price requires published versions or approved historical repair'); END
        """
    )
    db.execute(
        f"""
        CREATE TRIGGER validate_approved_price_version_update
        BEFORE UPDATE OF status ON route_price_versions
        WHEN OLD.status<>'approved' AND NEW.status='approved' AND NOT (
            ({normal_authorization}) OR ({historical_authorization})
        )
        BEGIN SELECT RAISE(ABORT,'approved price requires published versions or approved historical repair'); END
        """
    )
    db.execute(
        """
        CREATE TRIGGER protect_approved_price_version
        BEFORE UPDATE ON route_price_versions
        WHEN OLD.status IN ('approved','retired') AND NOT (
            OLD.status='approved' AND NEW.status='approved'
            AND OLD.route_id=NEW.route_id AND OLD.process_id=NEW.process_id
            AND OLD.route_version_id=NEW.route_version_id
            AND OLD.process_version_id=NEW.process_version_id
            AND OLD.normal_unit_price_micros=NEW.normal_unit_price_micros
            AND OLD.rework_rate_basis_points=NEW.rework_rate_basis_points
            AND OLD.rework_rate_configured=NEW.rework_rate_configured
            AND OLD.valid_from=NEW.valid_from
            AND COALESCE(OLD.valid_to,'')=''
            AND COALESCE(NEW.valid_to,'')<>''
        )
        BEGIN SELECT RAISE(ABORT,'approved price versions are immutable'); END
        """
    )
    # Reference-specific guards are separate from the approval-policy gate so
    # all historical repair fields must remain tied to one authorized item.
    db.execute(
        """
        CREATE TRIGGER validate_historical_price_repair_insert
        BEFORE INSERT ON route_price_versions
        WHEN NEW.historical_price_repair_item_id IS NOT NULL AND NOT EXISTS (
            SELECT 1
            FROM historical_price_binding_repair_items item
            JOIN historical_price_binding_repair_runs run ON run.id=item.run_id
            WHERE item.id=NEW.historical_price_repair_item_id
              AND run.status IN ('approved','partially_applied')
              AND item.target_price_version_id IS NULL
              AND item.target_route_id=NEW.route_id
              AND item.target_route_version_id=NEW.route_version_id
              AND item.target_process_id=NEW.process_id
              AND item.target_process_version_id=NEW.process_version_id
              AND item.normal_unit_price_micros=NEW.normal_unit_price_micros
              AND item.rework_rate_basis_points=NEW.rework_rate_basis_points
              AND item.rework_rate_configured=NEW.rework_rate_configured
              AND item.valid_from=NEW.valid_from
              AND COALESCE(item.valid_to,'')=COALESCE(NEW.valid_to,'')
        )
        BEGIN SELECT RAISE(ABORT,'historical price repair reference is invalid'); END
        """
    )
    db.execute(
        """
        CREATE TRIGGER validate_historical_price_repair_update
        BEFORE UPDATE OF historical_price_repair_item_id ON route_price_versions
        WHEN COALESCE(OLD.historical_price_repair_item_id,0)
             <>COALESCE(NEW.historical_price_repair_item_id,0)
        BEGIN SELECT RAISE(ABORT,'historical price repair reference is immutable'); END
        """
    )
    db.execute(
        """
        CREATE TRIGGER protect_applied_historical_price_repair_run
        BEFORE UPDATE ON historical_price_binding_repair_runs
        WHEN OLD.status='applied'
        BEGIN SELECT RAISE(ABORT,'applied historical price repair run is immutable'); END
        """
    )
    db.execute(
        """
        CREATE TRIGGER protect_applied_historical_price_repair_run_delete
        BEFORE DELETE ON historical_price_binding_repair_runs
        BEGIN SELECT RAISE(ABORT,'historical price repair run cannot be deleted'); END
        """
    )
    db.execute(
        """
        CREATE TRIGGER protect_applied_historical_price_repair_item
        BEFORE UPDATE ON historical_price_binding_repair_items
        WHEN EXISTS (
            SELECT 1 FROM historical_price_binding_repair_runs run
            WHERE run.id=OLD.run_id AND run.status='applied'
        )
        BEGIN SELECT RAISE(ABORT,'applied historical price repair item is immutable'); END
        """
    )
    db.execute(
        """
        CREATE TRIGGER protect_applied_historical_price_repair_item_delete
        BEFORE DELETE ON historical_price_binding_repair_items
        BEGIN SELECT RAISE(ABORT,'historical price repair item cannot be deleted'); END
        """
    )
    db.execute(
        """
        CREATE TRIGGER protect_historical_manual_price_draft
        BEFORE UPDATE ON historical_price_manual_price_drafts
        WHEN OLD.status IN ('approved','voided')
        BEGIN SELECT RAISE(ABORT,'historical manual price decision is immutable'); END
        """
    )
    db.execute(
        """
        CREATE TRIGGER protect_historical_manual_price_draft_delete
        BEFORE DELETE ON historical_price_manual_price_drafts
        BEGIN SELECT RAISE(ABORT,'historical manual price decision cannot be deleted'); END
        """
    )


def m083_historical_price_binding_repair_evidence(db):
    """Install fail-closed evidence and authorization gates for price repair."""
    _create_repair_tables(db)
    _add_price_repair_reference(db)
    _create_repair_guards(db)


MIGRATIONS = [
    (
        83,
        "Add controlled historical exact-price binding repair evidence",
        m083_historical_price_binding_repair_evidence,
    )
]
