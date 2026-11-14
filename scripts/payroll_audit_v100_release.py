#!/usr/bin/env python3
"""Validate and execute the reviewed payroll-audit V98->V100 migration."""

import argparse
import hashlib
import json
import os
import shutil
import sqlite3
import subprocess
import sys
import tempfile
from contextlib import closing
from pathlib import Path

from scripts import backend_frontend_static_release as static_release
from scripts import code_only_release, deployment_manifest


BASELINE_COMMIT = "6e04ec0ffec73ada6df20aded7117240bb74ec09"
TARGET_COMMIT = "4c662f8b807a82bcaa298f663d49b39a28823d0f"
SOURCE_SCHEMA = 98
TARGET_SCHEMA = 100
# This complete transition map is the only migration-aware path exception.
MIGRATION_TRANSITIONS = {
    "modules/migration_catalog.py": (
        ("100644", "blob", "4bfeb1afb2b3bda05944a5eee8c66a3ae7b37d43"),
        ("100644", "blob", "4d64ce4dd0e91f2a19c5ca43ab2c6cc9b04f9e9e"),
    ),
    "modules/migration_payroll_audit.py": (
        None,
        ("100644", "blob", "ae8387c6ce5c4cbeb5e1aa9bc139511f3d9fdb43"),
    ),
    "modules/migration_payroll_audit_policy.py": (
        None,
        ("100644", "blob", "16fdfac316c3332a7cfc421a7a9687bc0d2c101b"),
    ),
}
SUPPORT_TRANSITIONS = {
    "frontend/src/composables/wage/usePayrollExceptions.js": (
        ("100644", "blob", "2632ae1bfeb37c2f8606501d991860869044944d"),
        ("100644", "blob", "226ffcba75e73026d68c446a63b59f68286cabf2"),
    ),
    "frontend/src/composables/wage/usePayrollLedger.js": (
        ("100644", "blob", "30e882f3738c4baeac37304f91a96b133963939a"),
        ("100644", "blob", "1d15c6f1455e851e5251c12783c8335ad46fcfd5"),
    ),
    "frontend/src/lib/api/wages.js": (
        ("100644", "blob", "507174b4587f7bf8c028df366d023e6fbd0bfe0c"),
        ("100644", "blob", "f47b5e97f193d5458f69044d0a4d870149d8e13b"),
    ),
    "frontend/src/views/wage/PayrollExceptionsTab.vue": (
        ("100644", "blob", "a5f7ca9d45513b8fed7973ce5f363330dd614276"),
        ("100644", "blob", "1d4b0c904093ac8429c37fcf948a866d42f46a38"),
    ),
    "frontend/src/views/wage/PayrollLedgerTab.vue": (
        ("100644", "blob", "851be3850db6fa53e698bc4570d919c949c430bc"),
        ("100644", "blob", "71870908edae7a3d94a0d89b375f1e244278778d"),
    ),
    "frontend/tests/unit/payroll-audit-behavior.spec.js": (
        ("100644", "blob", "2702ffd5f36046d77f0bcadffb99083f189c9cc4"),
        ("100644", "blob", "14313b76e1775558f78b07fb067877b6b9e5d65f"),
    ),
    "frontend/tests/unit/task2d-wage-layers.spec.js": (
        ("100644", "blob", "ade535df3c31147598ff9cd9ceeb2bfa32b913ca"),
        ("100644", "blob", "2ac73bb3e97cbd618d8732fa7f3693463021f4f1"),
    ),
    "modules/domain/payroll_audit_rules.py": (
        None,
        ("100644", "blob", "8fc8c5e2e592619c01830c408af744c1ea829b8c"),
    ),
    "modules/repositories/payroll_repository.py": (
        ("100644", "blob", "ef7ad557e7fc39f0d7fb96f56930dcc4d60bd0eb"),
        ("100644", "blob", "f9abda35483cb1b2382be04ba36475d4978ddca8"),
    ),
    "modules/routes/payroll.py": (
        ("100644", "blob", "148429bf6da79d42954e92073e660fa756e6e990"),
        ("100644", "blob", "589d923f9d5ae3d015cd15051d15ab2159f39229"),
    ),
    "modules/services/payroll_service.py": (
        ("100644", "blob", "b7762a12c3938df2789b3595cbc40083f0824f5f"),
        ("100644", "blob", "1ebaddaf91048fac1bdad508dfaaf00912f1ff2b"),
    ),
    "tests/test_architecture_imports.py": (
        ("100644", "blob", "862eb4e6b0d48b30f70468b07b2cce52a1e54c03"),
        ("100644", "blob", "6b04a7ebeade923a80239e5c0ac90802f6642350"),
    ),
    "tests/test_code_only_deployment.py": (
        ("100644", "blob", "aa6b4438fa08e9f3e9051bb858a091fe340f8327"),
        ("100644", "blob", "33aa26ac1c3d94de6201b49ce74b7c37706b4f2b"),
    ),
    "tests/test_migrations.py": (
        ("100644", "blob", "4f43bfcdd82289ef69b274b9a201bb04a09d7eac"),
        ("100644", "blob", "89dd7afa66b0efabfc636b5cf8a28e02d6fe88ee"),
    ),
    "tests/test_operations_facade.py": (
        ("100644", "blob", "0e26ec8933b71b0e48ac4c26650e91322e60ee1f"),
        ("100644", "blob", "6fd8be3455e6d32f659e3dd88066491c41e4aed7"),
    ),
    "tests/test_payroll_audit_findings.py": (
        None,
        ("100644", "blob", "718c0137d5c50938a77961653398e8c29965ca68"),
    ),
    "tests/test_payroll_audit_rules.py": (
        None,
        ("100644", "blob", "22f99c2523f4adf5d292bdafaef361ad7a222b26"),
    ),
    "tests/test_production_node_schedule_workflow.py": (
        ("100644", "blob", "585d678b1deed253a833d855cfa60d2219821077"),
        ("100644", "blob", "4f9198f3acfa106a5565709a747925db7b96caed"),
    ),
    "tests/test_schedule_capacity.py": (
        ("100644", "blob", "f25e90363e8222081e93f6c9a9df0122ae25066c"),
        ("100644", "blob", "28bcf32953d4567867ed67d592b6c1cf03fa2d0f"),
    ),
    "tests/test_validate_production_scheduling_v094_final_acceptance.py": (
        ("100644", "blob", "865ad0d424c6dfaf144935852f71b665efa6465c"),
        ("100644", "blob", "961c472f1f1d392bddb31846fa1aa0eed48d9d61"),
    ),
}
CONTROL_TRANSITIONS = {
    "docs/deployment/payroll-risk-closure-v98-release.md": (
        None,
        ("100644", "blob", "01482d9e12a905b84ef0d00bf693fa7302dc132c"),
    ),
    "scripts/bootstrap_payroll_risk_closure_v98_release.py": (
        None,
        ("100644", "blob", "f7a18b71fb36afc3238275d01469ef2cbc47c410"),
    ),
    "scripts/deploy-payroll-risk-closure-v98.sh": (
        None,
        ("100644", "blob", "73adfbc4a47c768399c4b5434935697101f9f3d5"),
    ),
    "scripts/payroll_risk_closure_v98_release.py": (
        None,
        ("100644", "blob", "046988c80e49a366b7dc652af0fc9f13cbfba0b0"),
    ),
    "tests/test_payroll_risk_closure_v98_release.py": (
        None,
        ("100644", "blob", "d7217d19e07918b567bcbaf1507bd46828d8eb18"),
    ),
}
REQUIRED_TABLES = {
    "payroll_settlements",
    "payroll_export_batches",
    "payroll_export_items",
    "payroll_receipt_batches",
    "payroll_receipt_items",
    "payroll_reconciliation_runs",
    "payroll_reconciliation_items",
    "payroll_reconciliation_resolutions",
    "payroll_close_records",
    "payroll_audit_findings",
}
REQUIRED_TRIGGERS = {
    "prevent_closed_payroll_export_batch_insert",
    "prevent_closed_payroll_receipt_batch_insert",
    "prevent_closed_payroll_reconciliation_run_insert",
    "protect_payroll_export_item_update",
    "protect_payroll_close_record_delete",
    "protect_closed_payroll_settlement",
    "prevent_payroll_settlement_delete",
    "trg_payroll_settlement_current_batch_insert",
    "trg_payroll_settlement_batch_immutable",
    "trg_payroll_settled_batch_immutable",
    "trg_payroll_batch_nonnegative_transition",
    "trg_payroll_employee_line_insert_immutable",
    "trg_payroll_export_item_nonnegative",
    "trg_payroll_audit_finding_definition_immutable",
    "trg_payroll_audit_finding_resolution_once",
    "trg_payroll_audit_finding_no_delete",
    "prevent_invalid_payroll_batch_transition",
    "protect_payroll_batch_amounts",
    "protect_payroll_audit_rule_version",
}
REQUIRED_COLUMNS = {
    "payroll_adjustments": {
        "id", "employee_id", "employee_name_snapshot", "employee_no_snapshot", "payroll_month",
        "adjustment_type", "amount_cents", "reason", "created_by", "created_by_name",
        "created_at", "reversal_of_id", "replacement_for_id", "legacy_wage_adjustment_id",
        "idempotency_key", "request_digest",
    },
    "payroll_batches": {
        "id", "payroll_month", "version", "period_start", "period_end", "status",
        "source_cutoff_at", "input_digest", "idempotency_key", "normal_wage_cents",
        "rework_wage_cents", "bonus_cents", "allowance_cents", "deduction_cents",
        "payable_wage_cents", "source_record_count", "priced_record_count", "exception_count",
        "prepared_by", "prepared_by_name", "prepared_at", "submitted_at", "locked_by",
        "locked_by_name", "locked_at", "confirmed_by", "confirmed_by_name", "confirmed_at",
        "voided_by", "voided_by_name", "voided_at", "void_reason", "supersedes_batch_id",
        "superseded_by_batch_id", "revision_reason", "legacy_imported", "row_version",
        "created_at", "updated_at", "audit_run_version", "audit_rule_version",
    },
    "payroll_settlements": {
        "id", "batch_id", "status", "expected_total_cents", "successful_paid_cents",
        "difference_cents", "blocking_difference_count", "current_export_batch_id",
        "latest_reconciliation_run_id", "row_version", "created_by", "created_by_name",
        "created_at", "updated_at",
    },
    "payroll_export_batches": {
        "id", "settlement_id", "export_version", "status", "row_count", "total_cents",
        "content_sha256", "csv_content_blob", "idempotency_key", "created_by",
        "created_by_name", "created_at", "superseded_at", "superseded_by_export_id",
    },
    "payroll_export_items": {
        "id", "export_batch_id", "employee_line_id", "employee_id", "employee_no_snapshot",
        "employee_name_snapshot", "payable_cents", "payment_reference", "sequence_no", "created_at",
    },
    "payroll_receipt_batches": {
        "id", "export_batch_id", "status", "source_filename", "content_sha256",
        "accepted_row_count", "failed_row_count", "idempotency_key", "uploaded_by",
        "uploaded_by_name", "uploaded_at",
    },
    "payroll_receipt_items": {
        "id", "receipt_batch_id", "row_number", "payment_reference", "employee_no_snapshot",
        "employee_name_snapshot", "paid_cents", "payment_status", "paid_at",
        "external_transaction_no", "failure_reason", "validation_status", "validation_error", "created_at",
    },
    "payroll_reconciliation_runs": {
        "id", "settlement_id", "export_batch_id", "run_version", "status",
        "expected_total_cents", "successful_paid_cents", "difference_cents", "blocking_count",
        "receipt_digest", "idempotency_key", "executed_by", "executed_by_name", "executed_at",
    },
    "payroll_reconciliation_items": {
        "id", "reconciliation_run_id", "export_item_id", "payment_reference", "expected_cents",
        "successful_paid_cents", "difference_cents", "difference_type", "blocking", "detail_json",
    },
    "payroll_reconciliation_resolutions": {
        "id", "reconciliation_item_id", "receipt_item_id", "resolution_code", "resolution_reason",
        "idempotency_key", "resolved_by", "resolved_by_name", "resolved_at",
    },
    "payroll_close_records": {
        "id", "settlement_id", "export_batch_id", "reconciliation_run_id", "expected_total_cents",
        "successful_paid_cents", "close_digest", "close_reason", "idempotency_key", "closed_by",
        "closed_by_name", "closed_at",
    },
    "payroll_audit_findings": {
        "id",
        "batch_id",
        "calculation_version",
        "finding_type",
        "severity",
        "status",
        "subject_type",
        "subject_id",
        "rule_version",
        "snapshot_json",
        "resolution_code",
        "resolution_reason",
        "resolved_by",
        "resolved_at",
        "created_at",
    },
}
REQUIRED_INDEXES = {
    "idx_payroll_adjustment_idempotency",
    "idx_payroll_audit_findings_current",
    "idx_payroll_audit_findings_subject",
}
REQUIRED_INDEX_DEFINITIONS = {
    "idx_payroll_adjustment_idempotency": (
        "payroll_adjustments", ("idempotency_key",), True, True,
    ),
    "idx_payroll_audit_findings_current": (
        "payroll_audit_findings",
        ("batch_id", "calculation_version", "status", "severity", "finding_type"),
        False,
        False,
    ),
    "idx_payroll_audit_findings_subject": (
        "payroll_audit_findings", ("subject_type", "subject_id", "finding_type"), False, False,
    ),
}
REQUIRED_COLUMN_SIGNATURE_SHA256 = {
    "payroll_audit_findings": "cc35c149dd7f085d35d98012c3d2a26e78ba4b9884f226accc3bf4ea9e7bb8b8",
    "payroll_adjustments": "569326114fd5bd6f4aaf882dde6269c7a95d38691655a13cca0804728225c530",
    "payroll_batches": "963c3b4665a6f9df45836f0025d1db057b99f258e471c59bbe8c33bcd9eeff5b",
    "payroll_close_records": "12d3e5d6356f9ac9658108ce6e3e8e49a26674d9d964735127c1b944df25c7a7",
    "payroll_export_batches": "9fa808e9560ede7399a7070b631a0b8ad4e84df04549eb7cdb4cbdf442a396d4",
    "payroll_export_items": "77fe730ecd5209197a448b7a021d8be91cef47bbcaa3b074598b80b97bd13caf",
    "payroll_receipt_batches": "5d0ace349c34bd2037e169659e85894233debc88c9a89e1c95abf6932d3fe5b3",
    "payroll_receipt_items": "4f29c94794b7a6adfdbdfeea819731639677716546c8eebddead29b5241c6021",
    "payroll_reconciliation_items": "b1a86d3d30999070c1b21b4fc6621a09dd86f8ec5e593634c4c4c61699abcf6f",
    "payroll_reconciliation_resolutions": "b61adf0837d4fa76d595b5715119ea488d769a7e5defa110858fe37baf5e4a2e",
    "payroll_reconciliation_runs": "437b15ee39b81a61c1b8b80bf8b8bbb528c805fc6f3712490a1cf92834d25ebc",
    "payroll_settlements": "4645dbdf0f1cb27df18abf1ccf6df529545747c008d9bf00d4ea66546c844225",
}
REQUIRED_TRIGGER_SHA256 = {
    "prevent_closed_payroll_export_batch_insert": "d3b7fd8c7fab059dc0a4ca428a3b15ff52dca76abbf70bedb0d3138045a45c4d",
    "prevent_closed_payroll_receipt_batch_insert": "ba1ad2913638990745d04c7955b5048b1b7fc293fa6898985eff2b4e97db3fbb",
    "prevent_closed_payroll_reconciliation_run_insert": "573b2ab786fe9ebea89ef5e38d1e93726342c7d38ae666197a7d933d70eb8e69",
    "protect_payroll_export_item_update": "c226c3b14c0e3407a7afcdbc4041a31b9aa1ca001be73e14bb290e694fc01c01",
    "protect_payroll_close_record_delete": "42c398b9b491ca188f756cefe39f93c1e19d3ca10481a0393dfffa5b18e3cfcc",
    "protect_closed_payroll_settlement": "456507097e9a4c8a10c9cd6a543a0104de09c00e6991ff7b13adf8f02cef4931",
    "prevent_payroll_settlement_delete": "62b768b133a1f4d9c5fa40c367e0987b92ac5ad5c9d6f91c528df02dfbb0af6d",
    "trg_payroll_settlement_current_batch_insert": "ab8c176fbe3a415c2367d9d7da0b4991dcd63b747cea5d966fc6fd12b1d8c95f",
    "trg_payroll_settlement_batch_immutable": "d3b3cc8fd0897e2aece88dcfd3777414dd83fa9da69ce44b200f25c5243e37ed",
    "trg_payroll_settled_batch_immutable": "90b35b6f2e0328efd84e6feaa3c405316c3869ce706143558905cf0df8ac516a",
    "trg_payroll_batch_nonnegative_transition": "6cc00fbf85142c2e1b164410521b700c4369fa81000103bc43f03824b6760934",
    "trg_payroll_employee_line_insert_immutable": "d12a593d97cdfc055ba5e813707f2f164f56919075815c1ddac92c6e3f5c7360",
    "trg_payroll_export_item_nonnegative": "ed398e578c7e41dd2a448ddc2556204c3ec8196982530031d6a9ceb9789d9cf2",
    "trg_payroll_audit_finding_definition_immutable": "673fb7b92b45c2a24cd4e45c4029b069ed60c69097df1e1b56fae43e3671eb81",
    "trg_payroll_audit_finding_resolution_once": "420d1393c9eb37fc7df08d2c35a3e85a3d5f9d1610961c5f98d23daae28ae33b",
    "trg_payroll_audit_finding_no_delete": "c6eafe56e1fb38af37b2f049e532f097a89ccf796e1b5203e9dab8db74fa881f",
    "prevent_invalid_payroll_batch_transition": "8352f1228e23f08e71a90e72bbdc0b2903505734efc223272fd2c275e3f26956",
    "protect_payroll_batch_amounts": "782796915679dbf6611b9717c6669919d3b1c92f684835a1ac08b8fce78ce511",
    "protect_payroll_audit_rule_version": "fb2f71b211c8b45c93169ca4707db976ee41695c1647006e48f202bc77018841",
}
MIN_FREE_BYTES = 2 * 1024 * 1024 * 1024
OFFLINE_MIGRATION_SECRET = "offline-payroll-audit-v100"
TOOL_CHANGE_PATHS = {
    "docs/deployment/payroll-audit-v100-release.md",
    "scripts/bootstrap_payroll_audit_v100_release.py",
    "scripts/deploy-payroll-audit-v100.sh",
    "scripts/payroll_audit_v100_release.py",
    "tests/test_payroll_audit_v100_release.py",
}


def _git(root, *args, check=True):
    result = subprocess.run(
        ["git", "-C", str(root), *args],
        check=False,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    if check and result.returncode:
        raise RuntimeError(
            f"git {' '.join(args)} failed: {result.stderr.strip()}"
        )
    return result.stdout.strip()


def _tree_entry(repository, commit, path):
    return static_release._tree_entry(repository, commit, path)


def _assert_clean(root, *, allow_untracked_data):
    output = subprocess.run(
        ["git", "-C", str(root), "status", "--porcelain=v1", "-z", "--untracked-files=all"],
        check=True,
        stdout=subprocess.PIPE,
    ).stdout
    unexpected = []
    for entry in output.split(b"\0"):
        if not entry:
            continue
        status = entry[:2]
        path = os.fsdecode(entry[3:])
        if allow_untracked_data and status == b"??" and (path == "data" or path.startswith("data/")):
            continue
        unexpected.append(f"{status.decode(errors='replace')} {path}")
    if unexpected:
        raise RuntimeError("worktree is not clean: " + "; ".join(unexpected[:10]))


def _json_value(value):
    if isinstance(value, bytes):
        return {"bytes_sha256": hashlib.sha256(value).hexdigest(), "size": len(value)}
    return value


def _table_columns(database):
    columns = {}
    with closing(sqlite3.connect(Path(database).resolve().as_uri() + "?mode=ro", uri=True)) as db:
        db.execute("PRAGMA query_only=ON")
        names = [
            row[0]
            for row in db.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name"
            )
        ]
        for name in names:
            quoted = name.replace('"', '""')
            columns[name] = [
                row[1] for row in db.execute(f'PRAGMA table_info("{quoted}")')
            ]
    return columns


def _table_facts(database, table_columns=None):
    facts = {}
    with closing(sqlite3.connect(Path(database).resolve().as_uri() + "?mode=ro", uri=True)) as db:
        db.execute("PRAGMA query_only=ON")
        columns_by_table = table_columns or _table_columns(database)
        for name, columns in columns_by_table.items():
            quoted = name.replace('"', '""')
            projection = ", ".join(
                f'"{column.replace(chr(34), chr(34) * 2)}"' for column in columns
            )
            digest = hashlib.sha256()
            count = 0
            for row in db.execute(f'SELECT {projection} FROM "{quoted}"'):
                encoded = json.dumps(
                    [_json_value(value) for value in row],
                    ensure_ascii=False,
                    sort_keys=True,
                    separators=(",", ":"),
                ).encode("utf-8")
                digest.update(encoded)
                digest.update(b"\n")
                count += 1
            facts[name] = {"row_count": count, "sha256": digest.hexdigest()}
    return facts


def _schema_acceptance(database, expected_version):
    evidence = deployment_manifest.sqlite_evidence(database)
    if evidence["user_version"] != expected_version:
        raise RuntimeError(
            f"schema mismatch: expected V{expected_version}, found V{evidence['user_version']}"
        )
    with closing(sqlite3.connect(Path(database).resolve().as_uri() + "?mode=ro", uri=True)) as db:
        tables = {
            row[0]
            for row in db.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            )
        }
        triggers = {
            row[0]
            for row in db.execute(
                "SELECT name FROM sqlite_master WHERE type='trigger'"
            )
        }
        indexes = {
            row[0]
            for row in db.execute(
                "SELECT name FROM sqlite_master WHERE type='index'"
            )
        }
        columns = {}
        column_signatures = {}
        for table in REQUIRED_COLUMNS:
            quoted = table.replace('"', '""')
            table_info = list(db.execute(f'PRAGMA table_info("{quoted}")'))
            columns[table] = {row[1] for row in table_info}
            column_signatures[table] = hashlib.sha256(
                json.dumps(
                    [tuple(row[1:6]) for row in table_info], separators=(",", ":")
                ).encode("utf-8")
            ).hexdigest()
        object_sql = {
            (kind, name): sql
            for kind, name, sql in db.execute(
                "SELECT type, name, sql FROM sqlite_master "
                "WHERE type IN ('index','trigger') AND name NOT LIKE 'sqlite_%'"
            )
        }
        index_definitions = {}
        for name, (table, _expected_columns, _unique, _partial) in REQUIRED_INDEX_DEFINITIONS.items():
            quoted = table.replace('"', '""')
            row = next(
                (row for row in db.execute(f'PRAGMA index_list("{quoted}")') if row[1] == name),
                None,
            )
            if row is None:
                continue
            index_columns = tuple(
                info[2] for info in db.execute(f'PRAGMA index_info("{name}")')
            )
            index_definitions[name] = (table, index_columns, bool(row[2]), bool(row[4]))
    missing_tables = sorted(REQUIRED_TABLES - tables)
    missing_triggers = sorted(REQUIRED_TRIGGERS - triggers)
    missing_indexes = sorted(REQUIRED_INDEXES - indexes)
    missing_columns = {
        table: sorted(required - columns.get(table, set()))
        for table, required in REQUIRED_COLUMNS.items()
        if required - columns.get(table, set())
    }
    invalid_column_definitions = {
        table: column_signatures.get(table)
        for table, digest in REQUIRED_COLUMN_SIGNATURE_SHA256.items()
        if column_signatures.get(table) != digest
    }
    invalid_indexes = {
        name: {"expected": expected, "actual": index_definitions.get(name)}
        for name, expected in REQUIRED_INDEX_DEFINITIONS.items()
        if index_definitions.get(name) != expected
    }
    invalid_triggers = {
        name: hashlib.sha256((object_sql.get(("trigger", name)) or "").encode("utf-8")).hexdigest()
        for name, digest in REQUIRED_TRIGGER_SHA256.items()
        if hashlib.sha256((object_sql.get(("trigger", name)) or "").encode("utf-8")).hexdigest() != digest
    }
    if (
        missing_tables
        or missing_triggers
        or missing_indexes
        or missing_columns
        or invalid_column_definitions
        or invalid_indexes
        or invalid_triggers
    ):
        raise RuntimeError(
            "V100 acceptance missing "
            f"tables={missing_tables} triggers={missing_triggers} "
            f"indexes={missing_indexes} columns={missing_columns}; "
            f"invalid_column_definitions={sorted(invalid_column_definitions)} "
            f"invalid_indexes={invalid_indexes} invalid_triggers={sorted(invalid_triggers)}"
        )
    return {
        **evidence,
        "required_tables": sorted(REQUIRED_TABLES),
        "required_triggers": sorted(REQUIRED_TRIGGERS),
        "required_indexes": sorted(REQUIRED_INDEXES),
        "verified_trigger_count": len(REQUIRED_TRIGGER_SHA256),
        "verified_column_definition_count": len(REQUIRED_COLUMN_SIGNATURE_SHA256),
        "verified_index_definitions": sorted(REQUIRED_INDEX_DEFINITIONS),
        "required_columns": {
            table: sorted(required) for table, required in REQUIRED_COLUMNS.items()
        },
    }


def _run_target_migrations(target_root, database):
    command = [
        sys.executable,
        "-c",
        (
            "import sqlite3,sys; "
            "sys.path.insert(0, sys.argv[1]); "
            "from modules.application.operations_facade import OperationsFacade; "
            "db=sqlite3.connect(sys.argv[2]); db.execute('PRAGMA foreign_keys=ON'); "
            "version=OperationsFacade.migrate_database(db); "
            "stored=db.execute('PRAGMA user_version').fetchone()[0]; "
            "db.close(); print(f'{version}:{stored}')"
        ),
        str(target_root),
        str(database),
    ]
    result = subprocess.run(
        command,
        cwd=target_root,
        check=False,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        env={
            **os.environ,
            "PYTHONPATH": str(target_root),
            "SECRET_KEY": OFFLINE_MIGRATION_SECRET,
        },
    )
    if result.returncode:
        raise RuntimeError("target migration failed: " + result.stderr.strip())
    result_line = result.stdout.strip().splitlines()[-1] if result.stdout.strip() else ""
    if not result_line.endswith(f":{TARGET_SCHEMA}"):
        raise RuntimeError("target migration returned unexpected version: " + result.stdout.strip())


def _database_footprint(database):
    database = Path(database)
    size = database.stat().st_size
    wal = Path(str(database) + "-wal")
    if wal.is_file() and not wal.is_symlink():
        size += wal.stat().st_size
    return size


def _copy_database(source, target):
    source = Path(source).resolve(strict=True)
    target = Path(target)
    with closing(sqlite3.connect(source.as_uri() + "?mode=ro", uri=True)) as original:
        original.execute("PRAGMA query_only=ON")
        with closing(sqlite3.connect(target)) as replica:
            original.backup(replica)
            replica.commit()


def run_replica_trial(repository, target_commit, database):
    source = deployment_manifest.sqlite_evidence(database)
    if source["user_version"] != SOURCE_SCHEMA:
        raise RuntimeError(
            f"replica trial requires production V{SOURCE_SCHEMA}, found V{source['user_version']}"
        )
    with tempfile.TemporaryDirectory(prefix="qr-payroll-v100-replica-") as directory:
        root = Path(directory)
        target_root = root / "target"
        subprocess.run(
            ["git", "-C", str(repository), "worktree", "add", "--quiet", "--detach", str(target_root), target_commit],
            check=True,
        )
        try:
            replica = root / "production-v98.db"
            _copy_database(database, replica)
            existing_columns = _table_columns(replica)
            facts_before = _table_facts(replica, existing_columns)
            _run_target_migrations(target_root, replica)
            acceptance = _schema_acceptance(replica, TARGET_SCHEMA)
            facts_after = _table_facts(replica, existing_columns)
            if facts_after != facts_before:
                changed = sorted(
                    name for name in existing_columns if facts_before[name] != facts_after[name]
                )
                raise RuntimeError(
                    "V98->V100 migration changed pre-existing table facts: "
                    + ", ".join(changed)
                )
            all_facts = _table_facts(replica)
            _run_target_migrations(target_root, replica)
            if _table_facts(replica) != all_facts:
                raise RuntimeError("V98->V100 migration is not idempotent on a migrated replica")
            _schema_acceptance(replica, TARGET_SCHEMA)
            return {
                "source": source,
                "target": acceptance,
                "preserved_existing_table_count": len(existing_columns),
                "source_database_read_only": True,
            }
        finally:
            subprocess.run(
                ["git", "-C", str(repository), "worktree", "remove", "--force", str(target_root)],
                check=False,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )


def validate_business_transition(repository, before_commit, target_commit):
    if (before_commit, target_commit) != (BASELINE_COMMIT, TARGET_COMMIT):
        raise RuntimeError("payroll V100 release requires the reviewed baseline and target")
    changed = code_only_release._changed_paths(
        repository, before_commit, target_commit
    )
    transitions = {
        **MIGRATION_TRANSITIONS,
        **SUPPORT_TRANSITIONS,
        **CONTROL_TRANSITIONS,
    }
    if set(changed) != set(transitions):
        unexpected = sorted(set(changed) ^ set(transitions))
        raise RuntimeError(
            "release path set differs from the reviewed V98->V100 transition: "
            + ", ".join(unexpected)
        )
    for path, (expected_before, expected_target) in transitions.items():
        if (
            _tree_entry(repository, before_commit, path) != expected_before
            or _tree_entry(repository, target_commit, path) != expected_target
        ):
            raise RuntimeError(f"reviewed mode/blob transition mismatch: {path}")
    observed_migrations = {
        path for path in changed if path.startswith("modules/migration")
    }
    if observed_migrations != set(MIGRATION_TRANSITIONS):
        raise RuntimeError(
            "release contains an unreviewed migration path: "
            + ", ".join(sorted(observed_migrations ^ set(MIGRATION_TRANSITIONS)))
        )
    return changed


def validate_release(tool_root, project_root, database, before_commit, target_commit, *, replica_trial=True):
    tool = Path(tool_root).resolve(strict=True)
    project = Path(project_root).resolve(strict=True)
    database = Path(database).resolve(strict=True)
    if (before_commit, target_commit) != (BASELINE_COMMIT, TARGET_COMMIT):
        raise RuntimeError("payroll V100 release requires the reviewed baseline and target")
    if tool == project or tool in project.parents or project in tool.parents:
        raise RuntimeError("production and release-tool worktrees must be separate")
    if _git(project, "rev-parse", "HEAD") != before_commit:
        raise RuntimeError("production checkout does not match the reviewed baseline")
    marker = project / ".deployed_commit"
    if marker.is_symlink() or not marker.is_file() or marker.read_text(encoding="ascii").strip() != before_commit:
        raise RuntimeError("production deployed marker does not match the reviewed baseline")
    _assert_clean(project, allow_untracked_data=True)
    _assert_clean(tool, allow_untracked_data=False)
    _git(tool, "cat-file", "-e", f"{target_commit}^{{commit}}")
    tool_head = _git(tool, "rev-parse", "HEAD")
    if subprocess.run(
        ["git", "-C", str(tool), "merge-base", "--is-ancestor", target_commit, tool_head]
    ).returncode:
        raise RuntimeError("release-tool commit does not contain the reviewed target")
    if subprocess.run(
        ["git", "-C", str(tool), "merge-base", "--is-ancestor", before_commit, target_commit]
    ).returncode:
        raise RuntimeError("target is not based on the production baseline")
    tool_changes = set(code_only_release._changed_paths(tool, target_commit, tool_head))
    if tool_changes != TOOL_CHANGE_PATHS:
        raise RuntimeError(
            "release-tool commit contains an unexpected path set: "
            + ", ".join(sorted(tool_changes ^ TOOL_CHANGE_PATHS))
        )

    changed = validate_business_transition(tool, before_commit, target_commit)
    for path in ("package.json", "package-lock.json", ".nvmrc", ".node-version", ".npmrc", "vite.config.js"):
        static_release._assert_same_blob(tool, before_commit, target_commit, path)
    if code_only_release._tracked_data_paths(tool, before_commit) or code_only_release._tracked_data_paths(tool, target_commit):
        raise RuntimeError("migration release refuses tracked production data")

    database_evidence = deployment_manifest.sqlite_evidence(database)
    if database_evidence["user_version"] != SOURCE_SCHEMA:
        raise RuntimeError(
            f"production schema must be V{SOURCE_SCHEMA}, found V{database_evidence['user_version']}"
        )
    target_schema = code_only_release._target_schema_version(tool)
    if target_schema != TARGET_SCHEMA:
        raise RuntimeError(f"reviewed target must declare V{TARGET_SCHEMA}, found V{target_schema}")
    attachments = deployment_manifest.managed_path_inventory(
        project, deployment_manifest.MANAGED_ATTACHMENT_ROOTS
    )
    release = deployment_manifest.managed_path_inventory(
        project, deployment_manifest.MANAGED_RELEASE_ROOTS
    )
    free_bytes = shutil.disk_usage(project).free
    required_free = max(
        MIN_FREE_BYTES,
        _database_footprint(database) * 4
        + attachments["total_bytes"] * 2
        + release["total_bytes"] * 3,
    )
    if free_bytes < required_free:
        raise RuntimeError(
            f"insufficient free space: need {required_free} bytes, found {free_bytes}"
        )

    trial = run_replica_trial(tool, target_commit, database) if replica_trial else None
    return {
        "scope": "backend_frontend_migration",
        "before_commit": before_commit,
        "target_commit": target_commit,
        "tool_commit": tool_head,
        "changed_paths": changed,
        "database": database_evidence,
        "source_schema_version": SOURCE_SCHEMA,
        "target_schema_version": TARGET_SCHEMA,
        "free_bytes": free_bytes,
        "required_free_bytes": required_free,
        "managed_attachments": attachments,
        "managed_release": release,
        "replica_trial": trial,
        "operations": {
            "database_migration": True,
            "attachment_migration": False,
            "frontend_publish": True,
            "service_restart": True,
        },
    }


def migrate_production(target_root, database, manifest_path, project_root):
    manifest = deployment_manifest.require_schema(
        deployment_manifest.read_json(manifest_path),
        deployment_manifest.DEPLOYMENT_SCHEMA,
        "deployment manifest",
    )
    if manifest.get("scope") != deployment_manifest.DEPLOYMENT_SCOPE_BACKEND_FRONTEND_MIGRATION:
        raise RuntimeError("production migration requires the migration deployment scope")
    deployment_manifest._active_fence_for_manifest(manifest)
    if manifest.get("status") != "backup_verified":
        raise RuntimeError("production migration requires verified final backups")
    if manifest.get("before_commit") != BASELINE_COMMIT or manifest.get("target_commit") != TARGET_COMMIT:
        raise RuntimeError("deployment manifest does not match the reviewed V98->V100 transition")
    project = Path(project_root).resolve(strict=True)
    migration_root = Path(target_root).resolve(strict=True)
    if migration_root != project:
        raise RuntimeError("migration target root must be the verified production target checkout")
    if _git(project, "rev-parse", "HEAD") != TARGET_COMMIT:
        raise RuntimeError("migration target checkout does not match the reviewed target SHA")
    marker = project / ".deployed_commit"
    if marker.read_text(encoding="ascii").strip() != TARGET_COMMIT:
        raise RuntimeError("production marker must be switched to the target before migration")
    if deployment_manifest.sqlite_evidence(database)["user_version"] != SOURCE_SCHEMA:
        raise RuntimeError("production database is not at the reviewed V98 baseline")
    _run_target_migrations(migration_root, database)
    return _schema_acceptance(database, TARGET_SCHEMA)


def verify_attachments(project_root, backup_metadata):
    metadata = deployment_manifest.verify_backup_metadata(backup_metadata)
    observed = deployment_manifest.managed_path_inventory(
        project_root, deployment_manifest.MANAGED_ATTACHMENT_ROOTS
    )
    expected = metadata["attachments"]["inventory"]
    if deployment_manifest.inventory_content_identity(
        observed
    ) != deployment_manifest.inventory_content_identity(expected):
        raise RuntimeError("managed attachments changed during the migration release")
    return observed


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    preflight = commands.add_parser("preflight")
    preflight.add_argument("--tool-root", required=True)
    preflight.add_argument("--project-root", required=True)
    preflight.add_argument("--database", required=True)
    preflight.add_argument("--before-commit", required=True)
    preflight.add_argument("--target-commit", required=True)
    preflight.add_argument("--skip-replica-trial", action="store_true")
    migrate = commands.add_parser("migrate")
    migrate.add_argument("--target-root", required=True)
    migrate.add_argument("--database", required=True)
    migrate.add_argument("--manifest", required=True)
    migrate.add_argument("--project-root", required=True)
    acceptance = commands.add_parser("acceptance")
    acceptance.add_argument("--database", required=True)
    attachments = commands.add_parser("verify-attachments")
    attachments.add_argument("--project-root", required=True)
    attachments.add_argument("--backup-metadata", required=True)
    args = parser.parse_args(argv)
    if args.command == "preflight":
        result = validate_release(
            args.tool_root,
            args.project_root,
            args.database,
            args.before_commit,
            args.target_commit,
            replica_trial=not args.skip_replica_trial,
        )
    elif args.command == "migrate":
        result = migrate_production(
            args.target_root, args.database, args.manifest, args.project_root
        )
    elif args.command == "acceptance":
        result = _schema_acceptance(args.database, TARGET_SCHEMA)
    else:
        result = verify_attachments(args.project_root, args.backup_metadata)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
