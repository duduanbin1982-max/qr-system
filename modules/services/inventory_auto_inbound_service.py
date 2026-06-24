"""Auto-inbound workflow for completed work items."""
import logging


_logger = logging.getLogger(__name__)


class InventoryAutoInboundService:
    """Handles inventory inbound side effects after a piece completes production."""

    @staticmethod
    def auto_inbound_for_item(order_id, user_id, user_name, serial_no=None, db=None):
        """Per-item auto-inbound: triggered when a piece completes its last process."""
        from modules.services.scan_helper_service import ScanHelperService

        d = ScanHelperService._db(db)
        try:
            order_row = ScanHelperService.get_order_for_stock(order_id, db=d)
            if not order_row or not order_row["product_code"]:
                _logger.info("auto_inbound: order %s has no product_code, skip", order_id)
                return

            product_code = order_row["product_code"]
            product_name = order_row["product_name"] or product_code
            spec = (order_row["spec"] or "") if order_row else ""
            inv_id = ScanHelperService.find_or_create_inventory(
                product_code,
                product_name,
                order_id,
                spec,
                db=d,
            )

            dup = ScanHelperService.check_inventory_log_dup(order_id, serial_no, db=d)
            if dup:
                _logger.info(
                    "auto_inbound: dup detected for order %s item %s, skip",
                    order_id,
                    serial_no,
                )
                return

            ScanHelperService.stock_in(
                inv_id,
                1,
                order_id,
                order_row["order_no"],
                user_id,
                user_name,
                db=d,
            )
        except Exception as exc:
            _logger.warning("auto_inbound failed: %s", exc)
