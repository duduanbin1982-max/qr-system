import pytest

from modules.domain.errors import ValidationError
from modules.domain.position_versioning import (
    PositionApprovalSeparationError,
    PositionImpactChangedError,
    PositionProcessInvalidError,
    PositionReferenceConflictError,
    PositionVersionImmutableError,
    PositionVersionStaleError,
    assert_impact_digest,
    assert_root_identity_preserved,
    assert_row_version,
    assert_separation_of_duties,
    canonical_position_payload,
    content_digest,
    copy_revision_content,
    impact_digest,
    normalize_position_content,
    position_diff,
    validate_transition,
)


@pytest.mark.parametrize(
    ("current", "target"),
    [
        ("draft", "draft"),
        ("draft", "pending_approval"),
        ("draft", "cancelled"),
        ("pending_approval", "published"),
        ("pending_approval", "rejected"),
        ("published", "superseded"),
        ("published", "retired"),
    ],
)
def test_allows_declared_position_version_transitions(current, target):
    assert validate_transition(current, target) == target


@pytest.mark.parametrize("target", ["draft", "pending_approval", "rejected"])
def test_published_revision_is_immutable(target):
    with pytest.raises(PositionVersionImmutableError) as error:
        validate_transition("published", target)

    assert error.value.code == "POSITION_VERSION_IMMUTABLE"
    assert error.value.to_payload()["action"] == "create_position_revision"


def test_terminal_revision_cannot_transition_or_be_reopened():
    for status in ("superseded", "rejected", "cancelled", "retired"):
        with pytest.raises(PositionVersionImmutableError):
            validate_transition(status, "draft")


def test_row_version_and_separation_have_stable_conflicts():
    assert assert_row_version("2", 2) == 2
    with pytest.raises(PositionVersionStaleError) as stale:
        assert_row_version(1, 2)
    assert stale.value.code == "POSITION_VERSION_STALE"
    assert stale.value.details == {"expected": 1, "actual": 2}

    assert assert_separation_of_duties(1000, 1004) is True
    with pytest.raises(PositionApprovalSeparationError) as separation:
        assert_separation_of_duties(1000, "1000")
    assert separation.value.code == "POSITION_APPROVAL_SEPARATION_REQUIRED"


def test_normalizes_position_content_and_rejects_invalid_process_ids():
    normalized = normalize_position_content(
        {
            "name": "  焊工  ",
            "description": "  焊接岗位  ",
            "process_ids": [9, "3", 9],
        }
    )

    assert normalized == {
        "name": "焊工",
        "description": "焊接岗位",
        "process_ids": [3, 9],
    }
    with pytest.raises(PositionProcessInvalidError) as invalid:
        normalize_position_content({"name": "焊工", "process_ids": [0]})
    assert invalid.value.code == "POSITION_PROCESS_INVALID"


def test_position_diff_reports_fields_and_process_set_changes():
    result = position_diff(
        {"name": "焊工", "description": "旧", "process_ids": [1, 2]},
        {"name": "焊接工", "description": "新", "process_ids": [2, 3]},
    )

    assert result["has_changes"] is True
    assert result["changed_fields"] == ["name", "description", "process_ids"]
    assert result["added_process_ids"] == [3]
    assert result["removed_process_ids"] == [1]
    assert result["requires_assignment_snapshot_split"] is True
    assert result["high_impact"] is True


def test_content_and_impact_digests_are_order_stable():
    left_content = {
        "position_id": 7,
        "version": 2,
        "position_code_snapshot": "POS-0007",
        "name": "焊工",
        "description": "说明",
        "process_ids": [9, 3],
    }
    right_content = {
        "process_ids": [3, 9],
        "description": "说明",
        "name": "焊工",
        "position_code_snapshot": "POS-0007",
        "version": 2,
        "position_id": 7,
    }
    assert content_digest(left_content) == content_digest(right_content)

    left_impact = [
        {"key": "active_employees", "count": 2, "blocking_level": "blocking"},
        {"key": "source_facts", "count": 4, "blocking_level": "info"},
    ]
    right_impact = [
        {"blocking_level": "info", "count": 4, "key": "source_facts"},
        {"count": 2, "key": "active_employees", "blocking_level": "blocking"},
    ]
    assert impact_digest(left_impact) == impact_digest(right_impact)


def test_canonical_payload_contains_only_stable_business_content():
    payload = canonical_position_payload(
        {
            "id": 99,
            "position_id": 7,
            "version": 2,
            "position_code_snapshot": "POS-0007",
            "name": "焊工",
            "description": "说明",
            "process_ids": [3],
            "updated_at": "changes on every request",
        }
    )

    assert payload == {
        "position_id": 7,
        "version": 2,
        "position_code_snapshot": "POS-0007",
        "name": "焊工",
        "description": "说明",
        "process_ids": [3],
    }


def test_impact_digest_change_raises_stable_error():
    assert assert_impact_digest("same", "same") is True
    with pytest.raises(PositionImpactChangedError) as changed:
        assert_impact_digest("submitted", "current")
    assert changed.value.details == {
        "submitted_impact_digest": "submitted",
        "current_impact_digest": "current",
    }


def test_root_identity_change_requires_a_new_position_root():
    with pytest.raises(PositionReferenceConflictError) as changed:
        assert_root_identity_preserved(
            {"name": "焊工"},
            {"name": "质检员", "organizational_meaning_changed": True},
            identity_change_reason="职责从生产变为质量审批",
        )
    assert changed.value.code == "POSITION_REFERENCE_CONFLICT"
    assert changed.value.details["reason"] == "职责从生产变为质量审批"


def test_copy_revision_content_resets_workflow_fields():
    copied = copy_revision_content(
        {
            "position_id": 7,
            "id": 71,
            "position_code_snapshot": "POS-0007",
            "name": "焊工",
            "description": "说明",
            "process_ids": [3, 9],
            "status": "published",
            "approved_by": 1004,
        },
        version=2,
        revision_reason="调整工序范围",
    )

    assert copied == {
        "position_id": 7,
        "version": 2,
        "position_code_snapshot": "POS-0007",
        "name": "焊工",
        "description": "说明",
        "process_ids": [3, 9],
        "status": "draft",
        "supersedes_version_id": 71,
        "revision_reason": "调整工序范围",
    }


@pytest.mark.parametrize("value", [None, "", -1, True])
def test_invalid_row_version_is_validation_error(value):
    with pytest.raises(ValidationError):
        assert_row_version(value, 0)
