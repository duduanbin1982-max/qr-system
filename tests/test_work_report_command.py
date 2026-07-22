import pytest

from modules.domain.work_report import WorkReportCommand


def test_submission_command_normalizes_identity_and_serial_quantity():
    command = WorkReportCommand.from_submission(
        {
            "report_type": "NORMAL",
            "order_id": "11",
            "process_id": "5",
            "quantity": 9,
            "remark": "  已完成  ",
        },
        {"id": "13", "name": " Worker "},
        quantity=9,
        serial_no=" SERIAL-001 ",
        need_approval=1,
    )

    assert command.report_type == "normal"
    assert command.order_id == 11
    assert command.process_id == 5
    assert command.user_id == 13
    assert command.user_name == "Worker"
    assert command.remark == "已完成"
    assert command.serial_no == "SERIAL-001"
    assert command.quantity == 9
    assert command.effective_quantity == 1
    assert command.need_approval is True


def test_approved_record_command_preserves_report_owner_and_quantity():
    command = WorkReportCommand.from_approved_record({
        "order_id": 11,
        "process_id": 5,
        "user_id": 13,
        "user_name": "Worker",
        "quantity": 2,
        "serial_no": "",
    })

    assert command.report_type == "normal"
    assert command.effective_quantity == 2
    assert command.need_approval is False


@pytest.mark.parametrize(
    ("changes", "message"),
    [
        ({"report_type": "unknown"}, "报工类型不正确"),
        ({"quantity": 0}, "报工数量必须大于 0"),
        ({"quantity": "invalid"}, "报工数量必须为整数"),
        ({"order_id": None}, "缺少报工身份信息"),
    ],
)
def test_invalid_command_is_rejected(changes, message):
    data = {
        "report_type": "normal",
        "order_id": 11,
        "process_id": 5,
        "user_id": 13,
        "user_name": "Worker",
        "quantity": 1,
    }
    data.update(changes)

    with pytest.raises(ValueError, match=message):
        WorkReportCommand(**data)
