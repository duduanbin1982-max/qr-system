import pytest
from types import MappingProxyType

from modules.services.performance_history_planning import (
    CoverageStatistics,
    ManifestSummary,
    PerformanceHistoryMonthInputs,
    build_month_plan,
    build_month_plan_result,
)
from modules.services.performance_history_migration_service import (
    PerformanceHistoryMigrationService,
)


def _record(source_type, source_id, classification, payload, **_kwargs):
    return {
        "source_type": source_type,
        "source_id": int(source_id),
        "classification": classification,
        "payload": payload,
        "stable_key": f"{source_type}:{int(source_id):020d}",
    }


def _score_record(score, month, _targets):
    return _record(
        "legacy_score",
        score["id"],
        "legacy_baseline",
        {"month": month, "user_id": score["user_id"]},
    )


def test_month_planner_uses_snapshots_without_database_access():
    source_scores = [
        {
            "id": 1,
            "user_id": 11,
            "position_id_snapshot": 3,
            "position_name_snapshot": "历史岗位",
            "nested": {"tags": ["baseline"], "flags": {"frozen"}},
        }
    ]
    source_targets = {
        3: {
            "id": 12,
            "position_id": 3,
            "target_output_qty": 100,
            "minimum_effective_work_days": 1,
            "effective_from_month": "2026-01",
            "effective_to_month": "",
            "status": "approved",
        }
    }
    inputs = PerformanceHistoryMonthInputs(
        production_month="2026-06",
        period_start="2026-06-01 07:00:00",
        period_end="2026-07-01 07:00:00",
        legacy_batch={"id": 7},
        legacy_manifest={
            "id": 8,
            "source_score_count": 1,
            "overwritten_score_count": 0,
            "missing_position_count": 0,
            "manifest_sha256": "legacy-digest",
            "records_json": "[]",
        },
        scores=source_scores,
        targets=source_targets,
        work_records=[],
        work_time_records=[],
        ambiguity_rows=[],
        quality_evaluations=[],
        scrap_records=[],
        rework_records=[],
        inspections=[],
        inspection_candidates={},
        quality_events=[],
        assignments=[],
        rules=[],
        improvement_plans=[],
    )

    assert isinstance(inputs.scores, tuple)
    assert isinstance(inputs.targets, MappingProxyType)
    assert isinstance(inputs.targets[3], MappingProxyType)
    source_scores[0]["nested"]["tags"].append("mutated")
    source_scores[0]["nested"]["flags"].add("mutated")
    source_targets[3]["target_output_qty"] = 999
    assert inputs.scores[0]["nested"]["tags"] == ("baseline",)
    assert inputs.scores[0]["nested"]["flags"] == frozenset({"frozen"})
    assert inputs.targets[3]["target_output_qty"] == 100
    assert PerformanceHistoryMigrationService._json_object(
        inputs.scores[0]["nested"]
    ) == {"tags": ["baseline"], "flags": ["frozen"]}
    with pytest.raises(AttributeError):
        inputs.scores.append({})
    with pytest.raises(TypeError):
        inputs.targets[3]["target_output_qty"] = 101

    first = build_month_plan(
        inputs,
        record=_record,
        score_record=_score_record,
        json_object=lambda _value: {},
        calendar_month=lambda value: str(value or "")[:7],
        digest=lambda _value: "stable-digest",
    )
    second = build_month_plan(
        inputs,
        record=_record,
        score_record=_score_record,
        json_object=lambda _value: {},
        calendar_month=lambda value: str(value or "")[:7],
        digest=lambda _value: "stable-digest",
    )

    assert first == second
    assert first["legacy_batch_id"] == 7
    assert first["legacy_manifest_id"] == 8
    assert first["manifest_sha256"] == "stable-digest"
    assert [row["stable_key"] for row in first["records"]] == [
        "legacy_manifest:00000000000000000008",
        "legacy_score:00000000000000000001",
        "position_target:00000000000000000012",
    ]

    result = build_month_plan_result(
        inputs,
        record=_record,
        score_record=_score_record,
        json_object=lambda _value: {},
        calendar_month=lambda value: str(value or "")[:7],
        digest=lambda _value: "stable-digest",
    )
    assert isinstance(result.coverage, CoverageStatistics)
    assert isinstance(result.manifest, ManifestSummary)
    assert isinstance(result.manifest.records, tuple)
    assert isinstance(result.manifest.records[0], MappingProxyType)
    with pytest.raises(TypeError):
        result.manifest.records[0]["classification"] = "mutated"
    with pytest.raises(TypeError):
        result.manifest.records[2]["payload"]["position_id"] = 999
    assert result.source_snapshot_sha256
    assert result.source_snapshot_sha256 == first["source_snapshot_sha256"]
    assert result.as_dict() == first
