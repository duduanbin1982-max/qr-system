from factories import ensure_process
from modules.db import get_db
from modules.repositories.position_repository import PositionRepository
from modules.services.position_service import PositionService


def _seed_position_with_process(client):
    with client.application.app_context():
        db = get_db()
        process_id = ensure_process(db, "岗位契约测试工序")
        position_id = PositionService.create_position(
            {
                "name": "岗位契约测试岗位",
                "description": "原描述",
                "process_ids": [process_id],
            }
        )
        return position_id, process_id


def test_position_list_exposes_structured_processes_and_ids(client):
    position_id, process_id = _seed_position_with_process(client)

    with client.application.app_context():
        row = next(
            item
            for item in PositionService.list_positions()["positions"]
            if item["id"] == position_id
        )

    assert row["process_ids"] == [process_id]
    assert row["processes"] == [
        {
            "position_id": position_id,
            "process_id": process_id,
            "process_name": "岗位契约测试工序",
        }
    ]


def test_position_partial_update_preserves_processes(client):
    position_id, process_id = _seed_position_with_process(client)

    with client.application.app_context():
        PositionService.update_position(position_id, {"description": "只修改描述"})

        assert PositionRepository.find_process_ids_by_position(position_id) == {
            process_id
        }


def test_explicit_empty_process_ids_clears_processes(client):
    position_id, _ = _seed_position_with_process(client)

    with client.application.app_context():
        PositionService.update_position(position_id, {"process_ids": []})

        assert PositionRepository.find_process_ids_by_position(position_id) == set()


def test_create_and_update_use_the_same_position_name_rule(client, auth_headers):
    position_id, _ = _seed_position_with_process(client)

    create_response = client.post(
        "/api/positions",
        json={"name": "非法@岗位"},
        headers=auth_headers,
    )
    update_response = client.put(
        f"/api/positions/{position_id}",
        json={"name": "非法@岗位"},
        headers=auth_headers,
    )

    assert create_response.status_code == 400
    assert update_response.status_code == 400
