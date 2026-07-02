from modules.services.scan_report_policy import ScanReportPolicy


def test_quality_account_cannot_submit_normal_report():
    error = ScanReportPolicy.quality_account_normal_report_error(True, "normal")

    assert error == ({"error": "质检/管理员账号只能进行返工/报废操作，不能正常报工"}, 403)
    assert ScanReportPolicy.quality_account_normal_report_error(True, "scrap") is None


def test_serial_quantity_is_forced_to_one():
    assert ScanReportPolicy.normalized_quantity(True, 5, "") == 1
    assert ScanReportPolicy.normalized_quantity(False, 5, "SN-1") == 1
    assert ScanReportPolicy.normalized_quantity(False, 5, "") == 5


def test_required_serial_message_is_chinese():
    error = ScanReportPolicy.required_serial_error(True, "", False)

    assert error == ({"error": "此订单为序列号模式，请扫描工件二维码后再报工"}, 400)
    assert ScanReportPolicy.required_serial_error(True, "", True) is None


def test_duplicate_messages_are_chinese_and_actionable():
    serial_error = ScanReportPolicy.duplicate_serial_order_error(True, "SN-001")
    process_error = ScanReportPolicy.duplicate_normal_report_error({"id": 1}, "SN-001")
    batch_error = ScanReportPolicy.duplicate_normal_report_error({"id": 1}, "")

    assert serial_error[0]["error"] == "序列号 SN-001 在此订单中已报工"
    assert process_error[0]["error"] == "序列号 SN-001 在此工序已报工"
    assert batch_error[0]["error"] == "此工序已报工"


def test_serial_current_process_message_is_chinese():
    error = ScanReportPolicy.serial_current_process_error({"current_process_id": 8}, 9, "SN-002")

    assert error == ({"error": "序列号 SN-002 不在当前工序，请刷新后再试"}, 400)
    assert ScanReportPolicy.serial_current_process_error({"current_process_id": 9}, 9, "SN-002") is None
