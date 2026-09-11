import sqlite3

import pytest

from modules.app import app
from modules import db as db_module
from modules.domain.errors import ConflictError
from modules.migrations import run_migrations
from modules.services.historical_price_binding_service import HistoricalPriceBindingService
from modules.repositories.historical_price_binding_repository import (
    HistoricalPriceBindingRepository,
)
from modules.repositories.payroll_repository import PayrollRepository
from modules.services.payroll_service import PayrollCalculationService
from scripts.historical_price_binding_operations import (
    ProductionOperationError,
    _manifest_digest,
    apply_manifest,
    build_preflight,
)
from tests.factory_production import create_process_route, ensure_process
from tests.factory_auth import ensure_user
from tests.factory_auth import TEST_HASH, TEST_PASS


def _historical_route(db, route_id, process_id, version):
    process_version_id = db.execute(
        "SELECT current_effective_version_id FROM processes WHERE id=?", (process_id,)
    ).fetchone()[0]
    route = db.execute(
        "SELECT * FROM process_route_versions WHERE id=("
        "SELECT current_effective_version_id FROM process_routes WHERE id=?)",
        (route_id,),
    ).fetchone()
    route_version_id = db.execute(
        "INSERT INTO process_route_versions ("
        "process_route_id,version,route_code_snapshot,name,category,description,status,content_digest) "
        "VALUES (?,?,?,?,?,?,?,?)",
        (
            route_id, version, route["route_code_snapshot"], route["name"],
            route["category"], route["description"], "draft", route["content_digest"],
        ),
    ).lastrowid
    db.execute(
        "INSERT INTO process_route_version_items ("
        "route_version_id,process_id,process_version_id,seq_order,required_audit) "
        "SELECT ?,process_id,process_version_id,seq_order,required_audit "
        "FROM process_route_version_items WHERE route_version_id=?",
        (route_version_id, route["id"]),
    )
    db.execute(
        "UPDATE process_route_versions SET status='superseded' WHERE id=?",
        (route_version_id,),
    )
    return route_version_id, process_version_id


def _seed_database(tmp_path):
    path = tmp_path / "v083.db"
    db = sqlite3.connect(path)
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA foreign_keys=ON")
    run_migrations(db)
    operator_id = ensure_user(db, "v083-operator", "hash", "杜斌", "admin", "1000")
    approver_id = ensure_user(db, "v083-approver", "hash", "Dooley", "admin", "1004")

    process_a = ensure_process(db, "V083 唯一历史工序")
    route_a = create_process_route(db, [process_a], "V083 唯一路线")
    route_a_v2, process_a_v1 = _historical_route(db, route_a, process_a, 2)
    root_price = db.execute(
        "INSERT INTO route_price_versions ("
        "route_id,route_version_id,process_id,process_version_id,"
        "normal_unit_price_micros,rework_rate_basis_points,rework_rate_configured,"
        "valid_from,status,created_by_name,approved_by_name,approved_at) "
        "VALUES (?,?,?,?,10000,0,0,'2026-01-01 07:00:00','approved','legacy','legacy',"
        "'2026-01-01 07:00:00')",
        (
            route_a, db.execute(
                "SELECT current_effective_version_id FROM process_routes WHERE id=?", (route_a,)
            ).fetchone()[0], process_a, process_a_v1,
        ),
    ).lastrowid

    process_b = ensure_process(db, "V083 人工确认工序")
    route_b = create_process_route(db, [process_b], "V083 人工路线")
    route_b_v2, process_b_v1 = _historical_route(db, route_b, process_b, 2)

    order_ids = []
    for index, (order_no, route_id, route_version_id, process_id, process_version_id) in enumerate(
        (
            ("V083-CLONE-ORDER", route_a, route_a_v2, process_a, process_a_v1),
            ("V083-MANUAL-ORDER", route_b, route_b_v2, process_b, process_b_v1),
        ),
        start=1,
    ):
        order_id = db.execute(
            "INSERT INTO orders(order_no,product_name,route_id,route_version_id,route_name_snapshot) "
            "VALUES (?,? ,?,?,?)",
            (order_no, order_no, route_id, route_version_id, order_no),
        ).lastrowid
        db.execute(
            "INSERT INTO order_processes(order_id,process_id,process_version_id,seq_order,status) "
            "VALUES (?,?,?,1,'pending')",
            (order_id, process_id, process_version_id),
        )
        db.execute(
            "INSERT INTO work_records(order_id,process_id,user_id,type,status,quantity,"
            "route_id,route_version_id,process_version_id,created_at) "
            "VALUES (?,?,1,'normal','approved',?,?,?,?,'2026-07-15 08:00:00')",
            (order_id, process_id, index, route_id, route_version_id, process_version_id),
        )
        order_ids.append(order_id)
    db.commit()
    return path, db, root_price, order_ids, operator_id, approver_id


def _approved_manifest(report, key, items, operator_id=1, approver_id=2):
    manifest = dict(report)
    manifest["status"] = "approved"
    manifest["items"] = items
    manifest["approval"] = {
        "operator_id": operator_id,
        "operator_name": "杜斌",
        "approver_id": approver_id,
        "approver_name": "Dooley",
        "approved_at": "2026-09-07 10:00:00",
        "reason": "受控历史工价精确绑定修复",
        "idempotency_key": key,
    }
    manifest.pop("manifest_digest", None)
    manifest["manifest_digest"] = _manifest_digest(manifest)
    return manifest


def _prepare_http_database(tmp_path):
    """Seed a V083 database whose two admin users can authenticate over HTTP."""
    path, db, root_price, order_ids, operator_id, approver_id = _seed_database(tmp_path)
    db.execute("UPDATE users SET password=? WHERE id IN (?,?)", (TEST_HASH, operator_id, approver_id))
    db.commit()
    db.close()
    return path, root_price, order_ids, operator_id, approver_id


def _http_login(client, username):
    response = client.post(
        "/api/auth/login",
        json={"username": username, "password": TEST_PASS},
    )
    assert response.status_code == 200, response.get_json()
    token = (response.get_json() or {}).get("user", {}).get("token")
    assert token
    return {"Authorization": f"Bearer {token}"}


def test_v083_preflight_and_partial_apply_keep_manual_items_blocked(tmp_path):
    path, db, root_price, _, operator_id, approver_id = _seed_database(tmp_path)
    try:
        report = build_preflight(db)
        assert report["summary"]["affected_order_count"] == 2
        assert report["summary"]["clone_item_count"] == 1
        assert report["summary"]["manual_item_count"] == 1

        result = apply_manifest(
            path,
            _approved_manifest(report, "v083-clone-phase", report["items"], operator_id, approver_id),
        )
        assert result["status"] == "succeeded"
        assert len(result["created_price_version_ids"]) == 1
        assert len(result["deferred_manual_item_keys"]) == 1
        assert result["after"]["manual_item_count"] == 1

        partial = db.execute(
            "SELECT status FROM historical_price_binding_repair_runs "
            "WHERE idempotency_key='v083-clone-phase'"
        ).fetchone()[0]
        assert partial == "partially_applied"
        exact = db.execute(
            "SELECT route_version_id,process_version_id,normal_unit_price_micros "
            "FROM route_price_versions WHERE historical_price_repair_item_id IS NOT NULL"
        ).fetchone()
        assert exact["normal_unit_price_micros"] == 10000
        assert exact["route_version_id"] != db.execute(
            "SELECT route_version_id FROM route_price_versions WHERE id=?", (root_price,)
        ).fetchone()[0]
    finally:
        db.close()


def test_v083_manual_completion_requires_reason_and_cannot_use_similarity(tmp_path):
    path, db, _, _, operator_id, approver_id = _seed_database(tmp_path)
    try:
        report = build_preflight(db)
        apply_manifest(path, _approved_manifest(report, "v083-clone-phase-2", report["items"], operator_id, approver_id))
        pending = build_preflight(db)
        manual = next(item for item in pending["items"] if item["action"] == "manual")

        incomplete = dict(manual)
        incomplete.update(
            normal_unit_price_micros=7777,
            rework_rate_basis_points=0,
            rework_rate_configured=0,
            valid_from="2026-01-01 07:00:00",
        )
        with pytest.raises(Exception, match="manual decision reason"):
            apply_manifest(
                path,
                _approved_manifest(pending, "v083-manual-incomplete", [incomplete], operator_id, approver_id),
            )

        complete = dict(incomplete)
        complete["item_key"] = manual["item_key"] + ":confirmed"
        complete["manual_parent_item_key"] = manual["item_key"]
        complete["price_idempotency_key"] = "historical-price:" + complete["item_key"]
        complete["item_digest"] = ""
        complete.update(
            manual_decision_reason="负责人确认该历史工序单价为 7777 微单位",
            manual_decision_by=1,
            manual_decision_at="2026-09-07 10:05:00",
        )
        from scripts.historical_price_binding_operations import _digest
        complete["item_digest"] = _digest(complete)
        result = apply_manifest(
            path,
            _approved_manifest(pending, "v083-manual-complete", [complete], operator_id, approver_id),
        )
        assert result["after"]["missing_work_record_count"] == 0
        assert db.execute(
            "SELECT status FROM historical_price_binding_repair_runs "
            "WHERE idempotency_key='v083-manual-complete'"
        ).fetchone()[0] == "applied"
    finally:
        db.close()


def test_v083_retains_overlap_and_exact_binding_guards(tmp_path):
    path, db, root_price, _, _, _ = _seed_database(tmp_path)
    try:
        with pytest.raises(sqlite3.IntegrityError, match="overlap"):
            db.execute(
                "INSERT INTO route_price_versions(route_id,route_version_id,process_id,"
                "process_version_id,normal_unit_price_micros,valid_from,status) "
                "SELECT route_id,route_version_id,process_id,process_version_id,9999,"
                "'2026-02-01 07:00:00','approved' FROM route_price_versions WHERE id=?",
                (root_price,),
            )
        db.rollback()
        with pytest.raises(sqlite3.IntegrityError):
            db.execute(
                "INSERT INTO route_price_versions(route_id,process_id,normal_unit_price_micros,"
                "valid_from,status) SELECT route_id,process_id,9999,'2026-02-01 07:00:00',"
                "'approved' FROM route_price_versions WHERE id=?",
                (root_price,),
            )
    finally:
        db.close()


def test_v083_rejects_unknown_or_mismatched_approval_identity_before_write(tmp_path):
    path, db, _, _, operator_id, approver_id = _seed_database(tmp_path)
    try:
        report = build_preflight(db)
        manifest = _approved_manifest(report, "v083-invalid-actor", report["items"], operator_id, approver_id)
        manifest["approval"]["operator_id"] = 999999
        manifest["manifest_digest"] = _manifest_digest(manifest)
        with pytest.raises(ProductionOperationError, match="operator database user does not exist"):
            apply_manifest(path, manifest)
        assert db.execute(
            "SELECT count(*) FROM historical_price_binding_repair_runs"
        ).fetchone()[0] == 0

        manifest = _approved_manifest(report, "v083-mismatched-actor", report["items"], operator_id, approver_id)
        manifest["approval"]["operator_name"] = "错误姓名"
        manifest["manifest_digest"] = _manifest_digest(manifest)
        with pytest.raises(ProductionOperationError, match="operator name does not match"):
            apply_manifest(path, manifest)
        assert db.execute(
            "SELECT count(*) FROM historical_price_binding_repair_runs"
        ).fetchone()[0] == 0
    finally:
        db.close()


def test_v0831_no_settlement_keeps_fact_without_price_and_is_idempotent(tmp_path):
    path, db, _, _, operator_id, approver_id = _seed_database(tmp_path)
    try:
        report = build_preflight(db)
        apply_manifest(
            path,
            _approved_manifest(report, "v0831-clone-before-no-settlement", report["items"], operator_id, approver_id),
        )
        pending = build_preflight(db)
        manual = next(item for item in pending["items"] if item["action"] == "manual")
        decision = dict(
            manual,
            settlement_decision="no_settlement",
            manual_decision_reason="试运行历史报工不进入应付工资结算",
            manual_decision_by=operator_id,
            manual_decision_by_name="杜斌",
            manual_decision_at="2026-09-07 10:10:00",
        )
        decision["item_digest"] = __import__(
            "scripts.historical_price_binding_operations", fromlist=["_digest"]
        )._digest(decision)
        manifest = _approved_manifest(
            pending, "v0831-no-settlement", [decision], operator_id, approver_id
        )
        result = apply_manifest(path, manifest)
        assert result["created_price_version_ids"] == [
            {"decision": "no_settlement", "item_key": manual["item_key"]}
        ]
        assert result["after"]["missing_work_record_count"] == 0
        assert db.execute(
            "SELECT COUNT(*) FROM route_price_versions "
            "WHERE route_version_id=? AND process_version_id=?",
            (manual["target_route_version_id"], manual["target_process_version_id"]),
        ).fetchone()[0] == 0
        settlement = db.execute(
            "SELECT decision,price_version_id,reason FROM historical_price_binding_settlements "
            "WHERE repair_item_id=(SELECT id FROM historical_price_binding_repair_items WHERE item_key=?)",
            (manual["item_key"],),
        ).fetchone()
        assert settlement["decision"] == "no_settlement"
        assert settlement["price_version_id"] is None
        assert "不进入应付工资" in settlement["reason"]
        assert db.execute(
            "SELECT COUNT(*) FROM historical_price_binding_settlement_facts"
        ).fetchone()[0] == 1
        assert HistoricalPriceBindingRepository.list_manual_items(db) == []

        replay = apply_manifest(path, manifest)
        assert replay["replayed"] is True
        with pytest.raises(sqlite3.IntegrityError, match="immutable"):
            db.execute(
                "UPDATE historical_price_binding_settlements SET reason='篡改'"
            )
        db.rollback()
        with pytest.raises(sqlite3.IntegrityError, match="cannot be deleted"):
            db.execute("DELETE FROM historical_price_binding_settlement_facts")
        db.rollback()

        work_id = db.execute(
            "SELECT work_record_id FROM historical_price_binding_settlement_facts LIMIT 1"
        ).fetchone()[0]
        row = next(
            row for row in PayrollRepository.source_work_records(
                "2026-07-01 07:00:00", "2026-08-01 07:00:00", "2026-09-08 00:00:00", db
            ) if row["work_record_id"] == work_id
        )
        price, exception, error = PayrollCalculationService._resolve(
            row, {"id": 901}, db
        )
        assert exception is None and error is None
        assert price["normal_unit_price_micros"] == 0
        assert price["price_version_id"] is None
        assert price["resolution_method"] == "historical_no_settlement"
    finally:
        db.close()


def test_v0831_zero_price_creates_exact_zero_price_and_payroll_resolution(tmp_path):
    path, db, _, _, operator_id, approver_id = _seed_database(tmp_path)
    try:
        report = build_preflight(db)
        apply_manifest(
            path,
            _approved_manifest(report, "v0831-clone-before-zero-price", report["items"], operator_id, approver_id),
        )
        pending = build_preflight(db)
        parent = next(item for item in pending["items"] if item["action"] == "manual")
        zero = dict(
            parent,
            item_key=parent["item_key"] + ":zero-price",
            manual_parent_item_key=parent["item_key"],
            settlement_decision="zero_price",
            normal_unit_price_micros=0,
            rework_rate_basis_points=0,
            rework_rate_configured=0,
            valid_from="2026-01-01 07:00:00",
            valid_to=None,
            manual_decision_reason="试运行期间纳入台账但按零工价处理",
            manual_decision_by=operator_id,
            manual_decision_by_name="杜斌",
            manual_decision_at="2026-09-07 10:15:00",
            price_idempotency_key="historical-price:v0831-zero-price",
        )
        from scripts.historical_price_binding_operations import _digest
        zero["item_digest"] = _digest(zero)
        result = apply_manifest(
            path,
            _approved_manifest(pending, "v0831-zero-price", [zero], operator_id, approver_id),
        )
        assert len(result["created_price_version_ids"]) == 1
        price = db.execute(
            "SELECT id,normal_unit_price_micros,status FROM route_price_versions "
            "WHERE historical_price_repair_item_id IS NOT NULL AND normal_unit_price_micros=0"
        ).fetchone()
        assert price["normal_unit_price_micros"] == 0
        assert price["status"] == "approved"
        settlement = db.execute(
            "SELECT decision,price_version_id FROM historical_price_binding_settlements "
            "WHERE price_version_id=?",
            (price["id"],),
        ).fetchone()
        assert settlement["decision"] == "zero_price"
        assert settlement["price_version_id"] == price["id"]
        assert build_preflight(db)["summary"]["missing_work_record_count"] == 0

        work_id = db.execute(
            "SELECT work_record_id FROM historical_price_binding_settlement_facts LIMIT 1"
        ).fetchone()[0]
        row = next(
            row for row in PayrollRepository.source_work_records(
                "2026-07-01 07:00:00", "2026-08-01 07:00:00", "2026-09-08 00:00:00", db
            ) if row["work_record_id"] == work_id
        )
        resolved, exception, error = PayrollCalculationService._resolve(
            row, {"id": 902}, db
        )
        assert exception is None and error is None
        assert resolved["normal_unit_price_micros"] == 0
        assert resolved["price_version_id"] == price["id"]
        assert resolved["resolution_method"] == "historical_zero_price"
    finally:
        db.close()


def test_manual_review_service_uses_business_fields_and_applies_exact_price(tmp_path, monkeypatch):
    """The manual evidence key must never become a payroll UI input."""
    path, db, _, _, operator_id, approver_id = _seed_database(tmp_path)
    try:
        report = build_preflight(db)
        db.commit()
        db.close()
        apply_manifest(
            path,
            _approved_manifest(
                report, "v083-service-clone-phase", report["items"], operator_id, approver_id
            ),
        )
        monkeypatch.setattr(db_module, "DB_PATH", str(path))

        with app.app_context():
            listed = HistoricalPriceBindingService.list_manual_reviews()
            assert len(listed["items"]) == 1
            review = listed["items"][0]
            assert review["affected_orders"] == [{
                "order_id": review["affected_orders"][0]["order_id"],
                "order_no": "V083-MANUAL-ORDER",
                "product_code": "",
                "product_name": "V083-MANUAL-ORDER",
                "work_record_count": 1,
                "quantity": 2,
                "first_work_at": "2026-07-15 08:00:00",
                "last_work_at": "2026-07-15 08:00:00",
            }]
            assert review["route"]["name"] == "V083 人工路线"
            assert review["process"]["name"] == "V083 人工确认工序"
            assert "manual:" not in str(listed)
            assert "item_key" not in str(listed)

            draft_result = HistoricalPriceBindingService.create_draft(
                review["review_id"],
                {
                    "normal_unit_price": "0.7777",
                    "rework_rate_configured": False,
                    "valid_from": "2026-07-01 07:00:00",
                    "confirmation_reason": "负责人核对历史报工后确认单价",
                    "idempotency_key": "v083-service-manual-draft",
                },
                {"id": operator_id, "name": "杜斌"},
            )
            draft = draft_result["draft"]
            assert draft["status"] == "draft"
            assert "idempotency_key" not in draft
            assert "request_digest" not in draft

            with pytest.raises(Exception, match="必须不同"):
                HistoricalPriceBindingService.approve_draft(
                    draft["id"],
                    {"row_version": draft["row_version"], "idempotency_key": "v083-service-self-approve"},
                    {"id": operator_id, "name": "杜斌"},
                )

            approved = HistoricalPriceBindingService.approve_draft(
                draft["id"],
                {"row_version": draft["row_version"], "idempotency_key": "v083-service-manual-approve"},
                {"id": approver_id, "name": "Dooley"},
            )
            assert approved["draft"]["status"] == "approved"
            assert approved["price_version_id"] > 0
            assert HistoricalPriceBindingService.list_manual_reviews()["items"] == []
    finally:
        try:
            db.close()
        except Exception:
            pass


def test_historical_price_manual_review_http_contract_hides_internal_keys(tmp_path, monkeypatch, client):
    """The HTTP facade exposes business context, never the manual evidence key."""
    path, _, _, operator_id, approver_id = _prepare_http_database(tmp_path)
    monkeypatch.setattr(db_module, "DB_PATH", str(path))

    # Complete the automated clone phase so the remaining item is a manual review.
    seed_db = sqlite3.connect(path)
    seed_db.row_factory = sqlite3.Row
    report = build_preflight(seed_db)
    seed_db.close()
    apply_manifest(path, _approved_manifest(report, "v083-http-clone", report["items"], operator_id, approver_id))

    headers = _http_login(client, "v083-operator")
    response = client.get("/api/historical-price-binding-repairs/manual-reviews", headers=headers)
    assert response.status_code == 200, response.get_json()
    payload = response.get_json()
    assert len(payload["items"]) == 1
    review = payload["items"][0]
    assert review["affected_orders"][0]["order_no"] == "V083-MANUAL-ORDER"
    assert review["route"]["name"] == "V083 人工路线"
    assert review["process"]["name"] == "V083 人工确认工序"
    serialized = str(payload)
    for forbidden in ("manual:", "item_key", "request_digest", "idempotency_key"):
        assert forbidden not in serialized


def test_historical_price_manual_draft_http_schema_and_permissions(tmp_path, monkeypatch, client):
    path, _, _, operator_id, approver_id = _prepare_http_database(tmp_path)
    monkeypatch.setattr(db_module, "DB_PATH", str(path))
    seed_db = sqlite3.connect(path)
    seed_db.row_factory = sqlite3.Row
    report = build_preflight(seed_db)
    seed_db.close()
    apply_manifest(path, _approved_manifest(report, "v083-http-schema", report["items"], operator_id, approver_id))

    headers = _http_login(client, "v083-operator")
    review = client.get(
        "/api/historical-price-binding-repairs/manual-reviews", headers=headers
    ).get_json()["items"][0]
    endpoint = f"/api/historical-price-binding-repairs/manual-reviews/{review['review_id']}/drafts"
    valid = {
        "normal_unit_price": "0.8888",
        "valid_from": "2026-07-01 07:00:00",
        "confirmation_reason": "HTTP 层人工核对",
        "idempotency_key": "v083-http-draft-1",
    }
    invalid = dict(valid, item_key="manual:72:10")
    invalid_response = client.post(endpoint, headers=headers, json=invalid)
    assert invalid_response.status_code == 400
    assert "不允许的字段" in invalid_response.get_json()["error"]

    # A valid preparer request succeeds, while the same actor cannot approve it.
    created = client.post(endpoint, headers=headers, json=valid)
    assert created.status_code == 200, created.get_json()
    draft = created.get_json()["draft"]
    approve_endpoint = f"/api/historical-price-binding-repair-drafts/{draft['id']}/approve"
    same_actor = client.post(
        approve_endpoint,
        headers=headers,
        json={"row_version": draft["row_version"], "idempotency_key": "v083-http-self-approve"},
    )
    assert same_actor.status_code == 403
    assert "必须不同" in same_actor.get_json()["error"]

    # Explicitly exercise the route permission boundary as well.
    import modules.routes.payroll as payroll_routes

    monkeypatch.setattr(payroll_routes, "has_permission", lambda _user, _permission: False)
    denied = client.get("/api/historical-price-binding-repairs/manual-reviews", headers=headers)
    assert denied.status_code == 403


def test_historical_price_manual_approval_http_reports_interval_conflict(tmp_path, monkeypatch, client):
    path, _, _, operator_id, approver_id = _prepare_http_database(tmp_path)
    monkeypatch.setattr(db_module, "DB_PATH", str(path))
    seed_db = sqlite3.connect(path)
    seed_db.row_factory = sqlite3.Row
    report = build_preflight(seed_db)
    seed_db.close()
    apply_manifest(path, _approved_manifest(report, "v083-http-overlap", report["items"], operator_id, approver_id))

    headers_operator = _http_login(client, "v083-operator")
    review = client.get(
        "/api/historical-price-binding-repairs/manual-reviews", headers=headers_operator
    ).get_json()["items"][0]
    draft_response = client.post(
        f"/api/historical-price-binding-repairs/manual-reviews/{review['review_id']}/drafts",
        headers=headers_operator,
        json={
            "normal_unit_price": "0.9999",
            "valid_from": "2026-07-01 07:00:00",
            "valid_to": "2026-07-20 07:00:00",
            "confirmation_reason": "HTTP 层重叠区间核对",
            "idempotency_key": "v083-http-overlap-draft",
        },
    )
    assert draft_response.status_code == 200, draft_response.get_json()
    draft = draft_response.get_json()["draft"]

    # The database trigger is covered by the repository/migration test above;
    # this HTTP test isolates the adapter contract and verifies that a domain
    # interval conflict is exposed as a 409 with a user-facing message.
    def raise_overlap(*_args, **_kwargs):
        raise ConflictError(
            "该路线版本和工序版本在所填生效区间已有已批准工价；请调整生效区间，不会自动覆盖历史工价"
        )

    monkeypatch.setattr(
        "modules.services.historical_price_binding_service.HistoricalPriceBindingService._assert_interval_available",
        staticmethod(raise_overlap),
    )

    headers_approver = _http_login(client, "v083-approver")
    approval = client.post(
        f"/api/historical-price-binding-repair-drafts/{draft['id']}/approve",
        headers=headers_approver,
        json={"row_version": draft["row_version"], "idempotency_key": "v083-http-overlap-approve"},
    )
    assert approval.status_code == 409
    assert "已有已批准工价" in approval.get_json()["error"]
