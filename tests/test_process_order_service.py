import modules.services.process_order_service as process_order_module
from modules.services.process_order_service import ProcessOrderService


def _order(completed=(0, 0, 0)):
    return {
        "id": 1,
        "quantity": 10,
        "processes": [
            {
                "id": index,
                "process_id": index,
                "process_name": f"P{index}",
                "seq_order": index,
                "completed": value,
                "status": "pending",
            }
            for index, value in enumerate(completed, start=1)
        ],
    }


def _settings(mode, previous_limit="1"):
    values = {
        "process_order_mode": mode,
        "limit_by_prev_process": previous_limit,
    }
    return lambda key, default=None: values.get(key, default)


def test_sequential_exposes_started_pipeline_without_allowing_a_skip(monkeypatch):
    monkeypatch.setattr(
        process_order_module,
        "get_setting",
        _settings("sequential"),
    )
    order = _order((3, 0, 0))

    ProcessOrderService.attach_context(order)

    assert [process["normal_reportable"] for process in order["processes"]] == [True, True, False]
    assert order["processes"][1]["max_report_quantity"] == 3
    assert order["current_process"]["process_id"] == 1
    assert order["requires_process_selection"] is True


def test_out_of_order_makes_all_incomplete_authorized_processes_reportable(monkeypatch):
    monkeypatch.setattr(
        process_order_module,
        "get_setting",
        _settings("out_of_order", previous_limit="1"),
    )
    order = _order()

    ProcessOrderService.attach_context(order, user_process_ids={2, 3})

    assert [process["normal_reportable"] for process in order["processes"]] == [False, True, True]
    assert order["processes"][1]["max_report_quantity"] == 10
    assert order["limit_by_prev_process_effective"] is False
    assert order["current_process"]["process_id"] == 2


def test_serial_mode_only_exposes_the_item_current_process(monkeypatch):
    monkeypatch.setattr(
        process_order_module,
        "get_setting",
        _settings("out_of_order", previous_limit="0"),
    )
    order = _order()

    ProcessOrderService.attach_context(
        order,
        item_info={"current_process_id": 2},
        serial_no="SN-001",
    )

    assert [process["normal_reportable"] for process in order["processes"]] == [False, True, False]
    assert order["process_order_scope"] == "serial_sequential"
    assert order["current_process"]["process_id"] == 2
    assert order["requires_process_selection"] is False


def test_position_unique_candidate_is_selected_automatically(monkeypatch):
    monkeypatch.setattr(
        process_order_module,
        "get_setting",
        _settings("out_of_order", previous_limit="0"),
    )
    order = _order()

    ProcessOrderService.attach_context(
        order,
        user_process_ids={1, 2, 3},
        preferred_process_ids={2},
    )

    assert order["current_process"]["process_id"] == 2
    assert order["process_selection_source"] == "position_auto"
    assert order["requires_process_selection"] is False
    assert [process["position_reportable"] for process in order["processes"]] == [
        False,
        True,
        False,
    ]


def test_position_multiple_candidates_still_require_confirmation(monkeypatch):
    monkeypatch.setattr(
        process_order_module,
        "get_setting",
        _settings("out_of_order", previous_limit="0"),
    )
    order = _order()

    ProcessOrderService.attach_context(
        order,
        user_process_ids={1, 2, 3},
        preferred_process_ids={2, 3},
    )

    assert order["current_process"]["process_id"] == 2
    assert order["process_selection_source"] == "position_manual"
    assert order["requires_process_selection"] is True
    assert [process["position_reportable"] for process in order["processes"]] == [
        False,
        True,
        True,
    ]


def test_personal_authorization_is_fallback_when_position_has_no_candidate(monkeypatch):
    monkeypatch.setattr(
        process_order_module,
        "get_setting",
        _settings("out_of_order", previous_limit="0"),
    )
    order = _order()

    ProcessOrderService.attach_context(
        order,
        user_process_ids={2, 3},
        preferred_process_ids={99},
    )

    assert order["current_process"]["process_id"] == 2
    assert order["position_process_match"] is False
    assert order["process_selection_source"] == "authorization_manual"
    assert order["requires_process_selection"] is True
    assert all(
        process["position_reportable"] == process["normal_reportable"]
        for process in order["processes"]
    )


def test_serial_current_process_wins_over_active_position(monkeypatch):
    monkeypatch.setattr(
        process_order_module,
        "get_setting",
        _settings("out_of_order", previous_limit="0"),
    )
    order = _order()

    ProcessOrderService.attach_context(
        order,
        item_info={"current_process_id": 2},
        serial_no="SN-002",
        user_process_ids={1, 2, 3},
        preferred_process_ids={3},
    )

    assert order["current_process"]["process_id"] == 2
    assert order["process_selection_source"] == "serial_auto"
    assert order["requires_process_selection"] is False


def test_serial_backfill_unique_candidate_uses_active_position(monkeypatch):
    monkeypatch.setattr(
        process_order_module,
        "get_setting",
        _settings("out_of_order", previous_limit="0"),
    )
    order = _order()

    ProcessOrderService.attach_context(
        order,
        item_info={"current_process_id": 1},
        serial_no="SN-BF-001",
        user_process_ids={1, 2, 3},
        preferred_process_ids={3},
        serial_backfill_available=True,
    )

    assert order["serial_backfill_selection_source"] == "position_auto"
    assert order["serial_backfill_candidate_count"] == 1
    assert order["serial_backfill_message"]
    assert [p["serial_backfill_reportable"] for p in order["processes"]] == [False, False, True]


def test_serial_backfill_multiple_candidates_require_selection(monkeypatch):
    monkeypatch.setattr(
        process_order_module,
        "get_setting",
        _settings("out_of_order", previous_limit="0"),
    )
    order = _order()

    ProcessOrderService.attach_context(
        order,
        item_info={"current_process_id": 1},
        serial_no="SN-BF-002",
        user_process_ids={1, 2, 3},
        preferred_process_ids={2, 3},
        serial_backfill_available=True,
    )

    assert order["serial_backfill_selection_source"] == "position_manual"
    assert order["serial_backfill_candidate_count"] == 2
    assert [p["serial_backfill_reportable"] for p in order["processes"]] == [False, True, True]


def test_serial_backfill_does_not_fallback_to_other_position_authorization(monkeypatch):
    monkeypatch.setattr(
        process_order_module,
        "get_setting",
        _settings("out_of_order", previous_limit="0"),
    )
    order = _order()

    ProcessOrderService.attach_context(
        order,
        item_info={"current_process_id": 1},
        serial_no="SN-BF-003",
        user_process_ids={2, 3},
        preferred_process_ids={99},
        serial_backfill_available=True,
    )

    assert order["serial_backfill_selection_source"] == "none"
    assert order["serial_backfill_candidate_count"] == 0
    assert "切换岗位" in order["serial_backfill_message"]
    assert not any(p["serial_backfill_reportable"] for p in order["processes"])


def test_serial_backfill_requires_an_active_position_scope(monkeypatch):
    monkeypatch.setattr(
        process_order_module,
        "get_setting",
        _settings("out_of_order", previous_limit="0"),
    )
    order = _order()

    ProcessOrderService.attach_context(
        order,
        item_info={"current_process_id": 1},
        serial_no="SN-BF-004",
        user_process_ids={2, 3},
        preferred_process_ids=None,
        serial_backfill_available=True,
    )

    assert order["serial_backfill_selection_source"] == "none"
    assert order["serial_backfill_candidate_count"] == 0
    assert order["serial_backfill_message"] == "请先选择当前岗位"
