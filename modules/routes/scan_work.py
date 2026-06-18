"""qr-system - Scan work report routes (desktop + mobile) — Service-layer refactored"""
import base64, json
from datetime import datetime
from flask import request, jsonify, g
from modules.app import app
from modules.middleware.audit import audit_log
from modules.middleware.auth import check_auth, check_permission
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
            if _qr_mode == "serial" or _has_items:
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
    """移动端扫码报工"""
    try:
        data = get_json_body()
        order_id = data.get("order_id")
        process_id = data.get("process_id")
        quantity = data.get("quantity", 1)
        serial_no = data.get("serial_no", "").strip() or None
        report_type = data.get("report_type", "normal")
        # 系统管理员仅允许返工/报废，不可正常报工
        user_role = g.current_user.get("role", "")
        if user_role == "admin" and report_type == "normal":
            return jsonify({"error": "系统管理员仅可进行返工和报废操作，不可正常报工"}), 403
        remark = data.get("remark", "")

        if not order_id or not process_id:
            return jsonify({"error": "缺少订单或工序信息"}), 400

        # ===== 序列号模式：每件工件独立报工，数量恒为1 =====
        has_prod_items = bool(ScanHelperService.get_product_items_by_order(order_id))
        if has_prod_items and quantity > 1:
            quantity = 1
        elif serial_no and quantity > 1:
            quantity = 1

        user = g.current_user
        order = ScanHelperService.get_order(order_id)
        if not order:
            return jsonify({"error": "订单不存在"}), 404
        if not ScanHelperService.check_order_scope(order_id, get_user_process_ids(g.current_user)):
            return jsonify({"error": "您无权对此订单报工"}), 403

        # ===== 序列号模式守卫 =====
        has_items_m = bool(ScanHelperService.get_product_items_by_order(order_id))
        if has_items_m and not serial_no:
            return jsonify({"error": "此订单为序列号模式，请扫描工件二维码"}), 400

        op_check = ScanHelperService.check_process_in_order(order_id, process_id)
        if not op_check:
            return jsonify({"error": "该工序不在订单工艺路线中"}), 400

        # ===== 跨工序防重复（序列号在此订单整体已报工） =====
        if serial_no and ScanHelperService.check_serial_duplicate_in_order(order_id, serial_no, user["id"]):
            return jsonify({"error": f"序列号 {serial_no} 在此订单已报工，不可重复扫码！"}), 409

        # ===== 防重复报工 =====
        if report_type == "normal":
            dup = ScanHelperService.check_duplicate_normal_report(order_id, process_id, serial_no, user["id"])
            if dup:
                msg = f"序列号 {serial_no} 在此工序已报工，不可重复扫码！" if serial_no else "此工序您已报工，不可重复扫码"
                return jsonify({"error": msg}), 409
        elif report_type in ("scrap", "rework"):
            dup = ScanHelperService.check_duplicate_defect_report(order_id, process_id, user["id"], report_type)
            if dup:
                return jsonify({"error": "请勿短时间重复提交"}), 409

        # ===== 工序级权限校验 =====
        user_pids = get_user_process_ids(g.current_user)
        if user_pids is not None and process_id not in user_pids:
            return jsonify({"error": "您无权对此工序报工"}), 403

        # ===== 工序存在性校验（获取完整信息） =====
        current_op = ScanHelperService.get_order_process(order_id, process_id)
        if order["route_id"] and not current_op:
            return jsonify({"error": "该工序不在订单工艺路线中"}), 400
        current_seq = current_op["seq_order"] if current_op else 0

        # ===== 顺序报工检查 =====
        err, code = ScanHelperService.check_process_order(order_id, current_seq)
        if err:
            return jsonify(err), code

        # ===== 数量上限检查 =====
        err, code = ScanHelperService.check_quantity_limits(
            order_id, current_seq, current_op["completed"] or 0, quantity, order["quantity"])
        if err:
            return jsonify(err), code

        # 审批检查
        need_approval = ScanHelperService.check_approval_required(process_id) is not None

        # 使用共享报工写入逻辑
        ScanHelperService.execute_report_write(report_type, order_id, process_id, user["id"], user.get("name", ""),
                              quantity, remark, serial_no, need_approval, report_type)

        try:
            audit_log("report_" + report_type, "order", order_id,
                      "process=" + str(process_id) + " qty=" + str(quantity) + " type=" + report_type)
        except Exception:
            pass
        return jsonify({"message": "报工成功"})
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
    """桌面端报工（含完整业务校验）"""
    try:
        data = get_json_body()
        order_id = data.get("order_id")
        process_id = data.get("process_id")
        quantity = data.get("quantity", 1)
        serial_no = data.get("serial_no", "").strip() or None
        report_type = data.get("report_type", "normal")
        # 系统管理员仅允许返工/报废，不可正常报工
        user_role = g.current_user.get("role", "")
        if user_role == "admin" and report_type == "normal":
            return jsonify({"error": "系统管理员仅可进行返工和报废操作，不可正常报工"}), 403
        remark = data.get("remark", "")

        if not order_id or not process_id:
            return jsonify({"error": "缺少订单或工序信息"}), 400
        if not isinstance(quantity, (int, float)) or quantity <= 0:
            return jsonify({"error": "报工数量必须大于0"}), 400

        if serial_no and quantity > 1:
            quantity = 1

        user = g.current_user

        # ===== 订单校验 =====
        order = ScanHelperService.get_order(order_id)
        if not order:
            return jsonify({"error": "订单不存在"}), 404
        if not ScanHelperService.check_order_scope(order_id, get_user_process_ids(g.current_user)):
            return jsonify({"error": "您无权对此订单报工"}), 403

        # ===== 序列号模式守卫 =====
        has_items_wr = bool(ScanHelperService.get_product_items_by_order(order_id))
        if has_items_wr and not serial_no:
            return jsonify({"error": "此订单为序列号模式，请扫描工件二维码"}), 400

        # ===== 工序存在性校验 =====
        op_check = ScanHelperService.check_process_in_order(order_id, process_id)
        if not op_check:
            return jsonify({"error": "该工序不在订单工艺路线中"}), 400


        # ===== 防重复报工 =====
        if report_type == "normal":
            dup = ScanHelperService.check_duplicate_normal_report(order_id, process_id, serial_no, user["id"])
            if dup:
                msg = f"序列号 {serial_no} 在此工序已报工，不可重复扫码！" if serial_no else "此工序您已报工，不可重复扫码"
                return jsonify({"error": msg}), 409
        elif report_type in ("scrap", "rework"):
            dup = ScanHelperService.check_duplicate_defect_report(order_id, process_id, user["id"], report_type)
            if dup:
                return jsonify({"error": "请勿短旴间重复提交"}), 409
        # ===== 工序级权限校验 =====
        user_pids = get_user_process_ids(g.current_user)
        if user_pids is not None and process_id not in user_pids:
            return jsonify({"error": "您无权对此工序报工"}), 403

        current_op = ScanHelperService.get_order_process(order_id, process_id)
        if order["route_id"] and not current_op:
            return jsonify({"error": "该工序不在订单工艺路线中"}), 400
        current_seq = current_op["seq_order"] if current_op else 0

        # ===== 顺序报工检查 =====
        err, code = ScanHelperService.check_process_order(order_id, current_seq)
        if err:
            return jsonify(err), code

        # ===== 数量上限检查 =====
        err, code = ScanHelperService.check_quantity_limits(
            order_id, current_seq, current_op["completed"] or 0, quantity, order["quantity"])
        if err:
            return jsonify(err), code

        # ===== 审批检查 =====
        need_approval = ScanHelperService.check_approval_required(process_id) is not None

        # Serial number: validate item's current process matches
        if serial_no and report_type == "normal":
            item = ScanHelperService.get_product_item(serial_no)
            if item and item["current_process_id"] and item["current_process_id"] != process_id:
                return jsonify({"error": f"序列号 {serial_no} 当前不在该工序，请刷新后重试"}), 400

        # ===== 共享报工写入 =====
        ScanHelperService.execute_report_write(report_type, order_id, process_id, user["id"], user.get("name", ""),
                              quantity, remark, serial_no, need_approval, report_type)

        try:
            audit_log("report_" + report_type, "order", order_id,
                      "process=" + str(process_id) + " qty=" + str(quantity) + " type=" + report_type)
        except Exception:
            pass

        return jsonify({'message': '报工成功'})
    except ValueError as e:
        return jsonify({'error': str(e)}), 409
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
        return buf.getvalue(), 200, {"Content-Type": "image/png"}
    except Exception as e:
        return jsonify({"error": str(e)}), 500
