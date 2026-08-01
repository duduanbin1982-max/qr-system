"""Domain policy helpers for scan report validation."""


class ScanReportPolicy:
    @staticmethod
    def quality_account_normal_report_error(user_has_quality_edit, report_type):
        if user_has_quality_edit and report_type == "normal":
            return ({"error": "质检/管理员账号只能进行返工/报废操作，不能正常报工"}, 403)
        return None

    @staticmethod
    def report_identity_error(order_id, process_id):
        if not order_id or not process_id:
            return ({"error": "缺少订单或工序信息"}, 400)
        return None

    @staticmethod
    def normalized_quantity(has_items, quantity, serial_no):
        if (has_items or serial_no) and quantity > 1:
            return 1
        return quantity

    @staticmethod
    def required_serial_error(has_items, serial_no, user_can_view_quality):
        if has_items and not serial_no and not user_can_view_quality:
            return ({"error": "此订单为序列号模式，请扫描工件二维码后再报工"}, 400)
        return None

    @staticmethod
    def duplicate_normal_report_error(duplicate_row, serial_no):
        if not duplicate_row:
            return None
        message = "序列号 " + str(serial_no) + " 在此工序已报工" if serial_no else "此工序已报工"
        return ({"error": message, "can_scrap_rework": True}, 409)

    @staticmethod
    def duplicate_defect_report_error(duplicate_row):
        if duplicate_row:
            return ({"error": "请勿重复提交，请稍后再试"}, 409)
        return None

    @staticmethod
    def serial_current_process_error(item, process_id, serial_no):
        if item and item["current_process_id"] and item["current_process_id"] != process_id:
            return ({"error": "序列号 " + str(serial_no) + " 不在当前工序，请刷新后再试"}, 400)
        return None
