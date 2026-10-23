import pytest

from modules.services.performance_quality_planning import (
    QualityEventCommand,
    plan_quality_sources,
)


def _json_object(value):
    if not value:
        return {}
    return value if isinstance(value, dict) else {}


def test_quality_sources_preserve_source_order_and_ambiguity_count():
    result = plan_quality_sources(
        quality_evaluations=[
            {
                "id": 1,
                "target_user_id": None,
                "handoff_target_user_id": None,
                "target_work_record_id": None,
                "created_at": "2026-06-02",
            }
        ],
        scrap_records=[{"id": 2, "created_at": "2026-06-03", "quantity": 1}],
        rework_records=[{"id": 3, "created_at": "2026-06-04", "quantity": 2}],
        inspections=[{"id": 4, "order_id": 10, "process_id": 20, "business_at": "2026-06-05"}],
        inspection_candidates={(10, 20): [{"id": 40, "user_id": 7}]},
        quality_events=[
            {
                "id": 5,
                "business_at": "2026-06-06",
                "snapshot_json": {},
                "sources": [],
            }
        ],
        ambiguity_rows=[
            {"id": 90, "source_type": "process_quality_evaluation", "source_id": 1},
            {"id": 91, "source_type": "unmatched_source", "source_id": 99},
        ],
        json_object=_json_object,
        calendar_month=lambda value: str(value or "")[:7],
        production_month="2026-06",
    )

    assert [
        (command.source_type, command.source_id) for command in result.commands
    ] == [
        ("process_quality_evaluation", 1),
        ("scrap_record", 2),
        ("rework_record", 3),
        ("quality_inspection", 4),
        ("quality_event", 5),
        ("quality_ambiguity_unmatched_source", 99),
    ]
    assert result.quality_ambiguity_count == 2
    assert result.quality_ambiguity_ids == (90, 91)
    assert result.cross_month_ids == ()


def test_quality_coverage_keeps_legacy_boundary_count_semantics():
    result = plan_quality_sources(
        quality_evaluations=[{"id": 1, "created_at": "2026-05-31"}],
        scrap_records=[{"id": 2, "created_at": "2026-05-30", "quantity": 1}],
        rework_records=[],
        inspections=[{"id": 4, "order_id": 10, "process_id": 20, "business_at": "2026-05-29"}],
        inspection_candidates={(10, 20): [{"id": 40, "user_id": 7}]},
        quality_events=[
            {"id": 5, "business_at": "2026-05-28", "snapshot_json": {}, "sources": []}
        ],
        ambiguity_rows=[],
        json_object=_json_object,
        calendar_month=lambda value: str(value or "")[:7],
        production_month="2026-06",
    )

    assert result.cross_month_ids == (1,)
    assert result.cross_month_user_ids == (7,)


def test_quality_commands_are_immutable_until_materialized():
    result = plan_quality_sources(
        quality_evaluations=[],
        scrap_records=[{"id": 2, "created_at": "2026-06-03", "quantity": 1}],
        rework_records=[],
        inspections=[],
        inspection_candidates={},
        quality_events=[],
        ambiguity_rows=[],
        json_object=_json_object,
        calendar_month=lambda value: str(value or "")[:7],
        production_month="2026-06",
    )

    command = result.commands[0]
    assert isinstance(command, QualityEventCommand)
    with pytest.raises(TypeError):
        command.payload["quantity"] = 9
    with pytest.raises(AttributeError):
        result.commands.append(command)

    materialized = command.materialize(
        lambda source_type, source_id, classification, payload, **_kwargs: {
            "source_type": source_type,
            "source_id": source_id,
            "classification": classification,
            "payload": payload,
        }
    )
    materialized["payload"]["quantity"] = 9
    assert command.payload["quantity"] == 1
