"""qr-system - Scan work report routes (desktop + mobile) — Service-layer refactored"""
import base64, json, logging
from datetime import datetime
from flask import request, jsonify, g, send_file
from modules.app import app
from modules.middleware.audit import audit_log
from modules.middleware.auth import check_auth, check_permission, has_permission
from modules.middleware.rate_limit import rate_limit
from modules.middleware.validate import validate_json
from modules.middleware.helpers import get_json_body
from modules.middleware.error_handler import handle_unexpected_error
from modules.middleware.data_scope import get_user_process_ids
from modules.services.scan_helper_service import ScanHelperService
# (scan_helpers functions migrated to ScanHelperService - see scan_helper_service.py)
from modules.db import get_setting
import qrcode as qrcode_lib
from io import BytesIO


@app.route("/api/scan", methods=["POST"])
@check_auth
@check_permission("scan:view")
def scan_order():
    """扫码获取订单信息（支持订单号或产品序列号）"""
    try:
        data = get_json_body()
        code = data.get("code", "").strip()
        if not code:
            return jsonify({"error": "请扫描二维码"}), 400

        # 先当订单号查
        order = ScanHelperService.get_order_by_no(code)
        item_info = None
        serial_no = None
        if not order:
            item = ScanHelperService.get_product_item(code)
            if item:
                item_info = dict(item)
                order = ScanHelperService.get_order(item["order_id"])
                if order and item_info:
                    try:
                        item_info["qr_data"] = json.loads(item["qr_content"])
                    except (json.JSONDecodeError, TypeError):
                        item_info["qr_data"] = {}

        # Fallback: if code is a plain-text serial number, look it up directly
        if not order:
            item = ScanHelperService.get_product_item(code)
            if item:
                item_info = dict(item)
                serial_no = code
                order = ScanHelperService.get_order(item["order_id"])

        if not order:
            return jsonify({"error": f"未找到订单或产品: {code}"}), 404

        # QR模式校验：序列号模式订单拒绝订单号扫描
        if not serial_no:
            o_pre = dict(order)
            _qr_mode = (o_pre.get("qr_mode") or "").strip()
            _has_items = bool(ScanHelperService.get_product_items_by_order(o_pre["id"]))
            if (_qr_mode == "serial" or _has_items) and not has_permission(g.current_user, "quality:view"):
                return jsonify({"error": "此订单为序列号模式，请扫描工件二维码"}), 400

        o = dict(order)
        if not ScanHelperService.check_order_scope(o["id"], get_user_process_ids(g.current_user)):
            return jsonify({"error": "您无权查看此订单"}), 403

        try:
            o["extra_fields"] = json.loads(o.get("extra_fields") or "{}")
        except (json.JSONDecodeError, TypeError):
            o["extra_fields"] = {}

        procs = ScanHelperService.get_order_processes(o["id"])
        all_procs = [dict(p) for p in procs]
        user_pids = get_user_process_ids(g.current_user)
        o["processes"] = [p for p in all_procs if p["process_id"] in user_pids] if user_pids is not None else all_procs

        records = ScanHelperService.get_work_records(o["id"])
        o["records"] = [dict(r) for r in records]

        if item_info:
            o["has_items"] = True
            return jsonify({"order": o, "item": item_info})
        o["has_items"] = bool(ScanHelperService.get_product_items_by_order(o["id"]))
        return jsonify({"order": o})
    except Exception as e:
        return handle_unexpected_error(e, "database operation")


# ============================================================
# Mobile H5 扫码报工 API
# ============================================================

@app.route("/api/mobile/decode/<code>", methods=["GET"])
@check_auth
@check_permission("scan:view")
def mobile_decode(code):
    """将数字编码的二维码还原为JSON"""
    try:
        code = code.strip()
        if len(code) > 2048:
            return jsonify({"error": "二维码数据过长"}), 400
        if code.startswith("N"):
            code = code[1:]
        if not code.isdigit():
            return jsonify({"code": code})

        if len(code) < 12:
            return jsonify({"error": "无效的数字编码"}), 400

        mode = code[0]
        if mode != "2":
            return jsonify({"code": code})

        try:
            order_id = int(code[1:7])
            position_no = int(code[7:12])
        except ValueError:
            return jsonify({"error": "无效的数字编码"}), 400

        item = ScanHelperService.get_product_item_by_position(order_id, position_no)
        if not item:
            order = ScanHelperService.get_order(order_id)
            if not order:
                return jsonify({"error": "未找到对应订单或产品"}), 404
            return jsonify({
                "code": json.dumps({
                    "order_id": order_id, "position_no": position_no,
                    "order_no": dict(order).get("order_no", "")
                }),
                "mode": "order_only",
                "order": {"id": order_id, "order_no": dict(order).get("order_no", "")}
            })

        item_dict = dict(item)
        try:
            item_dict["qr_data"] = json.loads(item_dict.get("qr_content") or "{}")
        except (json.JSONDecodeError, TypeError):
            item_dict["qr_data"] = {}

        return jsonify({
            "code": json.dumps({
                "order_id": order_id, "position_no": position_no,
                "serial_no": item["serial_no"]
            }),
            "item": item_dict
        })
    except Exception as e:
        return handle_unexpected_error(e, "database operation")


@app.route("/api/mobile/scan", methods=["POST"])
@check_auth
@check_permission("scan:view")
def mobile_scan():
    """扫码获取订单信息（移动端）"""
    try:
        data = get_json_body()
        code = data.get("code", "").strip()
        if not code:
            qr_text = data.get("qr_text", "").strip()
            if qr_text:
                code = qr_text
        if not code:
            return jsonify({"error": "请扫描二维码"}), 400

        parsed = None
        try:
            parsed = json.loads(code)
        except (json.JSONDecodeError, TypeError):
            pass

        order_id = None
        serial_no = None
        if parsed and isinstance(parsed, dict):
            order_id = parsed.get("order_id")
            serial_no = parsed.get("serial_no")

        order = None
        item_info = None

        if order_id:
            order = ScanHelperService.get_order(order_id)
        if not order:
            order = ScanHelperService.get_order_by_no(code)

        if serial_no and not item_info:
            item = ScanHelperService.get_product_item(serial_no)
            if item:
                item_info = dict(item)
                if not order:
                    order = ScanHelperService.get_order(item["order_id"])

        # Fallback: if code is a plain-text serial number, look it up directly
        if not order:
            item = ScanHelperService.get_product_item(code)
            if item:
                item_info = dict(item)
                serial_no = code
                order = ScanHelperService.get_order(item["order_id"])

        if not order:
            return jsonify({"error": f"未找到订单或产品: {code}"}), 404

        # QR模式校验：序列号模式订单拒绝订单号扫描
        if not serial_no:
            o_pre = dict(order)
            _qr_mode = (o_pre.get("qr_mode") or "").strip()
            _has_items = bool(ScanHelperService.get_product_items_by_order(o_pre["id"]))
            if _qr_mode == "serial" or _has_items:
                return jsonify({"error": "此订单为序列号模式，请扫描工件二维码"}), 400

        o = dict(order)
        if not ScanHelperService.check_order_scope(o["id"], get_user_process_ids(g.current_user)):
            return jsonify({"error": "您无权查看此订单"}), 403

        o["processes"] = [dict(p) for p in ScanHelperService.get_order_processes(o["id"])]
        o["records"] = [dict(r) for r in ScanHelperService.get_work_records(o["id"], limit=20)]
        # Compute current process (first incomplete one)
        o["current_process"] = None
        for proc in o["processes"]:
            if proc.get("status") != "completed":
                proc_completed = proc.get("completed") or 0
                o["current_process"] = {
                    "process_id": proc["process_id"],
                    "process_name": proc.get("process_name", ""),
                    "completed": proc_completed,
                    "total": proc.get("total_quantity", o.get("quantity", 0)),
                }
                break

        # Serial-number mode: override current_process with item's actual process
        if serial_no and item_info and item_info.get("current_process_id"):
            item_pid = item_info["current_process_id"]
            for proc in o["processes"]:
                if proc["process_id"] == item_pid:
                    proc_completed = proc.get("completed") or 0
                    o["current_process"] = {
                        "process_id": proc["process_id"],
                        "process_name": proc.get("process_name", ""),
                        "completed": proc_completed,
                        "total": proc.get("total_quantity", o.get("quantity", 0)),
                    }
                    break

        if item_info:
            try:
                item_info["qr_data"] = json.loads(item_info.get("qr_content") or "{}")
            except (json.JSONDecodeError, TypeError):
                item_info["qr_data"] = {}
            return jsonify({"order": o, "item": item_info})
        return jsonify({"order": o})
    except Exception as e:
        return handle_unexpected_error(e, "database operation")


@app.route("/api/mobile/report", methods=["POST"])
@check_auth
@check_permission("scan:report")
def mobile_report():
    """Mobile scan report (uses shared validation)."""
    try:
        data = get_json_body()
        order_id = data.get("order_id")
        process_id = data.get("process_id")
        quantity = data.get("quantity", 1)
        serial_no = data.get("serial_no", "").strip() or None
        report_type = data.get("report_type", "normal")
        remark = data.get("remark", "")
        user = g.current_user

        # Shared validation
        (err, code), quantity, serial_no = ScanHelperService.validate_report(
            order_id, process_id, user, quantity, serial_no, report_type
        )
        if err:
            return jsonify(err), code

        # Approval check
        need_approval = ScanHelperService.check_approval_required(process_id) is not None

        # Execute report write
        ScanHelperService.execute_report_write(report_type, order_id, process_id, user["id"],
            user.get("name", ""), quantity, remark, serial_no, need_approval, report_type)

        try:
            audit_log("report_" + report_type, "order", order_id,
                      "process=" + str(process_id) + " qty=" + str(quantity) + " type=" + report_type)
        except Exception:
            logging.getLogger(__name__).warning(
                "audit_log failed for report_%s: order_id=%s process_id=%s",
                report_type, order_id, process_id
            )
        return jsonify({"message": "report OK"})
    except ValueError as e:
        return jsonify({"error": str(e)}), 409
    except Exception as e:
        return handle_unexpected_error(e, "database operation")


# ============================================================
# Desktop Work Report
# ============================================================

@app.route("/api/report", methods=["POST"])
@check_auth
@check_permission("scan:report")
def work_report():
    """Desktop work report (uses shared validation)."""
    try:
        data = get_json_body()
        order_id = data.get("order_id")
        process_id = data.get("process_id")
        quantity = data.get("quantity", 1)
        serial_no = data.get("serial_no", "").strip() or None
        report_type = data.get("report_type", "normal")
        remark = data.get("remark", "")
        user = g.current_user

        if not isinstance(quantity, (int, float)) or quantity <= 0:
            return jsonify({"error": "quantity must be > 0"}), 400

        # Shared validation
        (err, code), quantity, serial_no = ScanHelperService.validate_report(
            order_id, process_id, user, quantity, serial_no, report_type
        )
        if err:
            return jsonify(err), code

        # Approval check
        need_approval = ScanHelperService.check_approval_required(process_id) is not None

        # Execute report write
        ScanHelperService.execute_report_write(report_type, order_id, process_id, user["id"],
            user.get("name", ""), quantity, remark, serial_no, need_approval, report_type)

        try:
            audit_log("report_" + report_type, "order", order_id,
                      "process=" + str(process_id) + " qty=" + str(quantity) + " type=" + report_type)
        except Exception:
            logging.getLogger(__name__).warning(
                "audit_log failed for report_%s: order_id=%s process_id=%s",
                report_type, order_id, process_id
            )

        return jsonify({"message": "report OK"})
    except ValueError as e:
        return jsonify({"error": str(e)}), 409
    except Exception as e:
        return handle_unexpected_error(e, "database operation")


# ============================================================
# QR Code Generation
# ============================================================

@app.route("/api/qrcode/<code>", methods=["GET"])
@check_auth
def generate_qrcode(code):
    """生成二维码图片"""
    try:
        qr = qrcode_lib.QRCode(version=1, box_size=10, border=4)
        qr.add_data(code)
        qr.make(fit=True)
        img = qr.make_image(fill_color="black", back_color="white")
        buf = BytesIO()
        img.save(buf, format="PNG")
        buf.seek(0)
        return send_file(buf, mimetype="image/png")
    except Exception as e:
        return jsonify({"error": str(e)}), 500
