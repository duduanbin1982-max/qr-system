from modules.domain.process_reporting import ProcessReportingPolicy


def _order():
    return {
        "id": 1,
        "quantity": 10,
        "processes": [
            {
                "id": process_id,
                "process_id": process_id,
                "process_name": f"P{process_id}",
                "seq_order": process_id,
                "completed": completed,
                "status": "pending",
            }
            for process_id, completed in ((1, 3), (2, 0), (3, 0))
        ],
    }


def test_process_reporting_policy_applies_previous_process_limit_without_settings():
    order = _order()

    ProcessReportingPolicy.attach_context(
        order,
        {
            "mode": "sequential",
            "configured_previous_limit": True,
            "effective_previous_limit": True,
        },
    )

    assert [item["normal_reportable"] for item in order["processes"]] == [True, True, False]
    assert order["processes"][1]["max_report_quantity"] == 3


def test_process_reporting_policy_prefers_unique_active_position_candidate():
    order = _order()

    ProcessReportingPolicy.attach_context(
        order,
        {
            "mode": "out_of_order",
            "configured_previous_limit": False,
            "effective_previous_limit": False,
        },
        user_process_ids={1, 2, 3},
        preferred_process_ids={2},
    )

    assert order["current_process"]["process_id"] == 2
    assert order["process_selection_source"] == "position_auto"
    assert order["requires_process_selection"] is False
