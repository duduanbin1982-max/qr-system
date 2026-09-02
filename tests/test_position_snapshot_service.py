import uuid

from modules.db import get_db
from modules.repositories.performance_assignment_repository import (
    PerformanceAssignmentRepository,
)
from modules.services.position_snapshot_service import PositionSnapshotService


def _position_version(db, position_id, version, name, status, effective_from):
    root = db.execute(
        "SELECT position_code FROM positions WHERE id=?", (position_id,)
    ).fetchone()
    version_id = db.execute(
        "INSERT INTO position_versions("
        "position_id,version,position_code_snapshot,name,status,effective_from,"
        "content_digest) VALUES (?,?,?,?,?,?,?)",
        (
            position_id,
            version,
            root["position_code"],
            name,
            "draft",
            effective_from,
            f"snapshot-{position_id}-{version}",
        ),
    ).lastrowid
    db.execute(
        "UPDATE position_versions SET status=? WHERE id=?", (status, version_id)
    )
    return version_id


def _assigned_user(db, position_id, position_version_id, position_name):
    suffix = uuid.uuid4().hex[:8]
    user_id = db.execute(
        "INSERT INTO users(username,password,name,role,employee_no,status,position_id) "
        "VALUES (?,?,?,?,?,'active',?)",
        (
            f"snapshot-{suffix}",
            "hash",
            "Snapshot Worker",
            "worker",
            f"SNAP-{suffix}",
            position_id,
        ),
    ).lastrowid
    PerformanceAssignmentRepository.create_assignment(
        {
            "user_id": user_id,
            "employee_name_snapshot": "Snapshot Worker",
            "employee_no_snapshot": f"SNAP-{suffix}",
            "position_id": position_id,
            "position_version_id": position_version_id,
            "position_name_snapshot": position_name,
            "department_id": None,
            "department_name_snapshot": "",
            "valid_from": "2026-08-01 07:00:00",
            "valid_to": "",
            "source_type": "test",
            "source_key": f"snapshot-assignment-{suffix}",
        },
        db=db,
    )
    return user_id


def test_name_publish_splits_only_open_active_assignments(client):
    with client.application.app_context():
        db = get_db()
        position_id = db.execute(
            "INSERT INTO positions(name,description,status) VALUES ('Old Position','', 'active')"
        ).lastrowid
        old_version_id = _position_version(
            db,
            position_id,
            1,
            "Old Position",
            "published",
            "2026-08-01 07:00:00",
        )
        user_id = _assigned_user(
            db, position_id, old_version_id, "Old Position"
        )
        db.execute(
            "UPDATE position_versions SET status='superseded',"
            "effective_to='2026-08-20 10:00:00' WHERE id=?",
            (old_version_id,),
        )
        new_version_id = _position_version(
            db,
            position_id,
            2,
            "New Position",
            "published",
            "2026-08-20 10:00:00",
        )

        count = PositionSnapshotService.apply_published_name(
            position_id,
            new_version_id,
            "New Position",
            "2026-08-20 10:00:00",
            db,
        )
        rows = PerformanceAssignmentRepository.list_for_user(user_id, db=db)

    assert count == 1
    assert [row["position_name_snapshot"] for row in rows] == [
        "Old Position",
        "New Position",
    ]
    assert [row["position_version_id"] for row in rows] == [
        old_version_id,
        new_version_id,
    ]
    assert rows[0]["valid_to"] == rows[1]["valid_from"] == "2026-08-20 10:00:00"
    assert rows[1]["source_type"] == "position_version_published"


def test_unchanged_name_does_not_split_assignment(client):
    with client.application.app_context():
        db = get_db()
        position_id = db.execute(
            "INSERT INTO positions(name,description,status) VALUES ('Stable Position','', 'active')"
        ).lastrowid
        version_id = _position_version(
            db,
            position_id,
            1,
            "Stable Position",
            "published",
            "2026-08-01 07:00:00",
        )
        user_id = _assigned_user(
            db, position_id, version_id, "Stable Position"
        )

        count = PositionSnapshotService.apply_published_name(
            position_id,
            version_id,
            "Stable Position",
            "2026-08-20 10:00:00",
            db,
        )

        assert count == 0
        assert len(PerformanceAssignmentRepository.list_for_user(user_id, db=db)) == 1


def test_version_at_uses_half_open_published_intervals(client):
    with client.application.app_context():
        db = get_db()
        position_id = db.execute(
            "INSERT INTO positions(name,description,status) VALUES ('Version At','', 'active')"
        ).lastrowid
        first_id = _position_version(
            db,
            position_id,
            1,
            "Version At V1",
            "published",
            "2026-08-01 07:00:00",
        )
        db.execute(
            "UPDATE position_versions SET status='superseded',"
            "effective_to='2026-08-20 10:00:00' WHERE id=?",
            (first_id,),
        )
        second_id = _position_version(
            db,
            position_id,
            2,
            "Version At V2",
            "published",
            "2026-08-20 10:00:00",
        )

        before = PositionSnapshotService.version_at(
            position_id, "2026-08-20 09:59:59", db=db
        )
        boundary = PositionSnapshotService.version_at(
            position_id, "2026-08-20 10:00:00", db=db
        )
        unknown = PositionSnapshotService.version_at(
            position_id, "2026-07-01 07:00:00", db=db
        )

    assert before["id"] == first_id
    assert boundary["id"] == second_id
    assert unknown is None
