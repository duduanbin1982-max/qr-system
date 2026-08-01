import pytest

from factories import create_process_route, ensure_process
from modules.db import get_db
from modules.services.position_service import PositionService
from modules.services.price_service import RoutePriceService
from modules.services.role_service import RoleGroupService, RoleService


def test_role_group_hierarchy_rejects_cycles_and_parent_deletion(client):
    with client.application.app_context():
        parent_id = RoleGroupService.create_group({"name": "生产管理组"})
        child_id = RoleGroupService.create_group({"name": "班组长组", "parent_id": parent_id})

        with pytest.raises(ValueError, match="循环引用"):
            RoleGroupService.update_group(parent_id, {"parent_id": child_id})
        with pytest.raises(ValueError, match="有下级"):
            RoleGroupService.delete_group(parent_id)

        RoleGroupService.delete_group(child_id)
        RoleGroupService.delete_group(parent_id)
        names = {group["name"] for group in RoleGroupService.list_groups()["role_groups"]}
        assert "生产管理组" not in names
        assert "班组长组" not in names


def test_role_auto_code_update_and_assignment_guards(client):
    with client.application.app_context():
        db = get_db()
        role_id = RoleService.create_role({"name": "质量主管"})
        role = db.execute("SELECT code FROM roles WHERE id = ?", (role_id,)).fetchone()
        assert role["code"]

        RoleService.update_role(role_id, {"name": "质量负责人", "permissions": ["quality.view"]})
        updated = db.execute(
            "SELECT name, permissions FROM roles WHERE id = ?", (role_id,)
        ).fetchone()
        assert updated["name"] == "质量负责人"
        assert "quality.view" in updated["permissions"]

        user_id = db.execute(
            "INSERT INTO users (username, password, name, role, employee_no, status) "
            "VALUES ('qualityowner', 'hash', '质量主管', 'worker', 'QA-001', 'active')"
        ).lastrowid
        db.execute("INSERT INTO user_roles (user_id, role_id) VALUES (?, ?)", (user_id, role_id))
        db.commit()
        with pytest.raises(ValueError, match="已分配"):
            RoleService.delete_role(role_id)


def test_role_rejects_duplicate_code_and_builtin_deletion(client):
    with client.application.app_context():
        first_id = RoleService.create_role({"name": "计划员", "code": "planner_test"})
        second_id = RoleService.create_role({"name": "调度员", "code": "dispatcher_test"})

        with pytest.raises(ValueError, match="已存在"):
            RoleService.update_role(second_id, {"code": "planner_test"})

        db = get_db()
        builtin = db.execute("SELECT id FROM roles WHERE is_builtin = 1 LIMIT 1").fetchone()
        assert builtin is not None
        with pytest.raises(ValueError, match="内置角色"):
            RoleService.delete_role(builtin["id"])

        RoleService.delete_role(first_id)
        RoleService.delete_role(second_id)


def test_position_crud_keeps_process_assignments(client):
    with client.application.app_context():
        db = get_db()
        first_process = ensure_process(db, "岗位工序一")
        second_process = ensure_process(db, "岗位工序二", 2)

        position_id = PositionService.create_position({
            "name": "钻孔岗位",
            "description": "负责钻孔",
            "process_ids": [first_process],
        })
        listed = PositionService.list_positions()
        position = next(item for item in listed["positions"] if item["id"] == position_id)
        assert [item["process_id"] for item in position["processes"]] == [first_process]

        PositionService.update_position(position_id, {
            "name": "钻孔主岗位",
            "process_ids": [second_process],
        })
        process_ids = [
            row["process_id"]
            for row in db.execute(
                "SELECT process_id FROM position_processes WHERE position_id = ?",
                (position_id,),
            ).fetchall()
        ]
        assert process_ids == [second_process]
        assert PositionService.delete_position(position_id) == "钻孔主岗位"


def test_position_rejects_invalid_process_duplicate_name_and_assigned_user(client):
    with client.application.app_context():
        db = get_db()
        with pytest.raises(ValueError, match="不存在或已停用"):
            PositionService.create_position({"name": "无效岗位", "process_ids": [999999]})

        position_id = PositionService.create_position({"name": "焊接岗位"})
        with pytest.raises(ValueError, match="已存在"):
            PositionService.create_position({"name": "焊接岗位"})

        db.execute(
            "INSERT INTO users (username, password, name, role, employee_no, status, position_id) "
            "VALUES ('positionworker', 'hash', '岗位员工', 'worker', 'POS-001', 'active', ?)",
            (position_id,),
        )
        db.commit()
        impact = PositionService.check_impact(position_id)
        assert impact["users"] == 1
        with pytest.raises(ValueError, match="先将用户调岗"):
            PositionService.delete_position(position_id)


def test_route_price_create_update_and_history(client):
    with client.application.app_context():
        db = get_db()
        process_id = ensure_process(db, "计件工序")
        route_id = create_process_route(db, [process_id], "计件路线")

        assert RoutePriceService.save_prices(
            route_id, {str(process_id): "12.50"}, "2026-07-01", "首版"
        ) == (0, 1)
        assert RoutePriceService.save_prices(
            route_id, {str(process_id): 15}, "2026-07-15", "调整"
        ) == (1, 0)

        route = RoutePriceService.get_by_route(route_id)
        assert route["steps"][0]["unit_price"] == 15
        history = RoutePriceService.get_route_price_history(route_id)["history"]
        assert history[0]["old_price"] == 12.5
        assert history[0]["new_price"] == 15


@pytest.mark.parametrize(
    ("prices", "message"),
    [
        ({"not-an-id": "1"}, "格式无效"),
        ({"1": -1}, "不能为负数"),
    ],
)
def test_route_price_rejects_invalid_values(client, prices, message):
    with client.application.app_context():
        db = get_db()
        process_id = ensure_process(db, "工价校验工序")
        route_id = create_process_route(db, [process_id], "工价校验路线")
        normalized = {str(process_id) if key == "1" else key: value for key, value in prices.items()}
        with pytest.raises(ValueError, match=message):
            RoutePriceService.save_prices(route_id, normalized)


def test_route_price_rejects_process_outside_route(client):
    with client.application.app_context():
        db = get_db()
        route_process = ensure_process(db, "路线内工序")
        outside_process = ensure_process(db, "路线外工序", 2)
        route_id = create_process_route(db, [route_process], "边界路线")
        with pytest.raises(ValueError, match="不属于路线"):
            RoutePriceService.save_prices(route_id, {str(outside_process): 8})
