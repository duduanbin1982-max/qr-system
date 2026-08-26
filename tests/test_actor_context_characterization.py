import pytest

from modules.domain.errors import ValidationError
from modules.services.master_data_lifecycle_service import (
    MasterDataLifecycleService,
)
from modules.services.master_data_release_service import MasterDataReleaseService
from modules.services.position_audit_service import PositionAuditService
from modules.services.position_lifecycle_service import PositionLifecycleService
from modules.services.position_version_service import PositionVersionService
from modules.services.process_version_service import ProcessVersionService
from modules.services.route_version_service import RouteVersionService


ACTOR_ADAPTERS = (
    ("master-data-lifecycle", MasterDataLifecycleService._actor),
    ("master-data-release", MasterDataReleaseService._actor),
    ("process-version", ProcessVersionService._actor),
    ("route-version", RouteVersionService._actor),
    ("position-audit", PositionAuditService._actor),
    ("position-lifecycle", PositionLifecycleService._actor),
    ("position-version", PositionVersionService._actor),
)

VALID_CASES = (
    (
        {
            "id": " 1000 ",
            "name": " 杜斌 ",
            "username": "ignored",
            "role": " admin ",
        },
        {"id": 1000, "name": "杜斌", "role": "admin"},
    ),
    (
        {"id": 1004, "name": "", "username": " Dooley ", "role": None},
        {"id": 1004, "name": "Dooley", "role": ""},
    ),
)

INVALID_ACTORS = (
    None,
    {},
    {"id": None},
    {"id": "not-a-number"},
    {"id": "0"},
    {"id": -1},
)


@pytest.mark.parametrize("adapter_name,adapter", ACTOR_ADAPTERS)
@pytest.mark.parametrize("source,expected", VALID_CASES)
def test_actor_adapters_preserve_valid_normalization(
    adapter_name, adapter, source, expected
):
    assert adapter(source) == expected, adapter_name


@pytest.mark.parametrize("adapter_name,adapter", ACTOR_ADAPTERS)
@pytest.mark.parametrize("source", INVALID_ACTORS)
def test_actor_adapters_preserve_fail_closed_error(adapter_name, adapter, source):
    with pytest.raises(ValidationError) as error:
        adapter(source)

    assert str(error.value) == "操作人不能为空", adapter_name
    assert error.value.to_payload() == {
        "error": "操作人不能为空",
        "code": "validation_error",
    }


@pytest.mark.parametrize("adapter_name,adapter", ACTOR_ADAPTERS)
def test_actor_adapters_record_current_boolean_id_behavior(adapter_name, adapter):
    assert adapter({"id": True, "username": "布尔来源", "role": "worker"}) == {
        "id": 1,
        "name": "布尔来源",
        "role": "worker",
    }, adapter_name
