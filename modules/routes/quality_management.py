"""HTTP endpoints for the quality management center."""

from flask import g, jsonify, request

from modules.route_decorators import app, check_auth, check_permission, get_json_body, safe_audit_log
from modules.services.quality_management_service import QualityManagementService


def _pagination():
    page = max(request.args.get("page", 1, type=int), 1)
    limit = min(max(request.args.get("limit", 100, type=int), 1), 500)
    return page, limit


@app.route("/api/quality-management/dashboard", methods=["GET"])
@check_auth
@check_permission("quality:view")
def quality_management_dashboard():
    return jsonify({"ok": True, **QualityManagementService.dashboard()})


@app.route("/api/quality-management/references", methods=["GET"])
@check_auth
@check_permission("quality:view")
def quality_management_references():
    return jsonify({"ok": True, **QualityManagementService.reference_data()})


@app.route("/api/quality-management/rules", methods=["GET"])
@check_auth
@check_permission("quality:view")
def quality_management_rules():
    return jsonify({"ok": True, **QualityManagementService.rules()})


@app.route("/api/quality-management/rules", methods=["PUT"])
@check_auth
@check_permission("quality:standards")
def quality_management_rules_update():
    rules = QualityManagementService.save_rules(get_json_body())
    safe_audit_log(
        "quality_rules_update",
        "quality_management",
        0,
        {"changed_fields": sorted(rules)},
    )
    return jsonify({"ok": True, **rules})


@app.route("/api/quality-management/standards", methods=["GET"])
@check_auth
@check_permission("quality:view")
def quality_standard_list():
    page, limit = _pagination()
    return jsonify(QualityManagementService.list_standards(
        keyword=request.args.get("keyword", ""), status=request.args.get("status", ""),
        inspection_type=request.args.get("inspection_type", ""), page=page, limit=limit,
    ))


@app.route("/api/quality-management/standards/<int:standard_id>", methods=["GET"])
@check_auth
@check_permission("quality:view")
def quality_standard_detail(standard_id):
    return jsonify({"ok": True, "standard": QualityManagementService.get_standard(standard_id)})


@app.route("/api/quality-management/standards", methods=["POST"])
@check_auth
@check_permission("quality:standards")
def quality_standard_create():
    standard_id = QualityManagementService.create_standard(get_json_body(), g.current_user.get("id"))
    safe_audit_log("quality_standard_create", "quality_standard", standard_id, "created")
    return jsonify({"ok": True, "id": standard_id})


@app.route("/api/quality-management/standards/<int:standard_id>", methods=["PUT"])
@check_auth
@check_permission("quality:standards")
def quality_standard_update(standard_id):
    QualityManagementService.update_standard(standard_id, get_json_body())
    safe_audit_log("quality_standard_update", "quality_standard", standard_id, "updated")
    return jsonify({"ok": True})


@app.route("/api/quality-management/standards/<int:standard_id>", methods=["DELETE"])
@check_auth
@check_permission("quality:standards")
def quality_standard_archive(standard_id):
    QualityManagementService.archive_standard(standard_id)
    safe_audit_log("quality_standard_archive", "quality_standard", standard_id, "inactive")
    return jsonify({"ok": True})


@app.route("/api/quality-management/plans", methods=["GET"])
@check_auth
@check_permission("quality:view")
def quality_plan_list():
    page, limit = _pagination()
    return jsonify(QualityManagementService.list_plans(
        keyword=request.args.get("keyword", ""), status=request.args.get("status", ""), page=page, limit=limit,
    ))


@app.route("/api/quality-management/plans", methods=["POST"])
@check_auth
@check_permission("quality:plans")
def quality_plan_create():
    plan_id = QualityManagementService.create_plan(get_json_body(), g.current_user.get("id"))
    safe_audit_log("quality_plan_create", "quality_plan", plan_id, "created")
    return jsonify({"ok": True, "id": plan_id})


@app.route("/api/quality-management/plans/<int:plan_id>", methods=["PUT"])
@check_auth
@check_permission("quality:plans")
def quality_plan_update(plan_id):
    QualityManagementService.update_plan(plan_id, get_json_body())
    safe_audit_log("quality_plan_update", "quality_plan", plan_id, "updated")
    return jsonify({"ok": True})


@app.route("/api/quality-management/plans/<int:plan_id>", methods=["DELETE"])
@check_auth
@check_permission("quality:plans")
def quality_plan_archive(plan_id):
    QualityManagementService.archive_plan(plan_id)
    safe_audit_log("quality_plan_archive", "quality_plan", plan_id, "inactive")
    return jsonify({"ok": True})


@app.route("/api/quality-management/tasks", methods=["GET"])
@check_auth
@check_permission("quality:view")
def quality_task_list():
    page, limit = _pagination()
    return jsonify(QualityManagementService.list_tasks(
        status=request.args.get("status", ""), inspection_type=request.args.get("inspection_type", ""),
        gate_mode=request.args.get("gate_mode", ""), keyword=request.args.get("keyword", ""),
        assigned_to=request.args.get("assigned_to", type=int), date_from=request.args.get("from", ""),
        date_to=request.args.get("to", ""), page=page, limit=limit,
    ))


@app.route("/api/quality-management/tasks/<int:task_id>", methods=["GET"])
@check_auth
@check_permission("quality:view")
def quality_task_detail(task_id):
    return jsonify({"ok": True, "task": QualityManagementService.get_task(task_id)})


@app.route("/api/quality-management/tasks", methods=["POST"])
@check_auth
@check_permission("quality:inspect")
def quality_task_create():
    task_id = QualityManagementService.create_manual_task(get_json_body(), g.current_user.get("id"))
    safe_audit_log("quality_task_create", "quality_task", task_id, "manual")
    return jsonify({"ok": True, "id": task_id})


@app.route("/api/quality-management/tasks/<int:task_id>/start", methods=["POST"])
@check_auth
@check_permission("quality:inspect")
def quality_task_start(task_id):
    QualityManagementService.start_task(task_id, g.current_user.get("id"))
    safe_audit_log("quality_task_start", "quality_task", task_id, "in_progress")
    return jsonify({"ok": True})


@app.route("/api/quality-management/tasks/<int:task_id>/inspect", methods=["POST"])
@check_auth
@check_permission("quality:inspect")
def quality_task_inspect(task_id):
    result = QualityManagementService.inspect_task(task_id, get_json_body(), g.current_user)
    safe_audit_log("quality_task_inspect", "quality_task", task_id, result["result"])
    return jsonify({"ok": True, **result})


@app.route("/api/quality-management/inspections", methods=["GET"])
@check_auth
@check_permission("quality:view")
def quality_management_inspections():
    page, limit = _pagination()
    return jsonify(QualityManagementService.list_inspections(
        keyword=request.args.get("keyword", ""), result=request.args.get("result", ""),
        inspection_type=request.args.get("inspection_type", ""), page=page, limit=limit,
    ))


@app.route("/api/quality-management/inspections/<int:inspection_id>", methods=["GET"])
@check_auth
@check_permission("quality:view")
def quality_management_inspection_detail(inspection_id):
    return jsonify({"ok": True, "inspection": QualityManagementService.get_inspection(inspection_id)})


@app.route("/api/quality-management/inspections/<int:inspection_id>/review", methods=["POST"])
@check_auth
@check_permission("quality:review")
def quality_management_inspection_review(inspection_id):
    result = QualityManagementService.review_inspection(
        inspection_id, get_json_body(), g.current_user.get("id")
    )
    safe_audit_log("quality_inspection_review", "quality_inspection", inspection_id, result["review_status"])
    return jsonify({"ok": True, **result})


@app.route("/api/quality-management/ncr", methods=["GET"])
@check_auth
@check_permission("quality:view")
def quality_ncr_list():
    page, limit = _pagination()
    return jsonify(QualityManagementService.list_ncr(
        status=request.args.get("status", ""), disposition=request.args.get("disposition", ""),
        keyword=request.args.get("keyword", ""), page=page, limit=limit,
    ))


@app.route("/api/quality-management/ncr", methods=["POST"])
@check_auth
@check_permission("quality:disposition")
def quality_ncr_create():
    ncr_id = QualityManagementService.create_ncr(get_json_body(), g.current_user.get("id"))
    safe_audit_log("quality_ncr_create", "quality_ncr", ncr_id, "manual")
    return jsonify({"ok": True, "id": ncr_id})


@app.route("/api/quality-management/ncr/<int:ncr_id>", methods=["GET"])
@check_auth
@check_permission("quality:view")
def quality_ncr_detail(ncr_id):
    return jsonify({"ok": True, "ncr": QualityManagementService.get_ncr(ncr_id)})


@app.route("/api/quality-management/ncr/<int:ncr_id>/disposition", methods=["PUT"])
@check_auth
@check_permission("quality:disposition")
def quality_ncr_disposition(ncr_id):
    result = QualityManagementService.dispose_ncr(ncr_id, get_json_body(), g.current_user.get("id"))
    safe_audit_log("quality_ncr_disposition", "quality_ncr", ncr_id, result["disposition"])
    return jsonify({"ok": True, **result})


@app.route("/api/quality-management/capa", methods=["GET"])
@check_auth
@check_permission("quality:view")
def quality_capa_list():
    page, limit = _pagination()
    return jsonify(QualityManagementService.list_capa(
        status=request.args.get("status", ""), keyword=request.args.get("keyword", ""), page=page, limit=limit,
    ))


@app.route("/api/quality-management/capa", methods=["POST"])
@check_auth
@check_permission("quality:capa")
def quality_capa_create():
    capa_id = QualityManagementService.save_capa(get_json_body(), g.current_user.get("id"))
    safe_audit_log("quality_capa_create", "quality_capa", capa_id, "created")
    return jsonify({"ok": True, "id": capa_id})


@app.route("/api/quality-management/capa/<int:capa_id>", methods=["PUT"])
@check_auth
@check_permission("quality:capa")
def quality_capa_update(capa_id):
    QualityManagementService.save_capa(get_json_body(), g.current_user.get("id"), capa_id)
    safe_audit_log("quality_capa_update", "quality_capa", capa_id, "updated")
    return jsonify({"ok": True})


@app.route("/api/quality-management/supplier-inspections", methods=["GET"])
@check_auth
@check_permission("quality:view")
def quality_supplier_inspection_list():
    page, limit = _pagination()
    return jsonify(QualityManagementService.list_supplier_inspections(
        keyword=request.args.get("keyword", ""), result=request.args.get("result", ""), page=page, limit=limit,
    ))


@app.route("/api/quality-management/supplier-inspections", methods=["POST"])
@check_auth
@check_permission("quality:supplier")
def quality_supplier_inspection_create():
    result = QualityManagementService.create_supplier_inspection(get_json_body(), g.current_user.get("id"))
    safe_audit_log("quality_supplier_inspection", "quality_supplier_inspection", result["id"], "created")
    return jsonify({"ok": True, **result})


@app.route("/api/quality-management/gauges", methods=["GET"])
@check_auth
@check_permission("quality:view")
def quality_gauge_list():
    page, limit = _pagination()
    return jsonify(QualityManagementService.list_gauges(
        keyword=request.args.get("keyword", ""), status=request.args.get("status", ""), page=page, limit=limit,
    ))


@app.route("/api/quality-management/gauges", methods=["POST"])
@check_auth
@check_permission("quality:calibration")
def quality_gauge_create():
    gauge_id = QualityManagementService.save_gauge(get_json_body(), g.current_user.get("id"))
    safe_audit_log("quality_gauge_create", "quality_gauge", gauge_id, "created")
    return jsonify({"ok": True, "id": gauge_id})


@app.route("/api/quality-management/gauges/<int:gauge_id>", methods=["PUT"])
@check_auth
@check_permission("quality:calibration")
def quality_gauge_update(gauge_id):
    QualityManagementService.save_gauge(get_json_body(), g.current_user.get("id"), gauge_id)
    safe_audit_log("quality_gauge_update", "quality_gauge", gauge_id, "updated")
    return jsonify({"ok": True})


@app.route("/api/quality-management/gauges/<int:gauge_id>/calibrations", methods=["POST"])
@check_auth
@check_permission("quality:calibration")
def quality_gauge_calibrate(gauge_id):
    calibration_id = QualityManagementService.calibrate_gauge(gauge_id, get_json_body(), g.current_user.get("id"))
    safe_audit_log("quality_gauge_calibrate", "quality_gauge", gauge_id, f"calibration={calibration_id}")
    return jsonify({"ok": True, "id": calibration_id})


@app.route("/api/quality-management/analytics", methods=["GET"])
@check_auth
@check_permission("quality:view")
def quality_management_analytics():
    return jsonify({"ok": True, **QualityManagementService.analytics(
        date_from=request.args.get("from", ""), date_to=request.args.get("to", ""),
    )})
