"""Real caller transactions serialize order-common and report-specific deductions."""

import json
import shutil
import sqlite3
from concurrent.futures import ThreadPoolExecutor
from threading import Event

import pytest

from conftest import TEST_TEMPLATE_DB
from factories import add_order_material, create_material, create_order
from modules.process_fact_projection import capture_process_fact_binding
from modules.services.material_service import MaterialService
from modules.services.order_material_state_service import OrderMaterialStateService as State


def _connect(path, *, timeout=5):
    db = sqlite3.connect(path, timeout=timeout, isolation_level=None)
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA foreign_keys=ON")
    return db


@pytest.fixture
def concurrent_material_order(tmp_path):
    path = tmp_path / "concurrent-material-reports.db"
    shutil.copy2(TEST_TEMPLATE_DB, path)
    db = _connect(path)
    try:
        processes = [
            row["id"] for row in db.execute(
                "SELECT id FROM processes WHERE current_effective_version_id IS NOT NULL "
                "ORDER BY id LIMIT 2"
            )
        ]
        assert len(processes) == 2
        order_id = create_order(db, processes, quantity=5)
        db.execute("BEGIN IMMEDIATE")
        db.execute("UPDATE orders SET status='producing' WHERE id=?", (order_id,))
        material_id = create_material(db, quantity=100)
        add_order_material(db, order_id, material_id, None, 2)
        for process_id in processes:
            add_order_material(db, order_id, material_id, process_id, 1)
        user_ids = [
            db.execute(
                "INSERT INTO users(username,password,name,employee_no) VALUES (?,?,?,?)",
                (
                    f"concurrent-material-{index}", "unused",
                    f"Concurrent Worker {index}", f"CONCURRENT-MATERIAL-{index}",
                ),
            ).lastrowid
            for index in range(2)
        ]
        db.execute(
            "INSERT OR REPLACE INTO system_settings(key,value) "
            "VALUES ('auto_deduct_material','1')"
        )
        State.mark_initialized(order_id, None, 3, db)
        db.commit()
    finally:
        db.close()
    return path, order_id, material_id, processes, user_ids


def _approved_report_and_deduct(db, order_id, process_id, user_id, quantity):
    """Use the same report-owned transaction contract as the report service."""
    assert db.in_transaction
    binding = capture_process_fact_binding(db, order_id=order_id, process_id=process_id)
    values = {
        "order_id": order_id,
        "process_id": process_id,
        "user_id": user_id,
        "type": "normal",
        "status": "approved",
        "quantity": quantity,
        **{key: value for key, value in binding.items() if key != "process_id"},
    }
    columns = ",".join(values)
    placeholders = ",".join("?" for _ in values)
    work_record_id = db.execute(
        f"INSERT INTO work_records({columns}) VALUES ({placeholders})",
        tuple(values.values()),
    ).lastrowid
    MaterialService.deduct_for_process(
        order_id, process_id, quantity, user_id, "Concurrent Worker",
        db, work_record_id=work_record_id,
    )
    return work_record_id


@pytest.mark.parametrize("second_process_index", [0, 1], ids=["same-process", "other-process"])
@pytest.mark.parametrize("first_commits", [True, False], ids=["first-commits", "first-rolls-back"])
def test_overlapping_report_transactions_deduct_order_common_once(
    concurrent_material_order, second_process_index, first_commits,
):
    path, order_id, material_id, processes, user_ids = concurrent_material_order
    first_deduction_written = Event()
    second_confirmed_blocked = Event()

    def first_caller():
        db = _connect(path)
        try:
            db.execute("BEGIN IMMEDIATE")
            work_record_id = _approved_report_and_deduct(
                db, order_id, processes[0], user_ids[0], 2,
            )
            assert db.execute(
                "SELECT quantity FROM materials WHERE id=?", (material_id,),
            ).fetchone()[0] == 88
            first_deduction_written.set()
            assert second_confirmed_blocked.wait(10), "second caller did not contend"
            if first_commits:
                db.commit()
            else:
                db.rollback()
            return work_record_id
        finally:
            db.rollback()
            db.close()

    def second_caller():
        assert first_deduction_written.wait(10), "first caller did not reach its deduction"
        db = _connect(path, timeout=0)
        try:
            # The first report, inventory and immutable receipt remain uncommitted.
            assert db.execute(
                "SELECT quantity FROM materials WHERE id=?", (material_id,),
            ).fetchone()[0] == 100
            assert db.execute(
                "SELECT COUNT(*) FROM audit_logs WHERE action=? AND target_id=?",
                (State.COMMON_ACTION, order_id),
            ).fetchone()[0] == 0
            try:
                with pytest.raises(sqlite3.OperationalError) as blocked:
                    db.execute("BEGIN IMMEDIATE")
                assert (
                    getattr(blocked.value, "sqlite_errorcode", sqlite3.SQLITE_BUSY)
                    == sqlite3.SQLITE_BUSY
                )
                assert "locked" in str(blocked.value).lower()
                assert not db.in_transaction
            finally:
                # Release the first writer even when a serialization assertion fails.
                second_confirmed_blocked.set()

            db.execute("PRAGMA busy_timeout=5000")
            db.execute("BEGIN IMMEDIATE")
            # Read after acquiring the real write lock, never reuse the pre-lock view.
            assert db.execute(
                "SELECT quantity FROM materials WHERE id=?", (material_id,),
            ).fetchone()[0] == (88 if first_commits else 100)
            assert db.execute(
                "SELECT COUNT(*) FROM audit_logs WHERE action=? AND target_id=?",
                (State.COMMON_ACTION, order_id),
            ).fetchone()[0] == int(first_commits)
            work_record_id = _approved_report_and_deduct(
                db, order_id, processes[second_process_index], user_ids[1], 1,
            )
            db.commit()
            return work_record_id
        finally:
            db.rollback()
            db.close()

    with ThreadPoolExecutor(max_workers=2) as workers:
        first = workers.submit(first_caller)
        second = workers.submit(second_caller)
        first_report_id = first.result(timeout=20)
        second_report_id = second.result(timeout=20)

    db = _connect(path)
    try:
        reports = [
            dict(row) for row in db.execute(
                "SELECT * FROM work_records WHERE order_id=? ORDER BY id", (order_id,),
            )
        ]
        consumptions = [
            dict(row) for row in db.execute(
                "SELECT * FROM material_consumptions WHERE order_id=? ORDER BY id",
                (order_id,),
            )
        ]
        common = [row for row in consumptions if row["process_id"] is None]
        dedicated = [row for row in consumptions if row["process_id"] is not None]
        expected_report_ids = (
            {first_report_id, second_report_id} if first_commits else {second_report_id}
        )
        assert {row["id"] for row in reports} == expected_report_ids
        assert {row["user_id"] for row in reports} == (
            set(user_ids) if first_commits else {user_ids[1]}
        )
        assert len(common) == 1
        assert common[0]["quantity"] == 10
        assert common[0]["source_work_record_id"] is None
        assert len(dedicated) == len(expected_report_ids)
        assert {
            (row["source_work_record_id"], row["process_id"], row["quantity"])
            for row in dedicated
        } == {
            (row["id"], row["process_id"], row["quantity"]) for row in reports
        }
        assert db.execute(
            "SELECT quantity FROM materials WHERE id=?", (material_id,),
        ).fetchone()[0] == (87 if first_commits else 89)

        logs = [
            dict(row) for row in db.execute(
                "SELECT * FROM material_logs WHERE material_id=? ORDER BY id", (material_id,),
            )
        ]
        assert len(logs) == len(consumptions)
        assert sum(row["source_type"] == State.COMMON_SOURCE for row in logs) == 1
        assert sum(row["source_type"] == "auto_consumption" for row in logs) == len(reports)
        assert {row["source_id"] for row in logs} == {row["id"] for row in consumptions}
        assert logs[0]["balance_before"] == 100
        for previous, following in zip(logs, logs[1:]):
            assert following["balance_before"] == previous["balance_after"]
        assert logs[-1]["balance_after"] == (87 if first_commits else 89)

        receipts = db.execute(
            "SELECT detail FROM audit_logs WHERE action=? AND target_id=?",
            (State.COMMON_ACTION, order_id),
        ).fetchall()
        assert len(receipts) == 1
        receipt = json.loads(receipts[0]["detail"])
        assert receipt["work_record_id"] == (
            first_report_id if first_commits else second_report_id
        )
        assert receipt["allocations"][0]["consumption_id"] == common[0]["id"]
    finally:
        db.close()
