"""Validation use case for scan work reports."""
from modules.repositories.scan_repository import ScanRepository
from modules.services.access_policy_service import get_user_process_ids, has_permission
from modules.services.scan_report_policy import ScanReportPolicy


class ScanValidationService:
    """Validates desktop and mobile scan report submissions."""

    @staticmethod
    def _initial_report_context(order_id, process_id, user, quantity, serial_no, report_type):
        from modules.services.scan_helper_service import ScanHelperService

        account_error = ScanReportPolicy.quality_account_normal_report_error(
            has_permission(user, "quality:edit"),
            report_type,
        )
        if account_error:
            return None, quantity, account_error
        identity_error = ScanReportPolicy.report_identity_error(order_id, process_id)
        if identity_error:
            return None, quantity, identity_error
        quantity = ScanReportPolicy.normalized_quantity(
            ScanValidationService._order_has_items(order_id),
            quantity,
            serial_no,
        )
        order = ScanHelperService.get_order(order_id)
        if not order:
            return None, quantity, ({"error": "订单不存在"}, 404)
        if order["status"] == "completed":
            return None, quantity, ({"error": "订单已完成并归档，如需继续报工请先重新打开订单"}, 409)
        return order, quantity, None

    @staticmethod
    def _report_preflight_error(order_id, process_id, user, serial_no, report_type, user_process_ids):
        checks = (
            ScanValidationService._validate_order_scope(order_id, user_process_ids),
            ScanValidationService._validate_required_item_scan(order_id, user, serial_no),
            ScanValidationService._validate_process_membership(order_id, process_id),
            ScanValidationService._validate_duplicates(
                order_id, process_id, user["id"], serial_no, report_type
            ),
            ScanValidationService._validate_process_permission(process_id, user_process_ids),
        )
        return next((error for error in checks if error), None)

    @staticmethod
    def _report_route_error(
        order, order_id, process_id, quantity, report_type, serial_backfill=False
    ):
        current_op, route_error = ScanValidationService._validate_route_process(
            order,
            order_id,
            process_id,
        )
        if route_error:
            return current_op, route_error

        current_seq = current_op["seq_order"] if current_op else 0
        sequencing_error = None
        if not serial_backfill:
            sequencing_error = ScanValidationService._validate_sequence(
                order_id, current_seq, report_type
            )
        if sequencing_error:
            return current_op, sequencing_error

        if serial_backfill:
            quantity_error = None
            if (current_op["completed"] or 0) + quantity > (order["quantity"] or 0):
                quantity_error = ({"error": "报工数量超出订单总量限制"}, 400)
        else:
            quantity_error = ScanValidationService._validate_quantity(
                order_id,
                current_seq,
                current_op,
                quantity,
                order,
                report_type,
            )
        return current_op, quantity_error

    @staticmethod
    def validate_report(
        order_id,
        process_id,
        user,
        quantity,
        serial_no,
        report_type,
        serial_backfill=False,
    ):
        """Return ((error, status), quantity, serial_no) for scan report validation."""
        order, quantity, initial_error = ScanValidationService._initial_report_context(
            order_id, process_id, user, quantity, serial_no, report_type
        )
        if initial_error:
            return initial_error, None, None

        user_process_ids = get_user_process_ids(user, order_id=order_id)
        preflight_error = ScanValidationService._report_preflight_error(
            order_id, process_id, user, serial_no, report_type, user_process_ids
        )
        if preflight_error:
            return preflight_error, None, None

        focus_error = ScanValidationService._validate_completion_focus(
            order, process_id, user, report_type
        )
        if focus_error:
            return focus_error, None, None

        _, route_error = ScanValidationService._report_route_error(
            order,
            order_id,
            process_id,
            quantity,
            report_type,
            serial_backfill=serial_backfill,
        )
        if route_error:
            return route_error, None, None

        serial_error = None
        if not serial_backfill:
            serial_error = ScanValidationService._validate_serial_process(
                process_id,
                serial_no,
                report_type,
            )
        if serial_error:
            return serial_error, None, None

        return (None, None), quantity, serial_no

    @staticmethod
    def _order_has_items(order_id):
        from modules.services.scan_helper_service import ScanHelperService

        return bool(ScanHelperService.get_product_items_by_order(order_id))

    @staticmethod
    def _validate_completion_focus(order, process_id, user, report_type):
        if report_type != "normal":
            return None
        from modules.services.order_focus_service import OrderFocusService

        return OrderFocusService.report_block_error(order, process_id, user)

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
        return ScanReportPolicy.required_serial_error(
            has_items,
            serial_no,
            has_permission(user, "quality:view"),
        )

    @staticmethod
    def _validate_process_membership(order_id, process_id):
        from modules.services.scan_helper_service import ScanHelperService

        if ScanHelperService.check_process_in_order(order_id, process_id):
            return None
        return ({"error": "该工序不在订单工艺路线中"}, 400)

    @staticmethod
    def _validate_duplicates(order_id, process_id, user_id, serial_no, report_type):
        from modules.services.scan_helper_service import ScanHelperService

        if report_type == "normal":
            return ScanReportPolicy.duplicate_normal_report_error(
                ScanHelperService.check_duplicate_normal_report(
                    order_id,
                    process_id,
                    serial_no,
                    user_id,
                ),
                serial_no,
            )

        if report_type in ("scrap", "rework"):
            return ScanReportPolicy.duplicate_defect_report_error(
                ScanHelperService.check_duplicate_defect_report(order_id, process_id, user_id, report_type)
            )

        return None

    @staticmethod
    def _validate_process_permission(process_id, user_process_ids):
        from modules.services.scan_helper_service import ScanHelperService

        if user_process_ids is None or process_id in user_process_ids:
            return None

        proc = ScanRepository.find_process_name(process_id)
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
        return ScanReportPolicy.serial_current_process_error(item, process_id, serial_no)
