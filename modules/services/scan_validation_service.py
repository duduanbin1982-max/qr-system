"""Validation use case for scan work reports."""
from modules.access_policy import get_user_process_ids, has_permission


class ScanValidationService:
    """Validates desktop and mobile scan report submissions."""

    @staticmethod
    def validate_report(order_id, process_id, user, quantity, serial_no, report_type):
        """Return ((error, status), quantity, serial_no) for scan report validation."""
        from modules.services.scan_helper_service import ScanHelperService

        if has_permission(user, "quality:edit") and report_type == "normal":
            return ({"error": "质检/管理员账号只能进行返工/报废操作，不能正常报工"}, 403), None, None

        if not order_id or not process_id:
            return ({"error": "缺少订单或工序信息"}, 400), None, None

        if ScanValidationService._is_serial_quantity(order_id, quantity, serial_no):
            quantity = 1

        order = ScanHelperService.get_order(order_id)
        if not order:
            return ({"error": "订单不存在"}, 404), None, None

        user_process_ids = get_user_process_ids(user)
        scope_error = ScanValidationService._validate_order_scope(
            order_id,
            user_process_ids,
        )
        if scope_error:
            return scope_error, None, None

        item_scan_error = ScanValidationService._validate_required_item_scan(
            order_id,
            user,
            serial_no,
        )
        if item_scan_error:
            return item_scan_error, None, None

        process_error = ScanValidationService._validate_process_membership(order_id, process_id)
        if process_error:
            return process_error, None, None

        duplicate_error = ScanValidationService._validate_duplicates(
            order_id,
            process_id,
            user["id"],
            serial_no,
            report_type,
        )
        if duplicate_error:
            return duplicate_error, None, None

        permission_error = ScanValidationService._validate_process_permission(
            process_id,
            user_process_ids,
        )
        if permission_error:
            return permission_error, None, None

        current_op, route_error = ScanValidationService._validate_route_process(
            order,
            order_id,
            process_id,
        )
        if route_error:
            return route_error, None, None

        current_seq = current_op["seq_order"] if current_op else 0
        sequencing_error = ScanValidationService._validate_sequence(order_id, current_seq, report_type)
        if sequencing_error:
            return sequencing_error, None, None

        quantity_error = ScanValidationService._validate_quantity(
            order_id,
            current_seq,
            current_op,
            quantity,
            order,
            report_type,
        )
        if quantity_error:
            return quantity_error, None, None

        serial_error = ScanValidationService._validate_serial_process(
            process_id,
            serial_no,
            report_type,
        )
        if serial_error:
            return serial_error, None, None

        return (None, None), quantity, serial_no

    @staticmethod
    def _is_serial_quantity(order_id, quantity, serial_no):
        from modules.services.scan_helper_service import ScanHelperService

        has_items = bool(ScanHelperService.get_product_items_by_order(order_id))
        return (has_items or serial_no) and quantity > 1

    @staticmethod
    def _validate_order_scope(order_id, user_process_ids):
        from modules.services.scan_helper_service import ScanHelperService

        if ScanHelperService.check_order_scope(order_id, user_process_ids):
            return None
        return ({"error": "您没有此订单的报工权限"}, 403)

    @staticmethod
    def _validate_required_item_scan(order_id, user, serial_no):
        from modules.services.scan_helper_service import ScanHelperService

        has_items = bool(ScanHelperService.get_product_items_by_order(order_id))
        if has_items and not serial_no and not has_permission(user, "quality:view"):
            return ({"error": "此订单为序列号模式，请扫描工件二维码后再报工"}, 400)
        return None

    @staticmethod
    def _validate_process_membership(order_id, process_id):
        from modules.services.scan_helper_service import ScanHelperService

        if ScanHelperService.check_process_in_order(order_id, process_id):
            return None
        return ({"error": "该工序不在订单工艺路线中"}, 400)

    @staticmethod
    def _validate_duplicates(order_id, process_id, user_id, serial_no, report_type):
        from modules.services.scan_helper_service import ScanHelperService

        if report_type == "normal" and serial_no:
            if ScanHelperService.check_serial_duplicate_in_order(order_id, serial_no, user_id):
                return (
                    {"error": "序列号 " + str(serial_no) + " 在此订单中已报工", "can_scrap_rework": True},
                    409,
                )

        if report_type == "normal":
            dup = ScanHelperService.check_duplicate_normal_report(
                order_id,
                process_id,
                serial_no,
                user_id,
            )
            if dup:
                msg = "序列号 " + str(serial_no) + " 在此工序已报工" if serial_no else "此工序已报工"
                return ({"error": msg, "can_scrap_rework": True}, 409)

        if report_type in ("scrap", "rework"):
            if ScanHelperService.check_duplicate_defect_report(order_id, process_id, user_id, report_type):
                return ({"error": "请勿重复提交，请稍后再试"}, 409)

        return None

    @staticmethod
    def _validate_process_permission(process_id, user_process_ids):
        from modules.services.scan_helper_service import ScanHelperService

        if user_process_ids is None or process_id in user_process_ids:
            return None

        proc = ScanHelperService._db(None).execute(
            "SELECT name FROM processes WHERE id=?",
            (process_id,),
        ).fetchone()
        if proc:
            return ({"error": "工序「" + proc["name"] + "」不在您的权限范围内"}, 403)
        return ({"error": "您没有此工序的报工权限"}, 403)

    @staticmethod
    def _validate_route_process(order, order_id, process_id):
        from modules.services.scan_helper_service import ScanHelperService

        current_op = ScanHelperService.get_order_process(order_id, process_id)
        if order["route_id"] and not current_op:
            return None, ({"error": "该工序不在订单工艺路线中"}, 400)
        return current_op, None

    @staticmethod
    def _validate_sequence(order_id, current_seq, report_type):
        from modules.services.scan_helper_service import ScanHelperService

        if report_type != "normal":
            return None
        err, code = ScanHelperService.check_process_order(order_id, current_seq)
        if err:
            return err, code
        return None

    @staticmethod
    def _validate_quantity(order_id, current_seq, current_op, quantity, order, report_type):
        from modules.services.scan_helper_service import ScanHelperService

        if report_type != "normal":
            return None
        err, code = ScanHelperService.check_quantity_limits(
            order_id,
            current_seq,
            current_op["completed"] or 0,
            quantity,
            order["quantity"],
        )
        if err:
            return err, code
        return None

    @staticmethod
    def _validate_serial_process(process_id, serial_no, report_type):
        from modules.services.scan_helper_service import ScanHelperService

        if not serial_no or report_type != "normal":
            return None
        item = ScanHelperService.get_product_item(serial_no)
        if item and item["current_process_id"] and item["current_process_id"] != process_id:
            return ({"error": "序列号 " + str(serial_no) + " 不在当前工序，请刷新后再试"}, 400)
        return None
