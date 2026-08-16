import pytest

from factories import create_process_route, ensure_process
from modules.db import get_db
from modules.domain.errors import AuthorizationError, ConflictError, ValidationError
from modules.repositories.audit_log_repository import AuditLogRepository
from modules.services.position_service import PositionService
from modules.services.price_service import RoutePriceService
from modules.services.role_service import RoleGroupService, RoleService


def _admin_id(db):
    return db.execute(
        "SELECT u.id FROM users u JOIN user_roles ur ON ur.user_id = u.id "
        "JOIN roles r ON r.id = ur.role_id WHERE r.code = 'admin' LIMIT 1"
    ).fetchone()["id"]


def _worker_id(db):
    role_id = db.execute("SELECT id FROM roles WHERE code = 'worker'").fetchone()["id"]
    user_id = db.execute(
        "INSERT INTO users (username,password,name,role,status,employee_no) "
        "VALUES ('role_policy_worker','hash','角色策略员工','worker','active','ROLE-WORKER')"
    ).lastrowid
    db.execute(
        "INSERT INTO user_roles (user_id,role_id) VALUES (?,?)", (user_id, role_id)
    )
    db.commit()
    return user_id


def test_role_group_hierarchy_rejects_cycles_and_parent_deletion(client):
    with client.application.app_context():
        db = get_db()
        actor_id = _admin_id(db)
        parent_id = RoleGroupService.create_group({"name": "生产管理组"}, actor_id)
        child_id = RoleGroupService.create_group(
            {"name": "班组长组", "parent_id": parent_id}, actor_id
        )

        with pytest.raises(ValueError, match="循环引用"):
            RoleGroupService.update_group(parent_id, {"parent_id": child_id}, actor_id)
        with pytest.raises(ValueError, match="有下级"):
            RoleGroupService.delete_group(parent_id, actor_id)

        RoleGroupService.delete_group(child_id, actor_id)
        RoleGroupService.delete_group(parent_id, actor_id)
        names = {group["name"] for group in RoleGroupService.list_groups()["role_groups"]}
        assert "生产管理组" not in names
        assert "班组长组" not in names


def test_role_auto_code_update_and_assignment_guards(client):
    with client.application.app_context():
        db = get_db()
        actor_id = _admin_id(db)
        role_id = RoleService.create_role({"name": "质量主管"}, actor_id)
        role = db.execute("SELECT code FROM roles WHERE id = ?", (role_id,)).fetchone()
        assert role["code"]

        RoleService.update_role(
            role_id,
            {"name": "质量负责人", "permissions": ["quality:view"]},
            actor_id,
        )
        updated = db.execute(
            "SELECT name, permissions FROM roles WHERE id = ?", (role_id,)
        ).fetchone()
        assert updated["name"] == "质量负责人"
        assert "quality:view" in updated["permissions"]
        assert db.execute(
            "SELECT COUNT(*) FROM audit_logs WHERE target_type='role' AND target_id=?",
            (role_id,),
        ).fetchone()[0] == 2

        user_id = db.execute(
            "INSERT INTO users (username, password, name, role, employee_no, status) "
            "VALUES ('qualityowner', 'hash', '质量主管', 'worker', 'QA-001', 'active')"
        ).lastrowid
        db.execute("INSERT INTO user_roles (user_id, role_id) VALUES (?, ?)", (user_id, role_id))
        db.commit()
        with pytest.raises(ValueError, match="已分配"):
            RoleService.delete_role(role_id, actor_id)


def test_role_rejects_duplicate_code_and_builtin_deletion(client):
    with client.application.app_context():
        db = get_db()
        actor_id = _admin_id(db)
        first_id = RoleService.create_role(
            {"name": "计划员", "code": "planner_test"}, actor_id
        )
        second_id = RoleService.create_role(
            {"name": "调度员", "code": "dispatcher_test"}, actor_id
        )

        with pytest.raises(ValueError, match="已存在"):
            RoleService.update_role(second_id, {"code": "planner_test"}, actor_id)

        builtin = db.execute("SELECT id FROM roles WHERE is_builtin = 1 LIMIT 1").fetchone()
        assert builtin is not None
        with pytest.raises(ValueError, match="内置角色"):
            RoleService.delete_role(builtin["id"], actor_id)

        RoleService.delete_role(first_id, actor_id)
        RoleService.delete_role(second_id, actor_id)


def test_role_permission_mutations_require_actual_admin_and_catalog(client):
    with client.application.app_context():
        db = get_db()
        admin_id = _admin_id(db)
        worker_id = _worker_id(db)

        with pytest.raises(AuthorizationError, match="仅系统管理员"):
            RoleService.create_role({"name": "越权角色"}, worker_id)
        with pytest.raises(ConflictError, match="通配权限"):
            RoleService.create_role(
                {"name": "通配角色", "permissions": ["*"]}, admin_id
            )
        with pytest.raises(ValidationError, match="未知权限编码"):
            RoleService.create_role(
                {"name": "未知权限角色", "permissions": ["quality.view"]}, admin_id
            )
        with pytest.raises(ValidationError, match="active.*inactive"):
            RoleService.create_role(
                {"name": "非法状态角色", "status": "deleted"}, admin_id
            )
        with pytest.raises(ConflictError, match="仅用于分类"):
            RoleGroupService.create_group(
                {"name": "越权角色组", "permissions": ["orders:view"]}, admin_id
            )


def test_builtin_admin_security_fields_are_immutable(client):
    with client.application.app_context():
        db = get_db()
        actor_id = _admin_id(db)
        admin_role = db.execute(
            "SELECT id FROM roles WHERE code='admin' AND is_builtin=1"
        ).fetchone()

        for change in (
            {"code": "renamed_admin"},
            {"status": "inactive"},
            {"permissions": []},
            {"group_id": None},
        ):
            with pytest.raises(ConflictError, match="安全字段不可修改"):
                RoleService.update_role(admin_role["id"], change, actor_id)


def test_role_create_rolls_back_when_audit_write_fails(client, monkeypatch):
    with client.application.app_context():
        db = get_db()
        actor_id = _admin_id(db)

        def fail_audit(*args, **kwargs):
            raise RuntimeError("audit unavailable")

        monkeypatch.setattr(AuditLogRepository, "insert_log", fail_audit)
        with pytest.raises(RuntimeError, match="audit unavailable"):
            RoleService.create_role(
                {"name": "应回滚角色", "code": "rollback_role"}, actor_id
            )
        assert db.execute(
            "SELECT COUNT(*) FROM roles WHERE code='rollback_role'"
        ).fetchone()[0] == 0


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


def test_legacy_route_price_write_is_disabled(client):
    with client.application.app_context():
        db = get_db()
        process_id = ensure_process(db, "计件工序")
        route_id = create_process_route(db, [process_id], "计件路线")

        with pytest.raises(ValueError, match="版本化工价"):
            RoutePriceService.save_prices(
                route_id, {str(process_id): "12.50"}, "2026-07-01", "首版"
            )
        assert RoutePriceService.get_by_route(route_id)["steps"][0]["unit_price"] is None


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
