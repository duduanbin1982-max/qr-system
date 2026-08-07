import json
import uuid

from factories import TEST_HASH
from modules.db import get_db
from modules.services.performance_scoring_policy import PerformanceScoringPolicy


MONTH = "2026-07"
PERIOD_START = "2026-07-01 07:00:00"
PERIOD_END = "2026-08-01 07:00:00"


def _login_actor(client, permissions, name="绩效范围用户"):
    suffix = uuid.uuid4().hex[:8]
    username = "performance-api-login-" + suffix
    with client.application.app_context():
        db = get_db()
        role_id = db.execute(
            "INSERT INTO roles (name,code,description,permissions,status,level) "
            "VALUES (?,?, '',?,'active',1)",
            (
                "绩效 API 角色-" + suffix,
                "performance_api_role_" + suffix,
                json.dumps(permissions),
            ),
        ).lastrowid
        user_id = db.execute(
            "INSERT INTO users (username,password,name,role,employee_no,status,"
            "password_version,must_change_password) "
            "VALUES (?,?,?,'worker',?,'active',2,0)",
            (username, TEST_HASH, name, "PERF-LOGIN-" + suffix.upper()),
        ).lastrowid
        db.execute(
            "INSERT INTO user_roles (user_id,role_id) VALUES (?,?)",
            (user_id, role_id),
        )
        db.commit()
    response = client.post(
        "/api/auth/login",
        json={"username": username, "password": "Test@1234"},
    )
    assert response.status_code == 200, response.get_json()
    payload = response.get_json()
    token = payload.get("token") or payload["user"]["token"]
    return user_id, {"Authorization": "Bearer " + token}


def _user(db, suffix, name, *, position_id=None, department_id=None):
    return db.execute(
        "INSERT INTO users (username,password,name,role,employee_no,status,"
        "position_id,department_id) VALUES (?,?,?,'worker',?,'active',?,?)",
        (
            "performance-api-" + suffix,
            "hash",
            name,
            "PERF-API-" + suffix.upper(),
            position_id,
            department_id,
        ),
    ).lastrowid


def _batch(db, key, version, *, legacy=False):
    preparer_id = _user(db, key + "-preparer", "绩效 API 制单人")
    approver_id = _user(db, key + "-approver", "绩效 API 批准人")
    batch_id = db.execute(
        "INSERT INTO performance_batches ("
        "production_month,version,period_start,period_end,source_cutoff_at,"
        "idempotency_key,prepared_by,prepared_by_name,legacy_imported"
        ") VALUES (?,?,?,?,?,?,?,?,?)",
        (
            MONTH,
            version,
            PERIOD_START,
            PERIOD_END,
            PERIOD_END,
            "performance-api:" + key,
            preparer_id,
            "绩效 API 制单人",
            int(legacy),
        ),
    ).lastrowid
    return batch_id


def _approve_batch(db, batch_id, *, supersedes_batch_id=None):
    batch = db.execute(
        "SELECT idempotency_key FROM performance_batches WHERE id=?",
        (batch_id,),
    ).fetchone()
    key = batch["idempotency_key"].removeprefix("performance-api:")
    approver_id = db.execute(
        "SELECT id FROM users WHERE username=?",
        ("performance-api-" + key + "-approver",),
    ).fetchone()["id"]
    db.execute(
        "UPDATE performance_batches SET status='supervisor_review' WHERE id=?",
        (batch_id,),
    )
    db.execute(
        "UPDATE performance_batches SET status='approval_pending',"
        "submitted_at=datetime('now','localtime') WHERE id=?",
        (batch_id,),
    )
    if supersedes_batch_id is not None:
        db.execute(
            "UPDATE performance_batches SET supersedes_batch_id=? WHERE id=?",
            (supersedes_batch_id, batch_id),
        )
        _supersede(db, supersedes_batch_id, batch_id)
    db.execute(
        "UPDATE performance_batches SET status='approved',approved_by=?,"
        "approved_by_name='绩效 API 批准人',approved_at=datetime('now','localtime') "
        "WHERE id=?",
        (approver_id, batch_id),
    )


def _score(
    db,
    batch_id,
    user_id,
    *,
    name,
    department_id,
    department_name,
    position_id,
    position_name,
    eligibility="eligible",
    total_score=88,
    warning_level="green",
    rank_no=1,
):
    return db.execute(
        "INSERT INTO performance_score_revisions ("
        "batch_id,user_id,revision,employee_name_snapshot,employee_no_snapshot,"
        "role_type_snapshot,department_id_snapshot,department_name_snapshot,"
        "position_id_snapshot,position_name_snapshot,eligibility_status,"
        "output_qty,report_count,work_days,output_score,quality_score,delivery_score,"
        "discipline_score,improvement_score,total_score,rank_no,rank_total,"
        "warning_level,warning_reason,score_details_json"
        ") VALUES (?,?,1,?,?,?,?,?,?,?,?,100,2,2,30,30,20,10,8,?, ?,2,?,'',?)",
        (
            batch_id,
            user_id,
            name,
            "SNAPSHOT-" + str(user_id),
            "worker",
            department_id,
            department_name,
            position_id,
            position_name,
            eligibility,
            total_score,
            rank_no,
            warning_level,
            json.dumps({"snapshot": True}, ensure_ascii=False),
        ),
    ).lastrowid


def _supersede(db, old_batch_id, new_batch_id):
    db.execute(
        "UPDATE performance_batches SET status='superseded',"
        "superseded_by_batch_id=? WHERE id=?",
        (new_batch_id, old_batch_id),
    )


def test_formal_scores_default_to_immutable_legacy_snapshot(client, auth_headers):
    with client.application.app_context():
        db = get_db()
        department_id = db.execute(
            "INSERT INTO departments (name,status) VALUES ('当前部门','active')"
        ).lastrowid
        position_id = db.execute(
            "INSERT INTO positions (name,status) VALUES ('当前岗位','active')"
        ).lastrowid
        worker_id = _user(
            db,
            "legacy-worker",
            "当前姓名",
            position_id=position_id,
            department_id=department_id,
        )
        legacy_id = _batch(db, "legacy", 1, legacy=True)
        _score(
            db,
            legacy_id,
            worker_id,
            name="历史姓名",
            department_id=department_id,
            department_name="历史部门",
            position_id=position_id,
            position_name="历史岗位",
        )
        _approve_batch(db, legacy_id)
        db.execute(
            "UPDATE users SET name='再次改名' WHERE id=?",
            (worker_id,),
        )
        db.commit()

    response = client.get(
        "/api/performance/scores?year_month=" + MONTH,
        headers=auth_headers,
    )

    assert response.status_code == 200, response.get_json()
    payload = response.get_json()
    assert payload["result_source"] == "legacy_v1"
    assert payload["batch_id"] == legacy_id
    assert payload["version"] == 1
    assert payload["batch_status"] == "approved"
    assert payload["period_start"] == PERIOD_START
    assert payload["period_end"] == PERIOD_END
    assert payload["items"][0]["user_name"] == "历史姓名"
    assert payload["items"][0]["position_name"] == "历史岗位"


def test_v2_query_flag_selects_approved_v2_while_default_keeps_superseded_legacy(
    client, auth_headers
):
    with client.application.app_context():
        db = get_db()
        department_id = db.execute(
            "INSERT INTO departments (name,status) VALUES ('切换部门','active')"
        ).lastrowid
        position_id = db.execute(
            "INSERT INTO positions (name,status) VALUES ('切换岗位','active')"
        ).lastrowid
        worker_id = _user(db, "switch-worker", "切换员工")
        legacy_id = _batch(db, "switch-legacy", 1, legacy=True)
        _score(
            db,
            legacy_id,
            worker_id,
            name="Legacy 员工",
            department_id=department_id,
            department_name="切换部门",
            position_id=position_id,
            position_name="切换岗位",
            total_score=70,
        )
        _approve_batch(db, legacy_id)
        v2_id = _batch(db, "switch-v2", 2)
        _score(
            db,
            v2_id,
            worker_id,
            name="V2 员工",
            department_id=department_id,
            department_name="切换部门",
            position_id=position_id,
            position_name="切换岗位",
            total_score=95,
        )
        _approve_batch(db, v2_id, supersedes_batch_id=legacy_id)
        db.commit()

    client.application.config["PERFORMANCE_LEDGER_V2_QUERY_ENABLED"] = False
    legacy = client.get(
        "/api/performance/scores?year_month=" + MONTH,
        headers=auth_headers,
    ).get_json()
    client.application.config["PERFORMANCE_LEDGER_V2_QUERY_ENABLED"] = True
    v2 = client.get(
        "/api/performance/scores?year_month=" + MONTH,
        headers=auth_headers,
    ).get_json()
    client.application.config.pop("PERFORMANCE_LEDGER_V2_QUERY_ENABLED", None)

    assert legacy["result_source"] == "legacy_v1"
    assert legacy["batch_id"] == legacy_id
    assert legacy["items"][0]["total_score"] == 70
    assert v2["result_source"] == "ledger_v2"
    assert v2["batch_id"] == v2_id
    assert v2["items"][0]["total_score"] == 95


def test_insufficient_data_has_no_grade_or_rank_and_is_excluded_from_summary(
    client, auth_headers
):
    with client.application.app_context():
        db = get_db()
        department_id = db.execute(
            "INSERT INTO departments (name,status) VALUES ('资格部门','active')"
        ).lastrowid
        position_id = db.execute(
            "INSERT INTO positions (name,status) VALUES ('资格岗位','active')"
        ).lastrowid
        eligible_id = _user(db, "eligible", "合格员工")
        insufficient_id = _user(db, "insufficient", "数据不足员工")
        batch_id = _batch(db, "eligibility", 1, legacy=True)
        _score(
            db,
            batch_id,
            eligible_id,
            name="合格员工",
            department_id=department_id,
            department_name="资格部门",
            position_id=position_id,
            position_name="资格岗位",
            total_score=80,
            warning_level="yellow",
        )
        _score(
            db,
            batch_id,
            insufficient_id,
            name="数据不足员工",
            department_id=department_id,
            department_name="资格部门",
            position_id=position_id,
            position_name="资格岗位",
            eligibility="insufficient_data",
            total_score=99,
            warning_level="green",
            rank_no=2,
        )
        _approve_batch(db, batch_id)
        db.commit()

    payload = client.get(
        "/api/performance/scores?year_month=" + MONTH,
        headers=auth_headers,
    ).get_json()

    insufficient = next(
        item for item in payload["items"] if item["user_id"] == insufficient_id
    )
    assert insufficient["total_score"] is None
    assert insufficient["warning_level"] is None
    assert insufficient["rank_no"] is None
    assert payload["summary"]["avg_score"] == 80
    assert payload["summary"]["green"] == 0
    assert payload["summary"]["yellow"] == 1
    assert payload["summary"]["eligible_count"] == 1
    assert payload["summary"]["insufficient_data_count"] == 1


def test_legacy_writes_are_closed_and_batch_create_returns_event_id(
    client, auth_headers
):
    for path in ("/api/performance/generate", "/api/performance/reviews"):
        response = client.post(path, json={"year_month": MONTH}, headers=auth_headers)
        assert response.status_code == 409
        assert response.get_json()["code"] == "LEGACY_LEDGER_READ_ONLY"

    with client.application.app_context():
        db = get_db()
        defaults = PerformanceScoringPolicy.rules()
        db.execute(
            "INSERT INTO performance_rule_versions ("
            "version_code,name,weights_json,warning_levels_json,scoring_parameters_json,"
            "status,effective_from_month,published_by,published_at"
            ") VALUES ('api-rule','API 规则',?,?,?,'published','2026-01',1,?)",
            (
                json.dumps(defaults["weights"], ensure_ascii=False),
                json.dumps(defaults["warning_levels"], ensure_ascii=False),
                json.dumps(
                    {
                        "work_days_target": defaults["work_days_target"],
                        "handoff": defaults["handoff"],
                        "improvement": defaults["improvement"],
                    },
                    ensure_ascii=False,
                ),
                "2026-06-01 08:00:00",
            ),
        )
        db.commit()

    created = client.post(
        "/api/performance/batches",
        json={
            "production_month": MONTH,
            "source_cutoff_at": PERIOD_END,
            "idempotency_key": "performance-api:create-batch",
            "revision_reason": "API 合同测试",
        },
        headers=auth_headers,
    )

    assert created.status_code == 200, created.get_json()
    assert created.get_json()["event_id"] > 0
    assert created.get_json()["row_version"] >= 1

    replay = client.post(
        "/api/performance/batches",
        json={
            "production_month": MONTH,
            "source_cutoff_at": PERIOD_END,
            "idempotency_key": "performance-api:create-batch",
            "revision_reason": "API 合同测试",
        },
        headers=auth_headers,
    )
    assert replay.status_code == 200, replay.get_json()
    assert replay.get_json()["idempotent_replay"] is True
    assert replay.get_json()["event_id"] == created.get_json()["event_id"]


def test_self_scope_is_applied_before_pagination_and_rejects_direct_cross_scope(
    client,
):
    actor_id, headers = _login_actor(client, ["performance:view_self"])
    with client.application.app_context():
        db = get_db()
        department_id = db.execute(
            "INSERT INTO departments (name,status) VALUES ('范围部门','active')"
        ).lastrowid
        position_id = db.execute(
            "INSERT INTO positions (name,status) VALUES ('范围岗位','active')"
        ).lastrowid
        outside_ids = [
            _user(db, "outside-" + str(index), "范围外员工-" + str(index))
            for index in range(3)
        ]
        batch_id = _batch(db, "scope", 1, legacy=True)
        for index, user_id in enumerate(outside_ids + [actor_id]):
            _score(
                db,
                batch_id,
                user_id,
                name="快照员工-" + str(index),
                department_id=department_id,
                department_name="范围部门",
                position_id=position_id,
                position_name="范围岗位",
                rank_no=index + 1,
            )
        _approve_batch(db, batch_id)
        db.commit()

    visible = client.get(
        "/api/performance/scores?year_month=" + MONTH + "&per_page=1",
        headers=headers,
    )
    assert visible.status_code == 200, visible.get_json()
    assert visible.get_json()["total"] == 1
    assert [item["user_id"] for item in visible.get_json()["items"]] == [actor_id]

    denied_user = client.get(
        "/api/performance/scores?year_month="
        + MONTH
        + "&user_id="
        + str(outside_ids[0]),
        headers=headers,
    )
    denied_department = client.get(
        "/api/performance/scores?year_month="
        + MONTH
        + "&department_id="
        + str(department_id),
        headers=headers,
    )
    assert denied_user.status_code == 403
    assert denied_department.status_code == 403

    batches = client.get("/api/performance/batches?per_page=1", headers=headers)
    detail = client.get(
        "/api/performance/batches/" + str(batch_id), headers=headers
    )
    assert batches.status_code == 403
    assert detail.status_code == 403

    reviewer_id, reviewer_headers = _login_actor(
        client, ["performance:review_department"], name="绩效部门复核人"
    )
    with client.application.app_context():
        db = get_db()
        db.execute(
            "INSERT INTO performance_department_scopes ("
            "user_id,department_id,granted_by,granted_by_name"
            ") VALUES (?,?,1,'测试管理员')",
            (reviewer_id, department_id),
        )
        db.commit()
    reviewer_batches = client.get(
        "/api/performance/batches?per_page=1", headers=reviewer_headers
    )
    reviewer_detail = client.get(
        "/api/performance/batches/" + str(batch_id), headers=reviewer_headers
    )
    assert reviewer_batches.status_code == 200, reviewer_batches.get_json()
    assert reviewer_batches.get_json()["total"] == 1
    assert reviewer_detail.status_code == 200, reviewer_detail.get_json()
    assert reviewer_detail.get_json()["scores_total"] == 4

    missing = client.get(
        "/api/performance/batches/999999", headers=reviewer_headers
    )
    invalid_month = client.get(
        "/api/performance/scores?year_month=2026-13", headers=headers
    )
    assert missing.status_code == 404
    assert invalid_month.status_code == 400
