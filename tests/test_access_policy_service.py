import logging

from modules.access_policy import collect_permission_codes, has_permission_code, resolve_process_scope
import modules.services.access_policy_service as access_policy_module
from modules.services.access_policy_service import AccessPolicyService


class FakeAccessPolicyRepository:
    permission_rows = []
    position_rows = []
    existing_rows = []
    user_process_rows = []
    requested_process_ids = None
    requested_user_id = None

    @staticmethod
    def get_permission_rows(user_id):
        return FakeAccessPolicyRepository.permission_rows

    @staticmethod
    def list_position_process_ids(position_id):
        return FakeAccessPolicyRepository.position_rows

    @staticmethod
    def list_existing_process_ids(process_ids):
        FakeAccessPolicyRepository.requested_process_ids = process_ids
        return FakeAccessPolicyRepository.existing_rows

    @staticmethod
    def list_user_process_ids(user_id):
        FakeAccessPolicyRepository.requested_user_id = user_id
        return FakeAccessPolicyRepository.user_process_rows


def test_collect_permission_codes_merges_role_and_group_permissions(caplog):
    caplog.set_level(logging.WARNING)
    rows = [
        {"role_perms": '["orders:view", "orders:edit"]', "group_perms": '["page:production"]'},
        {"role_perms": "not-json", "group_perms": "[]"},
    ]

    permissions = collect_permission_codes(rows, user_id=7)

    assert permissions == ["orders:edit", "orders:view", "page:production"]
    assert "invalid role_perms JSON for user 7" in caplog.text


def test_has_permission_code_supports_wildcard():
    assert has_permission_code(["*"], "inventory:delete") is True
    assert has_permission_code(["orders:view"], "inventory:delete") is False


def test_resolve_process_scope_prefers_explicit_allowed_processes():
    result = resolve_process_scope(
        [{"process_id": 3}],
        [{"id": 5}],
        has_position_scope=True,
        has_explicit_process_scope=True,
        permissions=[],
        global_data_scope_permissions={"reports:view"},
    )

    assert result == [3, 5]


def test_access_policy_service_uses_repository_only_in_service_layer(monkeypatch):
    FakeAccessPolicyRepository.permission_rows = [
        {"role_perms": '["quality:view"]', "group_perms": '["page:quality"]'}
    ]
    FakeAccessPolicyRepository.position_rows = []
    FakeAccessPolicyRepository.existing_rows = [{"id": 12}]
    FakeAccessPolicyRepository.user_process_rows = []
    FakeAccessPolicyRepository.requested_process_ids = None
    FakeAccessPolicyRepository.requested_user_id = None
    monkeypatch.setattr(access_policy_module, "AccessPolicyRepository", FakeAccessPolicyRepository)

    user = {"id": 9, "process_ids": "12,99"}

    assert AccessPolicyService.get_user_permissions(user) == ["page:quality", "quality:view"]
    assert AccessPolicyService.has_permission(user, "quality:view") is True
    assert AccessPolicyService.get_user_process_ids(user) == [12]
    assert FakeAccessPolicyRepository.requested_process_ids == [12, 99]
    assert FakeAccessPolicyRepository.requested_user_id == 9


def test_access_policy_service_merges_user_processes_junction(monkeypatch):
    FakeAccessPolicyRepository.permission_rows = []
    FakeAccessPolicyRepository.position_rows = [{"process_id": 3}]
    FakeAccessPolicyRepository.existing_rows = []
    FakeAccessPolicyRepository.user_process_rows = [{"id": 12}]
    FakeAccessPolicyRepository.requested_user_id = None
    monkeypatch.setattr(access_policy_module, "AccessPolicyRepository", FakeAccessPolicyRepository)

    user = {"id": 9, "process_ids": "", "position_id": 2}

    assert AccessPolicyService.get_user_process_ids(user) == [3, 12]
    assert FakeAccessPolicyRepository.requested_user_id == 9


def test_access_policy_service_returns_global_scope_for_global_permission(monkeypatch):
    FakeAccessPolicyRepository.permission_rows = [{"role_perms": '["reports:view"]', "group_perms": "[]"}]
    FakeAccessPolicyRepository.position_rows = []
    FakeAccessPolicyRepository.existing_rows = []
    FakeAccessPolicyRepository.user_process_rows = []
    monkeypatch.setattr(access_policy_module, "AccessPolicyRepository", FakeAccessPolicyRepository)
    monkeypatch.setattr(access_policy_module, "GLOBAL_DATA_SCOPE_PERMS", {"reports:view"})

    assert AccessPolicyService.get_user_process_ids({"id": 10}) is None
