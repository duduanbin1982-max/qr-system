from factories import (
    TEST_HASH,
    create_process_route,
    ensure_process,
    ensure_user,
)
from modules.db import get_db
from scripts import repair_current_route_work_time_standards as repair


def _new_revision(db, route_id, source_version_id):
    source = db.execute(
        "SELECT * FROM process_route_versions WHERE id=?",
        (source_version_id,),
    ).fetchone()
    target_version_id = db.execute(
        "INSERT INTO process_route_versions "
        "(process_route_id,version,route_code_snapshot,name,category,description,"
        "status,effective_from) VALUES (?,?,?,?,?,?,'draft','2026-09-20')",
        (
            route_id,
            source["version"] + 1,
            source["route_code_snapshot"],
            source["name"],
            source["category"],
            source["description"],
        ),
    ).lastrowid
    db.execute(
        "INSERT INTO process_route_version_items "
        "(route_version_id,process_id,process_version_id,seq_order,required_audit) "
        "SELECT ?,process_id,process_version_id,seq_order,required_audit "
        "FROM process_route_version_items WHERE route_version_id=?",
        (target_version_id, source_version_id),
    )
    db.execute(
        "UPDATE process_route_versions SET status='superseded',"
        "effective_to='2026-09-20' WHERE id=?",
        (source_version_id,),
    )
    db.execute(
        "UPDATE process_route_versions SET status='published' WHERE id=?",
        (target_version_id,),
    )
    db.execute(
        "UPDATE process_routes SET current_effective_version_id=? WHERE id=?",
        (target_version_id, route_id),
    )
    return target_version_id


def _insert_standards(
    db,
    route_id,
    route_version_id,
    *,
    minutes=60,
    setup=10,
    factor=1,
):
    ids = []
    rows = db.execute(
        "SELECT process_id,process_version_id FROM process_route_version_items "
        "WHERE route_version_id=? ORDER BY seq_order,id",
        (route_version_id,),
    ).fetchall()
    for row in rows:
        ids.append(
            db.execute(
                "INSERT INTO work_time_standards "
                "(route_id,route_version_id,process_id,process_version_id,"
                "standard_minutes_per_unit,setup_minutes,difficulty_factor,"
                "effective_from,status,version) "
                "VALUES (?,?,?,?,?,?,?,'2026-08-17','active',1)",
                (
                    route_id,
                    route_version_id,
                    row["process_id"],
                    row["process_version_id"],
                    minutes,
                    setup,
                    factor,
                ),
            ).lastrowid
        )
    return ids


def _seed_bundle(client):
    with client.application.app_context():
        db = get_db()
        process_ids = [
            ensure_process(db, f"当前标准工时受控复制-{index}", seq_order=index)
            for index in range(1, 8)
        ]
        route_id = create_process_route(
            db, process_ids, name="当前标准工时受控复制主路线"
        )
        source_version_id = db.execute(
            "SELECT current_effective_version_id FROM process_routes WHERE id=?",
            (route_id,),
        ).fetchone()["current_effective_version_id"]
        target_version_id = _new_revision(db, route_id, source_version_id)
        source_standard_ids = _insert_standards(
            db, route_id, source_version_id
        )
        supporting_routes = []
        for suffix in ("A", "B"):
            support_route_id = create_process_route(
                db, process_ids, name=f"当前标准工时支持路线-{suffix}"
            )
            support_version_id = db.execute(
                "SELECT current_effective_version_id FROM process_routes WHERE id=?",
                (support_route_id,),
            ).fetchone()["current_effective_version_id"]
            _insert_standards(
                db,
                support_route_id,
                support_version_id,
                minutes=15,
                setup=5,
            )
            supporting_routes.append(
                {
                    "route_id": support_route_id,
                    "route_version_id": support_version_id,
                }
            )
        operator_id = ensure_user(
            db,
            "worktime-copy-operator",
            TEST_HASH,
            "工时复制操作人",
            "admin",
            "WT-COPY-OP",
        )
        approver_id = ensure_user(
            db,
            "worktime-copy-approver",
            TEST_HASH,
            "工时复制批准人",
            "admin",
            "WT-COPY-APP",
        )
        db.commit()
        version = db.execute("PRAGMA user_version").fetchone()[0]
        return {
            "db_path": db.execute("PRAGMA database_list").fetchone()["file"],
            "database_version": version,
            "route_id": route_id,
            "source_version_id": source_version_id,
            "target_version_id": target_version_id,
            "source_standard_ids": source_standard_ids,
            "supporting_routes": tuple(supporting_routes),
            "operator_id": operator_id,
            "approver_id": approver_id,
        }


def test_current_route_standard_repair_dry_run_is_read_only(client):
    bundle = _seed_bundle(client)
    report = repair.run(
        bundle["db_path"],
        apply=False,
        idempotency_key="work-time-current-route-test",
        operator_id=bundle["operator_id"],
        approver_id=bundle["approver_id"],
        route_id=bundle["route_id"],
        source_route_version_id=bundle["source_version_id"],
        target_route_version_id=bundle["target_version_id"],
        supporting_routes=bundle["supporting_routes"],
        expected_database_version=bundle["database_version"],
    )
    assert report["ok"] is True
    assert report["planned"] == 7
    assert report["applied"] == 0
    with client.application.app_context():
        db = get_db()
        assert db.execute(
            "SELECT COUNT(*) FROM work_time_standards WHERE route_version_id=?",
            (bundle["target_version_id"],),
        ).fetchone()[0] == 0


def test_current_route_standard_repair_applies_exactly_once(client):
    bundle = _seed_bundle(client)
    kwargs = {
        "idempotency_key": "work-time-current-route-apply-test",
        "operator_id": bundle["operator_id"],
        "approver_id": bundle["approver_id"],
        "route_id": bundle["route_id"],
        "source_route_version_id": bundle["source_version_id"],
        "target_route_version_id": bundle["target_version_id"],
        "supporting_routes": bundle["supporting_routes"],
        "expected_database_version": bundle["database_version"],
    }
    first = repair.run(bundle["db_path"], apply=True, **kwargs)
    assert first["ok"] is True
    assert first["applied"] == 7
    second = repair.run(bundle["db_path"], apply=True, **kwargs)
    assert second["ok"] is True
    assert second["applied"] == 0
    assert second["replayed"] == 7
    with client.application.app_context():
        db = get_db()
        rows = db.execute(
            "SELECT standard_minutes_per_unit,setup_minutes,difficulty_factor,"
            "effective_from FROM work_time_standards WHERE route_version_id=?",
            (bundle["target_version_id"],),
        ).fetchall()
        assert len(rows) == 7
        assert all(row["standard_minutes_per_unit"] == 60 for row in rows)
        assert all(row["setup_minutes"] == 10 for row in rows)
        assert all(row["difficulty_factor"] == 1 for row in rows)
        assert all(row["effective_from"] == "2026-09-20" for row in rows)
        assert db.execute(
            "SELECT COUNT(*) FROM work_time_standard_binding_events "
            "WHERE target_route_version_id=?",
            (bundle["target_version_id"],),
        ).fetchone()[0] == 7
        assert db.execute(
            "SELECT COUNT(*) FROM work_time_standards WHERE id IN ("
            + ",".join("?" for _ in bundle["source_standard_ids"])
            + ")",
            bundle["source_standard_ids"],
        ).fetchone()[0] == 7
