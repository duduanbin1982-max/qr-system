import ast
import json
from pathlib import Path

import pytest


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def _process(**overrides):
    value = {
        "process_id": 7,
        "version": 2,
        "process_code_snapshot": "PROC-0007",
        "name": "车削",
        "category": "机加工",
        "description": "数控车削",
        "seq_order": 10,
    }
    value.update(overrides)
    return value


def _route(**overrides):
    value = {
        "process_route_id": 5,
        "version": 3,
        "route_code_snapshot": "ROUTE-0005",
        "name": "机加工路线",
        "category": "机加工",
        "description": "标准加工路线",
        "items": [
            {
                "id": 101,
                "process_id": 7,
                "process_version_id": 70,
                "seq_order": 1,
                "is_required": 1,
                "required_audit": 0,
            },
            {
                "id": 102,
                "process_id": 8,
                "process_version_id": 80,
                "seq_order": 2,
                "is_required": 1,
                "required_audit": 1,
            },
        ],
    }
    value.update(overrides)
    return value


@pytest.mark.parametrize(
    ("current", "target"),
    [
        ("draft", "pending_approval"),
        ("draft", "cancelled"),
        ("pending_approval", "published"),
        ("published", "superseded"),
        ("published", "retired"),
    ],
)
def test_process_and_route_version_state_transitions_allow_only_workflow_edges(current, target):
    from modules.domain.process_versioning import (
        validate_process_version_transition,
        validate_route_version_transition,
    )

    assert validate_process_version_transition(current, target) == target
    assert validate_route_version_transition(current, target) == target


def test_process_rejection_is_terminal_but_route_rejection_returns_to_draft():
    from modules.domain.process_versioning import (
        RouteVersionImmutableError,
        validate_process_version_transition,
        validate_route_version_transition,
    )

    assert validate_process_version_transition("pending_approval", "rejected") == "rejected"
    assert validate_route_version_transition("pending_approval", "draft") == "draft"
    with pytest.raises(RouteVersionImmutableError):
        validate_route_version_transition("pending_approval", "rejected")


@pytest.mark.parametrize("target", ["draft", "pending_approval"])
def test_published_versions_cannot_return_to_editable_states(target):
    from modules.domain.process_versioning import (
        ProcessVersionImmutableError,
        RouteVersionImmutableError,
        validate_process_version_transition,
        validate_route_version_transition,
    )

    with pytest.raises(ProcessVersionImmutableError) as process_error:
        validate_process_version_transition("published", target)
    assert process_error.value.to_payload()["code"] == "PROCESS_VERSION_IMMUTABLE"

    with pytest.raises(RouteVersionImmutableError) as route_error:
        validate_route_version_transition("published", target)
    assert route_error.value.to_payload()["code"] == "ROUTE_VERSION_IMMUTABLE"


@pytest.mark.parametrize(
    ("current", "target"),
    [
        ("draft", "published"),
        ("pending_approval", "draft"),
        ("pending_approval", "cancelled"),
        ("superseded", "published"),
        ("rejected", "draft"),
        ("cancelled", "draft"),
        ("retired", "published"),
    ],
)
def test_invalid_version_transition_edges_are_rejected(current, target):
    from modules.domain.process_versioning import (
        ProcessVersionImmutableError,
        validate_process_version_transition,
    )

    with pytest.raises(ProcessVersionImmutableError) as error:
        validate_process_version_transition(current, target)
    assert error.value.to_payload()["details"] == {
        "current_status": current,
        "target_status": target,
    }


def test_separation_of_duties_and_stale_versions_return_stable_conflicts():
    from modules.domain.process_versioning import (
        ApprovalSeparationError,
        ProcessVersionStaleError,
        assert_row_version,
        assert_separation_of_duties,
    )

    with pytest.raises(ApprovalSeparationError) as separation:
        assert_separation_of_duties(10304, 10304, entity_type="process")
    assert separation.value.status_code == 409
    assert separation.value.to_payload() == {
        "error": "制单人与批准人必须不同",
        "code": "PROCESS_APPROVAL_SEPARATION_REQUIRED",
        "details": {"prepared_by": 10304, "approved_by": 10304},
        "action": "select_different_approver",
    }

    with pytest.raises(ProcessVersionStaleError) as stale:
        assert_row_version(3, 4, entity_type="process")
    assert stale.value.to_payload()["code"] == "PROCESS_VERSION_STALE"
    assert stale.value.to_payload()["details"] == {"expected": 3, "actual": 4}


def test_canonical_version_and_impact_summary_are_order_independent_and_stable():
    from modules.domain.process_versioning import (
        canonical_json,
        canonical_version_payload,
        payload_sha256,
        summarize_impact,
    )

    first_content = _process()
    second_content = {
        "description": "数控车削",
        "name": "车削",
        "seq_order": 10,
        "category": "机加工",
        "process_code_snapshot": "PROC-0007",
        "version": 2,
        "process_id": 7,
    }
    first_impact = [
        {"resource": "orders", "count": 3, "blocking_level": "warning"},
        {"resource": "prices", "count": 1, "blocking_level": "blocking"},
    ]
    second_impact = list(reversed(first_impact))

    first = canonical_version_payload("process", first_content, first_impact)
    second = canonical_version_payload("process", second_content, second_impact)
    assert first == second
    assert canonical_json(first) == canonical_json(second)
    assert payload_sha256(first) == payload_sha256(second)
    assert len(payload_sha256(first)) == 64
    assert summarize_impact(first_impact) == summarize_impact(second_impact)


def test_process_diff_distinguishes_fields_and_marks_category_as_high_impact():
    from modules.domain.process_versioning import diff_process_versions

    result = diff_process_versions(
        _process(),
        _process(
            name="精车",
            category="结构件",
            description="精密车削",
            seq_order=20,
        ),
    )

    assert result["changed_fields"] == ["name", "category", "description", "seq_order"]
    assert [change["field"] for change in result["changes"]] == result["changed_fields"]
    assert result["high_impact"] is True
    assert result["requires_authorized_review"] is True
    assert result["review_reasons"] == ["category_changed"]
    category_change = next(change for change in result["changes"] if change["field"] == "category")
    assert category_change["impact_level"] == "high"


def test_route_diff_distinguishes_node_add_remove_reorder_version_and_approval_changes():
    from modules.domain.process_versioning import diff_route_versions

    before = _route()
    after = _route(
        items=[
            {
                "process_id": 8,
                "process_version_id": 81,
                "seq_order": 1,
                "is_required": 1,
                "required_audit": 0,
            },
            {
                "process_id": 9,
                "process_version_id": 90,
                "seq_order": 2,
                "is_required": 1,
                "required_audit": 1,
            },
        ]
    )

    result = diff_route_versions(before, after)
    change_types = [change["change_type"] for change in result["node_changes"]]
    assert change_types == [
        "node_removed",
        "node_added",
        "node_reordered",
        "process_version_changed",
        "approval_requirement_changed",
    ]
    assert result["node_summary"] == {
        "node_added": 1,
        "node_removed": 1,
        "node_reordered": 1,
        "process_version_changed": 1,
        "approval_requirement_changed": 1,
    }


def test_identity_boundary_rejects_manufacturing_meaning_changes_as_revisions():
    from modules.domain.process_versioning import (
        MasterDataIdentityChangedError,
        assert_root_identity_preserved,
    )

    assert assert_root_identity_preserved("process", _process(), _process(name="精车")) is True
    with pytest.raises(MasterDataIdentityChangedError) as error:
        assert_root_identity_preserved(
            "process",
            _process(),
            _process(name="热处理", manufacturing_meaning_changed=True),
            identity_change_reason="工艺目的和技能要求均已改变",
        )
    assert error.value.to_payload()["code"] == "MASTER_DATA_ROOT_IDENTITY_CHANGED"
    assert error.value.to_payload()["action"] == "create_new_root_entity"


def test_route_category_consistency_has_stable_error_contract():
    from modules.domain.process_versioning import (
        RouteProcessCategoryMismatchError,
        assert_route_category_consistency,
    )

    with pytest.raises(RouteProcessCategoryMismatchError) as error:
        assert_route_category_consistency(
            "机加工",
            [
                {"process_id": 7, "process_category": "机加工"},
                {"process_id": 8, "process_category": "结构件"},
            ],
        )
    assert error.value.to_payload()["code"] == "ROUTE_PROCESS_CATEGORY_MISMATCH"
    assert error.value.to_payload()["details"]["mismatched_process_ids"] == [8]


def test_release_batch_summary_is_stable_and_missing_dependencies_have_reason_code():
    from modules.domain.process_versioning import (
        ReleaseDependencyError,
        payload_sha256,
        summarize_release_batch,
        validate_release_batch_dependencies,
    )

    first = summarize_release_batch(
        process_versions=[{"id": 70}, {"id": 80}],
        route_versions=[{"id": 500}],
        price_versions=[{"id": 900, "route_version_id": 500, "process_version_id": 70}],
    )
    second = summarize_release_batch(
        process_versions=[{"id": 80}, {"id": 70}],
        route_versions=[{"id": 500}],
        price_versions=[{"process_version_id": 70, "id": 900, "route_version_id": 500}],
    )
    assert first == second
    assert payload_sha256(first) == payload_sha256(second)

    batch = {
        "process_versions": [{"id": 70, "status": "pending_approval"}],
        "published_process_version_ids": [],
        "route_versions": [
            {
                "id": 500,
                "status": "pending_approval",
                "items": [
                    {
                        "process_id": 7,
                        "process_version_id": 70,
                        "requires_price": True,
                    }
                ],
            }
        ],
        "price_versions": [],
        "affected_routes": [],
    }
    with pytest.raises(ReleaseDependencyError) as error:
        validate_release_batch_dependencies(batch)
    payload = error.value.to_payload()
    assert payload["code"] == "MASTER_DATA_RELEASE_DEPENDENCY_MISSING"
    assert payload["details"]["reason_code"] == "PRICE_VERSION_BINDING_REQUIRED"
    assert payload["action"] == "complete_release_dependencies"


def test_release_batch_rejects_unavailable_process_versions_and_uncovered_routes():
    from modules.domain.process_versioning import (
        ReleaseDependencyError,
        validate_release_batch_dependencies,
    )

    with pytest.raises(ReleaseDependencyError) as process_error:
        validate_release_batch_dependencies(
            {
                "route_versions": [
                    {
                        "id": 500,
                        "items": [
                            {"process_id": 7, "process_version_id": 70}
                        ],
                    }
                ]
            }
        )
    assert (
        process_error.value.to_payload()["details"]["reason_code"]
        == "ROUTE_PROCESS_VERSION_INVALID"
    )

    with pytest.raises(ReleaseDependencyError) as route_error:
        validate_release_batch_dependencies(
            {
                "process_versions": [{"id": 70}],
                "affected_routes": [
                    {"route_version_id": 500, "process_version_id": 70}
                ],
            }
        )
    assert (
        route_error.value.to_payload()["details"]["reason_code"]
        == "AFFECTED_ROUTE_REVISION_OR_EXCEPTION_REQUIRED"
    )


def test_legacy_write_block_and_route_process_binding_errors_are_structured():
    from modules.domain.process_versioning import (
        LegacyMasterDataWriteBlockedError,
        RouteProcessVersionInvalidError,
        assert_legacy_master_data_write_allowed,
        assert_route_process_version_binding,
    )

    with pytest.raises(LegacyMasterDataWriteBlockedError) as legacy:
        assert_legacy_master_data_write_allowed(False)
    assert legacy.value.to_payload()["code"] == "LEGACY_MASTER_DATA_WRITE_BLOCKED"
    assert legacy.value.to_payload()["action"] == "use_versioned_master_data_api"

    with pytest.raises(RouteProcessVersionInvalidError) as binding:
        assert_route_process_version_binding(7, 8, process_version_id=70)
    assert binding.value.to_payload()["code"] == "ROUTE_PROCESS_VERSION_INVALID"


def test_process_versioning_policy_has_no_external_state_dependencies():
    path = PROJECT_ROOT / "modules" / "domain" / "process_versioning.py"
    tree = ast.parse(path.read_text(encoding="utf-8"))
    forbidden = {"datetime", "flask", "os", "sqlite3", "time"}
    imports = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imports.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imports.add(node.module.split(".")[0])
    assert imports.isdisjoint(forbidden)

    # The canonical representation is JSON, not repr(), and can be persisted directly.
    from modules.domain.process_versioning import canonical_json

    assert json.loads(canonical_json({"中文": "工序", "value": 1})) == {
        "中文": "工序",
        "value": 1,
    }
