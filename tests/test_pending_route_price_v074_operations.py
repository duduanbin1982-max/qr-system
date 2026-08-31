import sqlite3

import pytest


def copy_v073_database(tmp_path):
    from modules.migrations import MIGRATIONS

    source = tmp_path / "source-v073.db"
    db = sqlite3.connect(source)
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA foreign_keys=ON")
    try:
        for version, _, migration in MIGRATIONS:
            if version > 73:
                break
            migration(db)
            db.execute(f"PRAGMA user_version={version}")
            db.commit()
    finally:
        db.close()
    return source


def _seed_exact_binding(db, *, price_count=1, suffix="OPS"):
    process_id = db.execute(
        "INSERT INTO processes(name,category,status,process_code,lifecycle_status) "
        "VALUES (?,?, 'active',?, 'active')",
        (f"V074 运维工序 {suffix}", "机加工", f"PROC-V074-{suffix}"),
    ).lastrowid
    process_version_id = db.execute(
        "INSERT INTO process_versions(process_id,version,process_code_snapshot,name,"
        "category,status,content_digest,idempotency_key) "
        "VALUES (?,1,?,?,?,'pending_approval',?,?)",
        (
            process_id,
            f"PROC-V074-{suffix}",
            f"V074 运维工序 {suffix}",
            "机加工",
            f"process-digest-{suffix}",
            f"v074-ops-process-{suffix}",
        ),
    ).lastrowid
    route_id = db.execute(
        "INSERT INTO process_routes(name,category,status,route_code,lifecycle_status) "
        "VALUES (?,?, 'inactive',?, 'active')",
        (f"V074 运维路线 {suffix}", "机加工", f"ROUTE-V074-{suffix}"),
    ).lastrowid
    route_version_id = db.execute(
        "INSERT INTO process_route_versions(process_route_id,version,route_code_snapshot,"
        "name,category,status,content_digest,idempotency_key) "
        "VALUES (?,1,?,?,?,'pending_approval',?,?)",
        (
            route_id,
            f"ROUTE-V074-{suffix}",
            f"V074 运维路线 {suffix}",
            "机加工",
            f"route-digest-{suffix}",
            f"v074-ops-route-{suffix}",
        ),
    ).lastrowid
    db.execute(
        "INSERT INTO process_route_version_items(route_version_id,process_id,"
        "process_version_id,seq_order) VALUES (?,?,?,10)",
        (route_version_id, process_id, process_version_id),
    )
    price_ids = []
    for index in range(price_count):
        price_ids.append(
            db.execute(
                "INSERT INTO route_price_versions(route_id,route_version_id,process_id,"
                "process_version_id,normal_unit_price_micros,valid_from,status,remark) "
                "VALUES (?,?,?,?,?,?, 'draft',?)",
                (
                    route_id,
                    route_version_id,
                    process_id,
                    process_version_id,
                    100000 + index,
                    f"2026-08-{index + 1:02d} 07:00:00",
                    f"draft-{suffix}-{index + 1}",
                ),
            ).lastrowid
        )
    db.commit()
    return {
        "process_id": process_id,
        "process_version_id": process_version_id,
        "route_id": route_id,
        "route_version_id": route_version_id,
        "price_ids": price_ids,
    }


def _seed_preserved_business_data(path):
    db = sqlite3.connect(path)
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA foreign_keys=ON")
    binding = _seed_exact_binding(db, suffix="PRESERVE")
    db.execute(
        "UPDATE process_versions SET status='published' WHERE id=?",
        (binding["process_version_id"],),
    )
    db.execute(
        "UPDATE process_route_versions SET status='published' WHERE id=?",
        (binding["route_version_id"],),
    )
    db.execute(
        "UPDATE processes SET current_effective_version_id=? WHERE id=?",
        (binding["process_version_id"], binding["process_id"]),
    )
    db.execute(
        "UPDATE process_routes SET status='active',current_effective_version_id=? WHERE id=?",
        (binding["route_version_id"], binding["route_id"]),
    )
    approved_price_id = db.execute(
        "INSERT INTO route_price_versions(route_id,route_version_id,process_id,"
        "process_version_id,normal_unit_price_micros,valid_from,valid_to,status,remark) "
        "VALUES (?,?,?,?,200000,'2026-01-01 07:00:00','2026-02-01 07:00:00',"
        "'approved','approved-v073')",
        (
            binding["route_id"],
            binding["route_version_id"],
            binding["process_id"],
            binding["process_version_id"],
        ),
    ).lastrowid
    db.execute(
        "INSERT INTO route_price_versions(route_id,route_version_id,process_id,"
        "process_version_id,normal_unit_price_micros,valid_from,valid_to,status,remark) "
        "VALUES (?,?,?,?,300000,'2026-02-01 07:00:00','2026-03-01 07:00:00',"
        "'retired','retired-v073')",
        (
            binding["route_id"],
            binding["route_version_id"],
            binding["process_id"],
            binding["process_version_id"],
        ),
    )
    batch_id = db.execute(
        "INSERT INTO master_data_release_batches(release_no,status,revision_reason) "
        "VALUES ('V074-OPS-BATCH','draft','V074 运维验证')"
    ).lastrowid
    db.execute(
        "INSERT INTO master_data_release_price_versions(batch_id,price_version_id) "
        "VALUES (?,?)",
        (batch_id, binding["price_ids"][0]),
    )
    order_id = db.execute(
        "INSERT INTO orders(order_no,route_id,route_version_id,route_name_snapshot) "
        "VALUES ('V074-OPS-PAYROLL',?,?, 'V074 运维路线')",
        (binding["route_id"], binding["route_version_id"]),
    ).lastrowid
    work_id = db.execute(
        "INSERT INTO work_records(order_id,process_id,user_id,status,quantity,"
        "process_version_id,route_id,route_version_id,process_code_snapshot,"
        "process_name_snapshot,process_category_snapshot,route_name_snapshot,"
        "version_binding_source) VALUES (?,?,1,'approved',1,?,?,?,"
        "'PROC-V074-OPS','V074 运维工序','机加工','V074 运维路线','captured')",
        (
            order_id,
            binding["process_id"],
            binding["process_version_id"],
            binding["route_id"],
            binding["route_version_id"],
        ),
    ).lastrowid
    payroll_batch_id = db.execute(
        "INSERT INTO payroll_batches(payroll_month,version,period_start,period_end,"
        "source_cutoff_at,idempotency_key) VALUES "
        "('2026-08',1,'2026-08-01 07:00:00','2026-09-01 07:00:00',"
        "'2026-09-01 07:00:00','v074-ops-payroll')"
    ).lastrowid
    employee_line_id = db.execute(
        "INSERT INTO payroll_employee_lines(batch_id,employee_id,employee_name_snapshot) "
        "VALUES (?,1,'V074 运维员工')",
        (payroll_batch_id,),
    ).lastrowid
    db.execute(
        "INSERT INTO payroll_detail_lines(batch_id,employee_line_id,source_type,"
        "source_id,work_record_id,order_id,route_id,process_id,quantity,price_version_id,"
        "unit_price_micros,amount_cents,resolution_method,resolution_reason,"
        "route_version_id,process_version_id,version_binding_source) "
        "VALUES (?,?,'normal_work',1,?,?,?,?,?,?,200000,200,'exact','v073',?,?, 'captured')",
        (
            payroll_batch_id,
            employee_line_id,
            work_id,
            order_id,
            binding["route_id"],
            binding["process_id"],
            1,
            approved_price_id,
            binding["route_version_id"],
            binding["process_version_id"],
        ),
    )
    db.execute(
        "INSERT INTO payroll_work_price_resolutions(work_record_id,price_version_id,"
        "resolution_method,resolution_reason) "
        "VALUES (?,?,'current_price_migration','v073')",
        (work_id, approved_price_id),
    )
    db.commit()
    db.close()


def test_v074_preflight_is_read_only_and_lists_blockers(tmp_path):
    from scripts.pending_route_price_v074_operations import database_sha256, run_preflight

    source = copy_v073_database(tmp_path)
    db = sqlite3.connect(source)
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA foreign_keys=ON")
    binding = _seed_exact_binding(db, price_count=2, suffix="BLOCK")
    db.execute("DROP TRIGGER validate_price_version_binding_insert")
    db.execute(
        "INSERT INTO route_price_versions(route_id,process_id,normal_unit_price_micros,"
        "valid_from,status,legacy_binding_unavailable) "
        "VALUES (?,?,100000,'2026-01-01 07:00:00','draft',0)",
        (binding["route_id"], binding["process_id"]),
    )
    other = _seed_exact_binding(db, suffix="OTHER")
    db.execute(
        "INSERT INTO route_price_versions(route_id,route_version_id,process_id,"
        "process_version_id,normal_unit_price_micros,valid_from,status) "
        "VALUES (?,?,?,?,100000,'2026-08-20 07:00:00','draft')",
        (
            binding["route_id"],
            binding["route_version_id"],
            other["process_id"],
            other["process_version_id"],
        ),
    )
    db.commit()
    db.close()
    before = database_sha256(source)

    report = run_preflight(source)

    assert database_sha256(source) == before
    assert report["mode"] == "read_only_preflight"
    assert report["database"]["user_version"] == 73
    assert report["database"]["query_only"] == 1
    assert set(report["blocking"]) == {
        "empty_bindings",
        "binding_mismatches",
        "duplicate_pending_drafts",
    }
    assert all(report["blocking"].values())
    assert report["status"] == "blocked"


def test_v074_preflight_and_replica_preserve_legacy_unbound_tombstone(tmp_path):
    from scripts.pending_route_price_v074_operations import (
        run_preflight,
        validate_replica,
    )

    source = copy_v073_database(tmp_path)
    db = sqlite3.connect(source)
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA foreign_keys=ON")
    binding = _seed_exact_binding(db, suffix="LEGACY")
    price_id = db.execute(
        "INSERT INTO route_price_versions(route_id,process_id,normal_unit_price_micros,"
        "valid_from,status,legacy_binding_unavailable,remark) "
        "VALUES (?,?,100000,'2026-01-01 07:00:00','retired',1,'legacy tombstone')",
        (binding["route_id"], binding["process_id"]),
    ).lastrowid
    db.commit()
    db.close()

    source_report = run_preflight(source)
    replica = tmp_path / "legacy-unbound-v074.db"
    report = validate_replica(source, replica)

    assert source_report["status"] == "passed"
    assert source_report["blocking"]["empty_bindings"] == []
    assert source_report["price_aggregates"]["total"][
        "preserved_legacy_unbound_rows"
    ] == 1
    assert report["status"] == "passed", report["blocking_differences"]
    migrated = sqlite3.connect(replica).execute(
        "SELECT status,legacy_binding_unavailable,route_version_id,process_version_id,"
        "remark FROM route_price_versions WHERE id=?",
        (price_id,),
    ).fetchone()
    assert migrated == ("retired", 1, None, None, "legacy tombstone")


def test_v074_replica_validation_preserves_business_aggregates(tmp_path):
    from scripts.pending_route_price_v074_operations import (
        database_sha256,
        run_preflight,
        validate_replica,
    )

    source = copy_v073_database(tmp_path)
    _seed_preserved_business_data(source)
    before_hash = database_sha256(source)
    source_report = run_preflight(source)
    replica = tmp_path / "validated-v074.db"

    report = validate_replica(source, replica)

    assert report["status"] == "passed", report["blocking_differences"]
    assert replica.is_file()
    assert database_sha256(source) == before_hash
    assert report["source_unchanged"] is True
    assert report["migration"] == {
        "source_version": 73,
        "target_version": 75,
        "executed_migrations": 2,
    }
    assert report["aggregate_comparison"]["approved"]["equal"] is True
    assert report["aggregate_comparison"]["retired"]["equal"] is True
    assert report["release_batches_equal"] is True
    assert report["payroll_references_equal"] is True
    assert report["blocking_differences"] == []
    assert report["replica"]["database"]["foreign_key_check"] == []
    assert report["replica"]["database"]["integrity_check"] == "ok"
    assert report["replica"]["database"]["user_version"] == 75
    assert report["replica"]["blocking"] == {
        "empty_bindings": [],
        "binding_mismatches": [],
        "duplicate_pending_drafts": [],
    }
    assert source_report["release_batches"]["active_batches"]
    assert source_report["payroll_references"]["detail_lines"]["rows"] == 1
    assert source_report["payroll_references"]["work_price_resolutions"]["rows"] == 1


def test_v074_preflight_cli_exits_nonzero_for_blockers(tmp_path):
    from scripts.pending_route_price_v074_operations import main

    source = copy_v073_database(tmp_path)
    db = sqlite3.connect(source)
    db.row_factory = sqlite3.Row
    _seed_exact_binding(db, price_count=2, suffix="CLI")
    db.close()

    assert main(["preflight", "--db", str(source)]) == 1


def test_pending_price_flags_allow_only_approved_stages(tmp_path):
    from scripts.pending_route_price_v074_operations import (
        read_pending_price_flags,
        validate_pending_price_flag_transition,
    )

    env_path = tmp_path / ".env"
    env_path.write_text("SECRET_KEY=test\n", encoding="utf-8")
    closed = read_pending_price_flags(env_path)
    assert closed == {
        "ROUTE_PRICE_PENDING_REFERENCE_ENABLED": False,
        "ROUTE_PRICE_PENDING_COMPAT_AUDIT_ENABLED": False,
        "ROUTE_PRICE_PENDING_WRITE_ENABLED": False,
    }

    env_path.write_text(
        "ROUTE_PRICE_PENDING_REFERENCE_ENABLED=true\n"
        "ROUTE_PRICE_PENDING_COMPAT_AUDIT_ENABLED=true\n",
        encoding="utf-8",
    )
    observe = read_pending_price_flags(env_path)
    assert validate_pending_price_flag_transition(closed, observe)["stage"] == "observe"

    env_path.write_text(
        "ROUTE_PRICE_PENDING_REFERENCE_ENABLED=true\n"
        "ROUTE_PRICE_PENDING_COMPAT_AUDIT_ENABLED=true\n"
        "ROUTE_PRICE_PENDING_WRITE_ENABLED=true\n",
        encoding="utf-8",
    )
    enabled = read_pending_price_flags(env_path)
    assert validate_pending_price_flag_transition(observe, enabled)["stage"] == "write"

    with pytest.raises(RuntimeError, match="cannot skip"):
        validate_pending_price_flag_transition(closed, enabled)

    env_path.write_text(
        "ROUTE_PRICE_PENDING_REFERENCE_ENABLED=true\n"
        "ROUTE_PRICE_PENDING_COMPAT_AUDIT_ENABLED=false\n",
        encoding="utf-8",
    )
    with pytest.raises(RuntimeError, match="approved staged states"):
        read_pending_price_flags(env_path)


def test_canonical_sha256_is_independent_of_mapping_order():
    from scripts.pending_route_price_v074_operations import canonical_sha256

    assert canonical_sha256({"a": 1, "b": [2, 3]}) == canonical_sha256(
        {"b": [2, 3], "a": 1}
    )
