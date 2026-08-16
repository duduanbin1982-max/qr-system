import sqlite3

import pytest

from modules.domain.errors import ConflictError
from modules.domain.process_versioning import (
    ProcessVersionStaleError,
    RouteVersionStaleError,
)
from modules.migration_process_versioning import m060_process_master_versioning
from modules.repositories.master_data_lifecycle_repository import (
    MasterDataLifecycleRepository,
)
from modules.repositories.master_data_release_repository import (
    MasterDataReleaseRepository,
)
from modules.repositories.process_version_repository import ProcessVersionRepository
from modules.repositories.route_version_repository import RouteVersionRepository


def _legacy_schema(db):
    db.executescript(
        """
        CREATE TABLE users (
            id INTEGER PRIMARY KEY,
            name TEXT NOT NULL DEFAULT ''
        );
        CREATE TABLE processes (
            id INTEGER PRIMARY KEY,
            name TEXT NOT NULL,
            description TEXT DEFAULT '',
            category TEXT DEFAULT '机加工',
            seq_order INTEGER DEFAULT 0,
            status TEXT DEFAULT 'active',
            created_at TEXT DEFAULT '2026-01-01 08:00:00',
            updated_at TEXT DEFAULT ''
        );
        CREATE TABLE process_routes (
            id INTEGER PRIMARY KEY,
            name TEXT NOT NULL,
            description TEXT DEFAULT '',
            category TEXT DEFAULT '机加工',
            status TEXT DEFAULT 'active',
            created_at TEXT DEFAULT '2026-01-01 08:00:00',
            updated_at TEXT DEFAULT ''
        );
        CREATE TABLE process_route_items (
            id INTEGER PRIMARY KEY,
            route_id INTEGER NOT NULL,
            process_id INTEGER NOT NULL,
            seq_order INTEGER DEFAULT 0,
            is_required INTEGER DEFAULT 1,
            required_audit INTEGER DEFAULT 0,
            FOREIGN KEY(route_id) REFERENCES process_routes(id),
            FOREIGN KEY(process_id) REFERENCES processes(id)
        );
        CREATE TABLE route_price_versions (
            id INTEGER PRIMARY KEY,
            route_id INTEGER NOT NULL,
            process_id INTEGER NOT NULL
        );
        INSERT INTO users(id,name) VALUES (10,'制单人'),(11,'批准人');
        INSERT INTO processes
            (id,name,description,category,seq_order,status,created_at)
        VALUES
            (1,'车削','车床加工','机加工',10,'active','2026-01-02 08:00:00'),
            (2,'铣削','铣床加工','机加工',20,'active','2026-01-03 08:00:00');
        INSERT INTO process_routes
            (id,name,description,category,status,created_at)
        VALUES
            (3,'机加工路线','车铣路线','机加工','active','2026-02-01 08:00:00');
        INSERT INTO process_route_items
            (id,route_id,process_id,seq_order,is_required,required_audit)
        VALUES (31,3,1,10,1,1);
        INSERT INTO route_price_versions(id,route_id,process_id) VALUES (41,3,1);
        PRAGMA user_version=59;
        """
    )


def _repository_db(path=":memory:"):
    db = sqlite3.connect(path)
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA foreign_keys=ON")
    _legacy_schema(db)
    m060_process_master_versioning(db)
    db.commit()
    return db


def _process_revision_payload(key, **overrides):
    payload = {
        "process_code_snapshot": "PROC-0001",
        "name": "精车",
        "category": "机加工",
        "description": "精车修订",
        "seq_order": 10,
        "status": "draft",
        "supersedes_version_id": 1,
        "revision_reason": "更新工艺说明",
        "impact_digest": "impact-v2",
        "content_digest": "content-v2",
        "created_by": 10,
        "created_by_name": "制单人",
        "idempotency_key": key,
    }
    payload.update(overrides)
    return payload


def _route_revision_payload(key, **overrides):
    payload = {
        "route_code_snapshot": "ROUTE-0003",
        "name": "机加工路线 V2",
        "category": "机加工",
        "description": "增加铣削节点",
        "status": "draft",
        "supersedes_version_id": 1,
        "revision_reason": "调整路线节点",
        "impact_digest": "route-impact-v2",
        "content_digest": "route-content-v2",
        "created_by": 10,
        "created_by_name": "制单人",
        "idempotency_key": key,
    }
    payload.update(overrides)
    return payload


def test_exact_root_current_version_number_and_history_queries():
    db = _repository_db()
    try:
        process_root = ProcessVersionRepository.root(1, db=db)
        process_current = ProcessVersionRepository.current_version(1, db=db)
        process_v1 = ProcessVersionRepository.version_by_number(1, 1, db=db)
        process_history = ProcessVersionRepository.list_versions(1, db=db)

        assert process_root["process_code"] == "PROC-0001"
        assert process_current["id"] == process_root["current_effective_version_id"]
        assert process_v1 == process_current
        assert [item["version"] for item in process_history] == [1]

        route_root = RouteVersionRepository.root(3, db=db)
        route_current = RouteVersionRepository.current_version(3, db=db)
        route_v1 = RouteVersionRepository.version_by_number(3, 1, db=db)
        route_history = RouteVersionRepository.list_versions(3, db=db)

        assert route_root["route_code"] == "ROUTE-0003"
        assert route_current["id"] == route_root["current_effective_version_id"]
        assert route_v1["id"] == route_current["id"]
        assert [item["version"] for item in route_history] == [1]
        assert route_history[0]["items"][0]["legacy_route_item_id"] == 31
    finally:
        db.close()


def test_process_revision_allocates_next_version_atomically_and_is_idempotent():
    db = _repository_db()
    try:
        first = ProcessVersionRepository.create_revision(
            1, _process_revision_payload("process-revision-1"), db
        )
        replay = ProcessVersionRepository.create_revision(
            1,
            _process_revision_payload("process-revision-1", name="不应覆盖原内容"),
            db,
        )

        assert first["version"] == 2
        assert replay == first
        assert db.execute(
            "SELECT COUNT(*) FROM process_versions WHERE process_id=1 AND version=2"
        ).fetchone()[0] == 1

        ProcessVersionRepository.transition_version(
            first["id"], "draft", 0, "cancelled", {}, db
        )
        second = ProcessVersionRepository.create_revision(
            1,
            _process_revision_payload(
                "process-revision-2", supersedes_version_id=first["id"]
            ),
            db,
        )
        assert second["version"] == 3
    finally:
        db.close()


def test_route_revision_items_are_prefetched_in_stable_order_and_idempotent():
    db = _repository_db()
    try:
        process_v1 = ProcessVersionRepository.version_by_number(1, 1, db=db)
        process_v2 = ProcessVersionRepository.version_by_number(2, 1, db=db)
        items = [
            {
                "process_id": 2,
                "process_version_id": process_v2["id"],
                "seq_order": 20,
                "is_required": 1,
                "required_audit": 0,
            },
            {
                "process_id": 1,
                "process_version_id": process_v1["id"],
                "seq_order": 10,
                "is_required": 1,
                "required_audit": 1,
            },
        ]

        created = RouteVersionRepository.create_revision(
            3, _route_revision_payload("route-revision-1"), items, db
        )
        replay = RouteVersionRepository.create_revision(
            3, _route_revision_payload("route-revision-1"), [], db
        )
        loaded = RouteVersionRepository.version(created["id"], db=db)
        history = RouteVersionRepository.list_versions(3, db=db)

        assert replay["id"] == created["id"]
        assert [item["seq_order"] for item in loaded["items"]] == [10, 20]
        assert history[-1]["id"] == created["id"]
        assert [item["process_id"] for item in history[-1]["items"]] == [1, 2]
    finally:
        db.close()


def test_route_item_failure_is_not_mistaken_for_an_idempotent_replay():
    db = _repository_db()
    try:
        process_v1 = ProcessVersionRepository.version_by_number(1, 1, db=db)
        db.execute("BEGIN IMMEDIATE")
        with pytest.raises(ConflictError, match="节点写入冲突"):
            RouteVersionRepository.create_revision(
                3,
                _route_revision_payload("invalid-route-items"),
                [
                    {
                        "process_id": 1,
                        "process_version_id": process_v1["id"],
                        "seq_order": 10,
                    },
                    {
                        "process_id": 1,
                        "process_version_id": process_v1["id"],
                        "seq_order": 20,
                    },
                ],
                db,
            )
        db.rollback()

        assert RouteVersionRepository.version_by_idempotency_key(
            "invalid-route-items", db=db
        ) is None
    finally:
        db.close()


def test_repository_never_commits_the_supplied_transaction(tmp_path):
    database_path = tmp_path / "repository-transaction.db"
    writer = _repository_db(str(database_path))
    reader = sqlite3.connect(database_path)
    reader.row_factory = sqlite3.Row
    try:
        writer.execute("BEGIN IMMEDIATE")
        ProcessVersionRepository.create_revision(
            1, _process_revision_payload("uncommitted-revision"), writer
        )

        assert writer.execute(
            "SELECT COUNT(*) FROM process_versions WHERE idempotency_key='uncommitted-revision'"
        ).fetchone()[0] == 1
        assert reader.execute(
            "SELECT COUNT(*) FROM process_versions WHERE idempotency_key='uncommitted-revision'"
        ).fetchone()[0] == 0

        writer.rollback()
        assert reader.execute(
            "SELECT COUNT(*) FROM process_versions WHERE idempotency_key='uncommitted-revision'"
        ).fetchone()[0] == 0
    finally:
        reader.close()
        writer.close()


def test_conditional_status_updates_check_status_and_row_version():
    db = _repository_db()
    try:
        process = ProcessVersionRepository.create_revision(
            1, _process_revision_payload("process-transition"), db
        )
        with pytest.raises(ProcessVersionStaleError):
            ProcessVersionRepository.transition_version(
                process["id"], "pending_approval", 0, "cancelled", {}, db
            )
        updated_process = ProcessVersionRepository.transition_version(
            process["id"],
            "draft",
            0,
            "pending_approval",
            {"impact_digest": "submitted-impact"},
            db,
        )
        assert updated_process["row_version"] == 1
        with pytest.raises(ProcessVersionStaleError):
            ProcessVersionRepository.transition_version(
                process["id"], "pending_approval", 0, "rejected", {}, db
            )

        route = RouteVersionRepository.create_revision(
            3,
            _route_revision_payload("route-transition"),
            [],
            db,
        )
        with pytest.raises(RouteVersionStaleError):
            RouteVersionRepository.transition_version(
                route["id"], "draft", 99, "cancelled", {}, db
            )
    finally:
        db.close()


def test_release_members_are_unique_and_batch_members_are_prefetched():
    db = _repository_db()
    try:
        process = ProcessVersionRepository.create_revision(
            1, _process_revision_payload("release-process"), db
        )
        route = RouteVersionRepository.create_revision(
            3, _route_revision_payload("release-route"), [], db
        )
        batch = MasterDataReleaseRepository.create_batch(
            {
                "release_no": "MDR-20260812-001",
                "status": "draft",
                "revision_reason": "成组发布测试",
                "impact_digest": "release-impact",
                "created_by": 10,
                "created_by_name": "制单人",
                "idempotency_key": "release-batch-1",
            },
            db,
        )
        replay = MasterDataReleaseRepository.create_batch(
            {
                "release_no": "IGNORED-ON-REPLAY",
                "revision_reason": "不会覆盖",
                "idempotency_key": "release-batch-1",
            },
            db,
        )
        assert replay["id"] == batch["id"]

        MasterDataReleaseRepository.add_process_version(
            batch["id"], process["id"], db
        )
        MasterDataReleaseRepository.add_route_version(batch["id"], route["id"], db)
        MasterDataReleaseRepository.add_price_version(batch["id"], 41, db)
        with pytest.raises(ConflictError):
            MasterDataReleaseRepository.add_process_version(
                batch["id"], process["id"], db
            )

        loaded = MasterDataReleaseRepository.batch(batch["id"], db=db)
        assert [item["id"] for item in loaded["process_versions"]] == [process["id"]]
        assert [item["id"] for item in loaded["route_versions"]] == [route["id"]]
        assert [item["id"] for item in loaded["price_versions"]] == [41]

        with pytest.raises(ConflictError):
            MasterDataReleaseRepository.transition_batch(
                batch["id"], "pending_approval", 0, "published", {}, db
            )
    finally:
        db.close()


def test_lifecycle_repository_replays_same_key_and_blocks_duplicate_pending_request():
    db = _repository_db()
    try:
        payload = {
            "action": "retire",
            "status": "pending",
            "reason": "工艺不再使用",
            "requested_by": 10,
            "requested_by_name": "制单人",
            "idempotency_key": "process-retire-1",
        }
        request = MasterDataLifecycleRepository.create_process_request(1, payload, db)
        replay = MasterDataLifecycleRepository.create_process_request(1, payload, db)

        assert replay == request
        assert MasterDataLifecycleRepository.pending_process_request(1, db=db) == request
        with pytest.raises(ConflictError):
            MasterDataLifecycleRepository.create_process_request(
                1, {**payload, "idempotency_key": "process-retire-2"}, db
            )

        resolved = MasterDataLifecycleRepository.transition_process_request(
            request["id"],
            "pending",
            0,
            "approved",
            {
                "approved_by": 11,
                "approved_by_name": "批准人",
                "resolved_at": "2026-08-12 10:00:00",
            },
            db,
        )
        assert resolved["status"] == "approved"
        assert MasterDataLifecycleRepository.pending_process_request(1, db=db) is None

        route_request = MasterDataLifecycleRepository.create_route_request(
            3,
            {
                **payload,
                "idempotency_key": "route-retire-1",
            },
            db,
        )
        assert MasterDataLifecycleRepository.pending_route_request(3, db=db)["id"] == route_request["id"]
    finally:
        db.close()


def test_compatibility_projection_updates_are_explicit_and_optimistic():
    db = _repository_db()
    try:
        process = ProcessVersionRepository.create_revision(
            1,
            _process_revision_payload(
                "process-projection",
                name="精车发布名",
                description="发布后的兼容描述",
                seq_order=15,
            ),
            db,
        )
        process_projection = ProcessVersionRepository.update_compatibility_projection(
            1, process["id"], 0, db
        )
        assert process_projection["name"] == "精车发布名"
        assert process_projection["current_effective_version_id"] == process["id"]
        with pytest.raises(ProcessVersionStaleError):
            ProcessVersionRepository.update_compatibility_projection(
                1, process["id"], 0, db
            )

        process_v1 = ProcessVersionRepository.version_by_number(1, 1, db=db)
        process_v2 = ProcessVersionRepository.version_by_number(2, 1, db=db)
        route = RouteVersionRepository.create_revision(
            3,
            _route_revision_payload("route-projection", name="新路线发布名"),
            [
                {
                    "process_id": 2,
                    "process_version_id": process_v2["id"],
                    "seq_order": 20,
                    "is_required": 0,
                    "required_audit": 0,
                },
                {
                    "process_id": 1,
                    "process_version_id": process_v1["id"],
                    "seq_order": 10,
                    "is_required": 1,
                    "required_audit": 1,
                },
            ],
            db,
        )
        route_projection = RouteVersionRepository.update_compatibility_projection(
            3, route["id"], 0, db
        )
        legacy_items = db.execute(
            "SELECT process_id,seq_order,is_required,required_audit "
            "FROM process_route_items WHERE route_id=3 ORDER BY seq_order,id"
        ).fetchall()

        assert route_projection["name"] == "新路线发布名"
        assert [dict(item) for item in legacy_items] == [
            {"process_id": 1, "seq_order": 10, "is_required": 1, "required_audit": 1},
            {"process_id": 2, "seq_order": 20, "is_required": 0, "required_audit": 0},
        ]
    finally:
        db.close()


def test_version_events_are_append_only_repository_operations():
    db = _repository_db()
    try:
        version = ProcessVersionRepository.create_revision(
            1, _process_revision_payload("event-process"), db
        )
        event = ProcessVersionRepository.insert_event(
            {
                "entity_id": 1,
                "version_id": version["id"],
                "event_type": "revision_created",
                "actor_id": 10,
                "actor_name": "制单人",
                "actor_role": "process_editor",
                "reason": "创建修订版",
                "idempotency_key": "event-process-1",
                "from_status": "published",
                "to_status": "draft",
                "payload": {"version": 2},
            },
            db,
        )
        replay = ProcessVersionRepository.insert_event(
            {
                "entity_id": 1,
                "version_id": version["id"],
                "event_type": "revision_created",
                "idempotency_key": "event-process-1",
            },
            db,
        )

        assert replay == event
        events = ProcessVersionRepository.list_events(1, db=db)
        assert events[-1] == event
        assert events[0]["event_type"] == "legacy_baseline_created"
        assert not hasattr(ProcessVersionRepository, "update_event")
        assert not hasattr(ProcessVersionRepository, "delete_event")
    finally:
        db.close()
