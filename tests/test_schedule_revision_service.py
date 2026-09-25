import pytest

from modules.services.schedule_revision_service import ScheduleRevisionService


def test_workflow_input_and_digest_are_stable():
    reason, key, actor = ScheduleRevisionService._workflow_input(
        "  manual adjustment  ", "schedule-revision-key-001", "1000"
    )

    assert (reason, key, actor) == (
        "manual adjustment",
        "schedule-revision-key-001",
        1000,
    )
    payload = {"action": "submit", "revision_id": 12, "actor_id": actor}
    assert ScheduleRevisionService._workflow_digest(payload) == (
        ScheduleRevisionService._workflow_digest(
            {"actor_id": 1000, "revision_id": 12, "action": "submit"}
        )
    )


@pytest.mark.parametrize(
    ("reason", "key", "actor", "message"),
    [
        ("", "schedule-revision-key-001", 1000, "原因必须填写"),
        ("reason", "short", 1000, "幂等键长度"),
        ("reason", "schedule-revision-key-001", 0, "操作人不能为空"),
    ],
)
def test_workflow_input_rejects_invalid_values(reason, key, actor, message):
    with pytest.raises(ValueError, match=message):
        ScheduleRevisionService._workflow_input(reason, key, actor)


def test_workflow_service_requires_explicit_capacity_dependency():
    with pytest.raises(TypeError, match="capacity_service"):
        ScheduleRevisionService.lock_schedule_item(
            7, "reason", "schedule-revision-key-001", 1000
        )
