import uuid

from factory_production import ensure_process, ensure_process_version
from modules.db import get_db
from modules.services.position_access_service import PositionAccessService


def _published_position(db, process_ids, *, name_prefix="Access Position"):
    suffix = uuid.uuid4().hex[:8]
    position_id = db.execute(
        "INSERT INTO positions(name,description,status) VALUES (?, '', 'inactive')",
        (f"{name_prefix} {suffix}",),
    ).lastrowid
    root = db.execute(
        "SELECT position_code FROM positions WHERE id=?", (position_id,)
    ).fetchone()
    version_id = db.execute(
        "INSERT INTO position_versions("
        "position_id,version,position_code_snapshot,name,status,content_digest) "
        "VALUES (?,1,?,?,'draft',?)",
        (
            position_id,
            root["position_code"],
            f"{name_prefix} {suffix}",
            f"position-access-{suffix}",
        ),
    ).lastrowid
    for index, process_id in enumerate(process_ids, start=1):
        db.execute(
            "INSERT INTO position_version_processes("
            "position_version_id,process_id,seq_order) VALUES (?,?,?)",
            (version_id, process_id, index),
        )
        db.execute(
            "INSERT INTO position_processes(position_id,process_id) VALUES (?,?)",
            (position_id, process_id),
        )
    db.execute(
        "UPDATE position_versions SET status='published' WHERE id=?", (version_id,)
    )
    db.execute(
        "UPDATE positions SET status='active',lifecycle_status='active',"
        "current_effective_version_id=? WHERE id=?",
        (version_id, position_id),
    )
    return position_id, version_id


def _order_with_bound_process(db, process_id, process_version_id, status="producing"):
    suffix = uuid.uuid4().hex[:8]
    order_id = db.execute(
        "INSERT INTO orders(order_no,product_name,quantity,status) VALUES (?,?,1,?)",
        (f"ACCESS-{suffix}", "Access Product", status),
    ).lastrowid
    db.execute(
        "INSERT INTO order_processes("
        "order_id,process_id,process_version_id,seq_order,status) "
        "VALUES (?,?,?,1,'pending')",
        (order_id, process_id, process_version_id),
    )
    return order_id


def test_new_business_requires_published_active_position_and_process(client):
    with client.application.app_context():
        db = get_db()
        process_id = ensure_process(db, f"Access Process {uuid.uuid4().hex[:8]}")
        process_version_id = ensure_process_version(db, process_id)
        position_id, position_version_id = _published_position(db, [process_id])

        assert PositionAccessService.new_business_process_ids(
            position_id, db=db
        ) == [process_id]

        db.execute(
            "UPDATE position_versions SET status='retired' WHERE id=?",
            (position_version_id,),
        )
        db.execute(
            "UPDATE positions SET status='inactive',lifecycle_status='retired' "
            "WHERE id=?",
            (position_id,),
        )
        assert PositionAccessService.new_business_process_ids(position_id, db=db) == []

        draft_position_id = db.execute(
            "INSERT INTO positions(name,description,status) VALUES (?, '', 'inactive')",
            (f"Draft Position {uuid.uuid4().hex[:8]}",),
        ).lastrowid
        db.execute(
            "INSERT INTO position_processes(position_id,process_id) VALUES (?,?)",
            (draft_position_id, process_id),
        )
        assert PositionAccessService.new_business_process_ids(
            draft_position_id, db=db
        ) == []
        assert process_version_id is not None


def test_retired_process_is_available_only_for_bound_open_order(client):
    with client.application.app_context():
        db = get_db()
        process_id = ensure_process(db, f"WIP Process {uuid.uuid4().hex[:8]}")
        process_version_id = ensure_process_version(db, process_id)
        position_id, position_version_id = _published_position(db, [process_id])
        open_order_id = _order_with_bound_process(
            db, process_id, process_version_id, status="producing"
        )
        closed_order_id = _order_with_bound_process(
            db, process_id, process_version_id, status="completed"
        )

        db.execute(
            "UPDATE process_versions SET status='retired' WHERE id=?",
            (process_version_id,),
        )
        db.execute(
            "UPDATE processes SET status='inactive',lifecycle_status='retired' "
            "WHERE id=?",
            (process_id,),
        )
        db.execute(
            "UPDATE position_versions SET status='retired' WHERE id=?",
            (position_version_id,),
        )
        db.execute(
            "UPDATE positions SET status='inactive',lifecycle_status='retired' "
            "WHERE id=?",
            (position_id,),
        )

        assert PositionAccessService.new_business_process_ids(position_id, db=db) == []
        assert PositionAccessService.historical_wip_process_ids(
            position_id, open_order_id, db=db
        ) == [process_id]
        assert PositionAccessService.historical_wip_process_ids(
            position_id, closed_order_id, db=db
        ) == []


def test_effective_scope_merges_active_explicit_and_historical_position(client):
    with client.application.app_context():
        db = get_db()
        historical_process_id = ensure_process(
            db, f"Historical Process {uuid.uuid4().hex[:8]}"
        )
        explicit_process_id = ensure_process(
            db, f"Explicit Process {uuid.uuid4().hex[:8]}", 2
        )
        historical_version_id = ensure_process_version(db, historical_process_id)
        ensure_process_version(db, explicit_process_id)
        position_id, position_version_id = _published_position(
            db, [historical_process_id]
        )
        order_id = _order_with_bound_process(
            db, historical_process_id, historical_version_id
        )
        user_id = db.execute(
            "INSERT INTO users(username,password,name,role,employee_no,status,position_id) "
            "VALUES (?,?,?,?,?,'active',?)",
            (
                f"access-{uuid.uuid4().hex[:8]}",
                "hash",
                "Access Worker",
                "worker",
                f"ACCESS-{uuid.uuid4().hex[:8]}",
                position_id,
            ),
        ).lastrowid
        db.execute(
            "INSERT INTO user_processes(user_id,process_id) VALUES (?,?)",
            (user_id, explicit_process_id),
        )
        db.execute(
            "UPDATE process_versions SET status='retired' WHERE id=?",
            (historical_version_id,),
        )
        db.execute(
            "UPDATE processes SET status='inactive',lifecycle_status='retired' "
            "WHERE id=?",
            (historical_process_id,),
        )
        db.execute(
            "UPDATE position_versions SET status='retired' WHERE id=?",
            (position_version_id,),
        )
        db.execute(
            "UPDATE positions SET status='inactive',lifecycle_status='retired' "
            "WHERE id=?",
            (position_id,),
        )
        user = {
            "id": user_id,
            "position_id": position_id,
            "process_ids": "",
            "_permissions": [],
        }

        assert PositionAccessService.effective_user_process_ids(user, db=db) == [
            explicit_process_id
        ]
        assert PositionAccessService.effective_user_process_ids(
            user, order_id=order_id, db=db
        ) == sorted([historical_process_id, explicit_process_id])


def test_active_legacy_position_fallback_remains_available_during_cutover(client):
    with client.application.app_context():
        db = get_db()
        process_id = ensure_process(db, f"Legacy Access {uuid.uuid4().hex[:8]}")
        ensure_process_version(db, process_id)
        position_id = db.execute(
            "INSERT INTO positions(name,description,status) VALUES (?, '', 'active')",
            (f"Legacy Position {uuid.uuid4().hex[:8]}",),
        ).lastrowid
        db.execute(
            "INSERT INTO position_processes(position_id,process_id) VALUES (?,?)",
            (position_id, process_id),
        )

        assert PositionAccessService.new_business_process_ids(
            position_id, db=db
        ) == [process_id]
