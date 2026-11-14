"""Versioned payroll ledger HTTP API."""

import csv
import io

from flask import g, jsonify, request, send_file

from modules.csv_utils import safe_csv_cell
from modules.middleware.auth import has_permission
from modules.middleware.validate import validate_json
from modules.route_decorators import app, check_auth, safe_audit_log
from modules.services.payroll_service import PayrollAuditService, PayrollWorkflowService
from modules.services.payroll_read_service import PayrollReadService
from modules.services.payroll_settlement_service import (
    MAX_RECEIPT_BYTES,
    PayrollSettlementService,
)
from modules.services.price_version_service import PriceVersionService
from modules.services.historical_price_binding_service import HistoricalPriceBindingService
from modules.domain.payroll_policy import PayrollConflictError
from modules.domain.errors import DomainError


def _allowed(*permissions):
    user = getattr(g, "current_user", {}) or {}
    return any(has_permission(user, permission) for permission in permissions)


def _deny():
    return jsonify({"error": "无权限"}), 403


def _json_error(exc):
    if isinstance(exc, DomainError):
        return jsonify(exc.to_payload()), exc.status_code
    if isinstance(exc, PayrollConflictError):
        return jsonify({"error": str(exc)}), 409
    return jsonify({"error": str(exc)}), 400


def _no_store_json(payload, status=200):
    response = jsonify(payload)
    response.headers["Cache-Control"] = "no-store"
    return response if status == 200 else (response, status)


def _actor():
    return getattr(g, "current_user", {}) or {}


def _idempotency_key(data=None):
    data = data or {}
    return request.headers.get("Idempotency-Key") or data.get("idempotency_key")


def _json_object():
    data = request.get_json(silent=True)
    if data is None:
        return {}
    if not isinstance(data, dict):
        raise ValueError("请求内容必须是 JSON 对象")
    return data


@app.route("/api/payroll/me", methods=["GET"])
@check_auth
def payroll_me():
    if not _allowed("wages:view_self", "wages:view_all", "wages:prepare", "wages:approve"):
        return _deny()
    try:
        return jsonify(PayrollWorkflowService.my_payroll(_actor(), request.args.get("payroll_month", "")))
    except ValueError as exc:
        return _json_error(exc)


@app.route("/api/payroll/batches", methods=["GET"])
@check_auth
def payroll_batches():
    if not _allowed("wages:view_all", "wages:prepare", "wages:approve"):
        return _deny()
    return jsonify(PayrollWorkflowService.list_batches(
        request.args.get("payroll_month", ""), request.args.get("status", "")
    ))


@app.route("/api/payroll/periods/<payroll_month>/control", methods=["GET"])
@check_auth
def payroll_period_control(payroll_month):
    if not _allowed("wages:view_all", "wages:prepare", "wages:approve"):
        return _deny()
    try:
        return jsonify(PayrollWorkflowService.period_control(payroll_month))
    except ValueError as exc:
        return _json_error(exc)


@app.route("/api/payroll/batches", methods=["POST"])
@check_auth
def payroll_batch_create():
    if not _allowed("wages:prepare"):
        return _deny()
    data = request.get_json() or {}
    key = request.headers.get("Idempotency-Key") or data.get("idempotency_key")
    try:
        result = PayrollWorkflowService.create_batch(
            data.get("payroll_month") or data.get("year_month"), _actor(), key,
            str(data.get("revision_reason") or ""), data.get("supersedes_batch_id"),
        )
        safe_audit_log("payroll_batch_generate", "payroll_batch", result.get("id", result.get("batch_id", 0)), "")
        return jsonify(result)
    except (ValueError, RuntimeError) as exc:
        return _json_error(exc)


@app.route("/api/payroll/batches/<int:batch_id>", methods=["GET"])
@check_auth
def payroll_batch_detail(batch_id):
    if not _allowed("wages:view_all", "wages:prepare", "wages:approve"):
        return _deny()
    try:
        return jsonify(PayrollWorkflowService.batch_detail(batch_id))
    except ValueError as exc:
        return _json_error(exc)


@app.route("/api/payroll/batches/<int:batch_id>/lines", methods=["GET"])
@check_auth
def payroll_batch_lines(batch_id):
    can_view_all = _allowed("wages:view_all", "wages:prepare", "wages:approve")
    if not can_view_all and not _allowed("wages:view_self"):
        return _deny()
    try:
        employee_id = PayrollReadService.employee_scope(
            _actor().get("id"),
            request.args.get("employee_id"),
            can_view_all=can_view_all,
        )
        if can_view_all:
            result = PayrollWorkflowService.batch_detail(batch_id, employee_id)
        else:
            result = PayrollReadService.confirmed_employee_detail(batch_id, employee_id)
        return jsonify(result)
    except ValueError as exc:
        return _json_error(exc)


@app.route("/api/payroll/batches/<int:batch_id>/regenerate", methods=["POST"])
@check_auth
def payroll_batch_regenerate(batch_id):
    if not _allowed("wages:prepare"):
        return _deny()
    data = request.get_json() or {}
    try:
        result = PayrollWorkflowService.regenerate(batch_id, _actor(), data.get("row_version"))
        safe_audit_log("payroll_batch_regenerate", "payroll_batch", batch_id, "")
        return jsonify(result)
    except (ValueError, RuntimeError) as exc:
        return _json_error(exc)


def _transition_route(batch_id, action):
    if not _allowed("wages:approve"):
        return _deny()
    data = request.get_json() or {}
    try:
        result = getattr(PayrollWorkflowService, action)(batch_id, _actor(), data.get("row_version"))
        safe_audit_log("payroll_batch_" + action, "payroll_batch", batch_id, "")
        return jsonify(result)
    except (ValueError, RuntimeError) as exc:
        return _json_error(exc)


@app.route("/api/payroll/batches/<int:batch_id>/submit", methods=["POST"])
@check_auth
def payroll_batch_submit(batch_id):
    if not _allowed("wages:prepare"):
        return _deny()
    data = request.get_json() or {}
    try:
        return jsonify(PayrollWorkflowService.submit(batch_id, _actor(), data.get("row_version")))
    except (ValueError, RuntimeError) as exc:
        return _json_error(exc)


@app.route("/api/payroll/batches/<int:batch_id>/lock", methods=["POST"])
@check_auth
def payroll_batch_lock(batch_id):
    return _transition_route(batch_id, "lock")


@app.route("/api/payroll/batches/<int:batch_id>/confirm", methods=["POST"])
@check_auth
def payroll_batch_confirm(batch_id):
    return _transition_route(batch_id, "confirm")


@app.route("/api/payroll/batches/<int:batch_id>/void", methods=["POST"])
@check_auth
def payroll_batch_void(batch_id):
    if not _allowed("wages:approve"):
        return _deny()
    data = request.get_json() or {}
    try:
        return jsonify(PayrollWorkflowService.void(batch_id, _actor(), data.get("row_version"), data.get("reason")))
    except (ValueError, RuntimeError) as exc:
        return _json_error(exc)


@app.route("/api/payroll/batches/<int:batch_id>/revisions", methods=["POST"])
@check_auth
def payroll_batch_revision(batch_id):
    if not _allowed("wages:prepare"):
        return _deny()
    data = request.get_json() or {}
    key = request.headers.get("Idempotency-Key") or data.get("idempotency_key")
    try:
        source = PayrollWorkflowService.batch_detail(batch_id)["batch"]
        result = PayrollWorkflowService.create_batch(
            source["payroll_month"], _actor(), key, data.get("revision_reason", ""), batch_id
        )
        return jsonify(result)
    except (ValueError, RuntimeError) as exc:
        return _json_error(exc)


@app.route("/api/payroll/batches/<int:batch_id>/compare/<int:other_id>", methods=["GET"])
@check_auth
def payroll_batch_compare(batch_id, other_id):
    if not _allowed("wages:view_all", "wages:prepare", "wages:approve"):
        return _deny()
    try:
        return jsonify(PayrollWorkflowService.compare_batches(batch_id, other_id))
    except ValueError as exc:
        return _json_error(exc)


@app.route("/api/payroll/batches/<int:batch_id>/export", methods=["GET"])
@check_auth
def payroll_batch_export(batch_id):
    if not _allowed("wages:export"):
        return _deny()
    from modules.domain.payroll_policy import cents_to_yuan

    try:
        batch, lines = PayrollWorkflowService.export_data(batch_id)
    except ValueError as exc:
        return _json_error(exc)
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["工资月", "版本", "员工", "工号", "正常工资", "返工工资", "奖金", "补贴", "扣款", "应发工资"])
    for line in lines:
        values = [
            batch["payroll_month"], batch["version"], line["employee_name_snapshot"], line["employee_no_snapshot"],
            cents_to_yuan(line["normal_wage_cents"]), cents_to_yuan(line["rework_wage_cents"]),
            cents_to_yuan(line["bonus_cents"]), cents_to_yuan(line["allowance_cents"]),
            cents_to_yuan(line["deduction_cents"]), cents_to_yuan(line["payable_wage_cents"]),
        ]
        writer.writerow([safe_csv_cell(value) for value in values])
    output.seek(0)
    safe_audit_log("payroll_export_preview", "payroll_batch", batch_id, "preview only")
    response = send_file(
        io.BytesIO(output.getvalue().encode("utf-8-sig")),
        mimetype="text/csv; charset=utf-8-sig", as_attachment=True,
        download_name=f"payroll_preview_{batch['payroll_month']}_v{batch['version']}.csv",
    )
    response.headers["X-Payroll-Export-Mode"] = "preview"
    response.headers["X-Payroll-Export-Notice"] = (
        "Preview only; use settlement export APIs for payment lists."
    )
    response.headers["Cache-Control"] = "no-store"
    return response


@app.route("/api/payroll/batches/<int:batch_id>/settlement", methods=["GET"])
@check_auth
def payroll_settlement_detail(batch_id):
    if not _allowed("wages:view_all", "wages:prepare", "wages:approve"):
        return _deny()
    try:
        return _no_store_json(PayrollSettlementService.get_by_batch(batch_id))
    except (ValueError, RuntimeError) as exc:
        return _json_error(exc)


@app.route("/api/payroll/batches/<int:batch_id>/settlement/exports", methods=["POST"])
@check_auth
def payroll_settlement_export_create(batch_id):
    if not _allowed("wages:export"):
        return _deny()
    try:
        data = _json_object()
        result = PayrollSettlementService.create_export(
            batch_id, _actor(), _idempotency_key(data)
        )
        safe_audit_log(
            "payroll_settlement_export_created", "payroll_batch", batch_id,
            str(result.get("id", "")),
        )
        return _no_store_json(result, 200 if result.get("replayed") else 201)
    except (ValueError, RuntimeError) as exc:
        return _json_error(exc)


@app.route("/api/payroll/settlement/exports/<int:export_id>/download", methods=["GET"])
@check_auth
def payroll_settlement_export_download(export_id):
    if not _allowed("wages:export"):
        return _deny()
    try:
        content = PayrollSettlementService.download_export(export_id)
        safe_audit_log(
            "payroll_settlement_export_downloaded", "payroll_export_batch", export_id, ""
        )
        response = send_file(
            io.BytesIO(content),
            mimetype="text/csv; charset=utf-8-sig",
            as_attachment=True,
            download_name=f"payroll_payment_list_{export_id}.csv",
        )
        response.headers["X-Payroll-Export-Mode"] = "payment_list"
        response.headers["Cache-Control"] = "no-store"
        return response
    except (ValueError, RuntimeError) as exc:
        return _json_error(exc)


@app.route("/api/payroll/settlement/exports/<int:export_id>/receipts", methods=["POST"])
@check_auth
def payroll_settlement_receipt_upload(export_id):
    if not _allowed("wages:receipt"):
        return _deny()
    if (
        request.content_length is not None
        and request.content_length > MAX_RECEIPT_BYTES + 64 * 1024
    ):
        return jsonify({"error": "回执文件不能超过 2 MB"}), 413
    receipt_file = request.files.get("file") or request.files.get("receipt")
    if receipt_file is None:
        return jsonify({"error": "缺少回执 CSV 文件"}), 400
    content = receipt_file.stream.read(MAX_RECEIPT_BYTES + 1)
    if len(content) > MAX_RECEIPT_BYTES:
        return jsonify({"error": "回执文件不能超过 2 MB"}), 400
    try:
        result = PayrollSettlementService.upload_receipt(
            export_id,
            _actor(),
            request.headers.get("Idempotency-Key") or request.form.get("idempotency_key"),
            receipt_file.filename,
            content,
        )
        safe_audit_log(
            "payroll_settlement_receipt_uploaded", "payroll_export_batch", export_id,
            str(result.get("id", "")),
        )
        return _no_store_json(result, 200 if result.get("replayed") else 201)
    except (ValueError, RuntimeError) as exc:
        return _json_error(exc)


@app.route("/api/payroll/settlements/<int:settlement_id>/reconcile", methods=["POST"])
@check_auth
def payroll_settlement_reconcile(settlement_id):
    if not _allowed("wages:reconcile"):
        return _deny()
    try:
        data = _json_object()
        result = PayrollSettlementService.reconcile(
            settlement_id, _actor(), _idempotency_key(data)
        )
        safe_audit_log(
            "payroll_settlement_reconciled", "payroll_settlement", settlement_id,
            str(result.get("id", "")),
        )
        return _no_store_json(result, 200 if result.get("replayed") else 201)
    except (ValueError, RuntimeError) as exc:
        return _json_error(exc)


@app.route("/api/payroll/settlement/differences/<int:item_id>/resolve", methods=["POST"])
@check_auth
def payroll_settlement_difference_resolve(item_id):
    if not _allowed("wages:reconcile"):
        return _deny()
    try:
        data = _json_object()
        data["idempotency_key"] = _idempotency_key(data)
        result = PayrollSettlementService.resolve_difference(item_id, _actor(), data)
        safe_audit_log(
            "payroll_settlement_difference_resolved",
            "payroll_reconciliation_item", item_id,
            str(data.get("resolution_code", "")),
        )
        return _no_store_json(result, 200 if result.get("replayed") else 201)
    except (ValueError, RuntimeError) as exc:
        return _json_error(exc)


@app.route("/api/payroll/settlements/<int:settlement_id>/close", methods=["POST"])
@check_auth
def payroll_settlement_close(settlement_id):
    if not _allowed("wages:close"):
        return _deny()
    try:
        data = _json_object()
        data["idempotency_key"] = _idempotency_key(data)
        result = PayrollSettlementService.close(settlement_id, _actor(), data)
        safe_audit_log(
            "payroll_settlement_closed", "payroll_settlement", settlement_id,
            str(result.get("id", "")),
        )
        return _no_store_json(result, 200 if result.get("replayed") else 201)
    except (ValueError, RuntimeError) as exc:
        return _json_error(exc)


@app.route("/api/payroll/exceptions", methods=["GET"])
@check_auth
def payroll_exceptions():
    if not _allowed("wages:view_all", "wages:prepare", "wages:approve"):
        return _deny()
    return jsonify(PayrollWorkflowService.list_exceptions(
        request.args.get("payroll_month", ""), request.args.get("batch_id", type=int), request.args.get("status", "")
    ))


@app.route("/api/payroll/exceptions/<int:exception_id>/propose", methods=["POST"])
@check_auth
def payroll_exception_propose(exception_id):
    if not _allowed("wages:prepare"):
        return _deny()
    try:
        return jsonify(PayrollWorkflowService.propose_exception(exception_id, _actor(), request.get_json() or {}))
    except (ValueError, RuntimeError) as exc:
        return _json_error(exc)


@app.route("/api/payroll/exceptions/<int:exception_id>/approve", methods=["POST"])
@check_auth
def payroll_exception_approve(exception_id):
    if not _allowed("wages:approve"):
        return _deny()
    try:
        return jsonify(PayrollWorkflowService.approve_exception(exception_id, _actor()))
    except (ValueError, RuntimeError) as exc:
        return _json_error(exc)


@app.route("/api/payroll/audit-findings", methods=["GET"])
@check_auth
def payroll_audit_findings():
    if not _allowed("wages:view_all", "wages:prepare", "wages:approve"):
        return _deny()
    return _no_store_json(PayrollWorkflowService.list_audit_findings(
        request.args.get("payroll_month", ""),
        request.args.get("batch_id", type=int),
        request.args.get("status", ""),
        request.args.get("severity", ""),
        request.args.get("finding_type", ""),
        request.args.get("include_history") == "1",
    ))


@app.route("/api/payroll/audit-findings/<int:finding_id>/resolve", methods=["POST"])
@check_auth
def payroll_audit_finding_resolve(finding_id):
    if not _allowed("wages:approve"):
        return _deny()
    try:
        return _no_store_json(PayrollAuditService.resolve(
            finding_id, _actor(), _json_object()
        ))
    except (ValueError, RuntimeError) as exc:
        return _json_error(exc)


@app.route("/api/payroll/adjustments", methods=["GET"])
@check_auth
def payroll_adjustments():
    if not _allowed("wages:view_all", "wages:prepare", "wages:approve"):
        return _deny()
    return jsonify(PayrollWorkflowService.list_adjustments(
        request.args.get("payroll_month", ""), request.args.get("employee_id", type=int)
    ))


@app.route("/api/payroll/adjustments", methods=["POST"])
@check_auth
def payroll_adjustment_create():
    if not _allowed("wages:prepare"):
        return _deny()
    try:
        data = _json_object()
        data["idempotency_key"] = _idempotency_key(data)
        return jsonify(PayrollWorkflowService.create_adjustment(_actor(), data))
    except (ValueError, RuntimeError) as exc:
        return _json_error(exc)


@app.route("/api/payroll/adjustments/<int:adjustment_id>/reverse", methods=["POST"])
@check_auth
def payroll_adjustment_reverse(adjustment_id):
    if not _allowed("wages:prepare"):
        return _deny()
    try:
        data = _json_object()
        return jsonify(PayrollWorkflowService.reverse_adjustment(
            adjustment_id, _actor(), data.get("reason"), _idempotency_key(data)
        ))
    except (ValueError, RuntimeError) as exc:
        return _json_error(exc)


@app.route("/api/route-price-versions", methods=["GET"])
@check_auth
def route_price_versions():
    if not _allowed("wages:view_all", "wages:prepare", "wages:approve"):
        return _deny()
    return jsonify({"versions": PriceVersionService.list_versions(
        request.args.get("route_id", type=int),
        request.args.get("status", ""),
        request.args.get("route_version_id", type=int),
        request.args.get("process_version_id", type=int),
    )})


@app.route("/api/route-price-versions/reference", methods=["GET"])
@check_auth
def route_price_version_reference():
    if not _allowed("wages:prepare", "wages:approve"):
        return _deny()
    include_pending = str(request.args.get("include_pending") or "").lower() in {
        "1", "true", "yes", "on"
    }
    return jsonify({"items": PriceVersionService.reference_items(include_pending)})


@app.route("/api/route-price-versions", methods=["POST"])
@check_auth
@validate_json("route_price_version_create")
def route_price_version_create():
    if not _allowed("wages:prepare"):
        return _deny()
    try:
        return jsonify(PriceVersionService.create(request.get_json() or {}, _actor()))
    except (ValueError, RuntimeError) as exc:
        return _json_error(exc)


@app.route("/api/route-price-versions/<int:version_id>/void", methods=["POST"])
@check_auth
@validate_json("route_price_version_void")
def route_price_version_void(version_id):
    if not _allowed("wages:prepare"):
        return _deny()
    try:
        return jsonify(
            PriceVersionService.void(version_id, request.get_json() or {}, _actor())
        )
    except (ValueError, RuntimeError) as exc:
        return _json_error(exc)


@app.route("/api/route-price-versions/<int:version_id>/approve", methods=["POST"])
@check_auth
def route_price_version_approve(version_id):
    if not _allowed("wages:approve"):
        return _deny()
    try:
        return jsonify(PriceVersionService.approve(
            version_id, _actor(), (request.get_json() or {}).get("row_version")
        ))
    except (ValueError, RuntimeError) as exc:
        return _json_error(exc)


@app.route("/api/historical-price-binding-repairs/manual-reviews", methods=["GET"])
@check_auth
def historical_price_manual_reviews():
    """List readable historical price confirmations without leaking internal keys."""
    if not _allowed("wages:view_all", "wages:prepare", "wages:approve"):
        return _deny()
    try:
        return jsonify(HistoricalPriceBindingService.list_manual_reviews())
    except (ValueError, RuntimeError) as exc:
        return _json_error(exc)


@app.route(
    "/api/historical-price-binding-repairs/manual-reviews/<int:review_id>/drafts",
    methods=["POST"],
)
@check_auth
@validate_json("historical_price_manual_draft_create")
def historical_price_manual_draft_create(review_id):
    if not _allowed("wages:prepare"):
        return _deny()
    try:
        return jsonify(
            HistoricalPriceBindingService.create_draft(
                review_id, request.get_json() or {}, _actor()
            )
        )
    except (ValueError, RuntimeError) as exc:
        return _json_error(exc)


@app.route(
    "/api/historical-price-binding-repair-drafts/<int:draft_id>/void",
    methods=["POST"],
)
@check_auth
@validate_json("historical_price_manual_draft_void")
def historical_price_manual_draft_void(draft_id):
    if not _allowed("wages:prepare"):
        return _deny()
    try:
        return jsonify(
            HistoricalPriceBindingService.void_draft(
                draft_id, request.get_json() or {}, _actor()
            )
        )
    except (ValueError, RuntimeError) as exc:
        return _json_error(exc)


@app.route(
    "/api/historical-price-binding-repair-drafts/<int:draft_id>/approve",
    methods=["POST"],
)
@check_auth
@validate_json("historical_price_manual_draft_approve")
def historical_price_manual_draft_approve(draft_id):
    if not _allowed("wages:approve"):
        return _deny()
    try:
        return jsonify(
            HistoricalPriceBindingService.approve_draft(
                draft_id, request.get_json() or {}, _actor()
            )
        )
    except (ValueError, RuntimeError) as exc:
        return _json_error(exc)
