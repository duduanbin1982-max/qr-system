"""Full-process quality evaluation APIs."""

from flask import g, jsonify, request

from modules.route_decorators import app, check_auth, check_permission, has_permission, safe_audit_log
from modules.services.process_quality_evaluation_service import ProcessQualityEvaluationService


def _can_read(user):
    return has_permission(user, "process_quality_evaluation:view") or has_permission(
        user, "process_quality_evaluation:submit"
    )


@app.route("/api/process-quality-evaluations/tasks", methods=["GET"])
@check_auth
def process_quality_tasks():
    if not _can_read(g.current_user):
        return jsonify({"error": "无权限"}), 403
    can_view_all = has_permission(g.current_user, "process_quality_evaluation:view")
    requested_all = can_view_all and request.args.get("scope") == "all"
    evaluator_id = request.args.get("evaluator_user_id", type=int) if requested_all else g.current_user["id"]
    result = ProcessQualityEvaluationService.pending_tasks(
        evaluator_user_id=evaluator_id,
        status=request.args.get("status", "pending"),
        keyword=request.args.get("keyword", "").strip(),
        page=request.args.get("page", 1, type=int),
        per_page=min(request.args.get("per_page", 100, type=int), 500),
    )
    result["pending_count"] = ProcessQualityEvaluationService.pending_count(g.current_user["id"])
    return jsonify(result)


@app.route("/api/process-quality-evaluations", methods=["POST"])
@check_auth
@check_permission("process_quality_evaluation:submit")
def process_quality_submit():
    try:
        result = ProcessQualityEvaluationService.submit(request.get_json() or {}, g.current_user)
        safe_audit_log("process_quality_evaluation_submit", "process_quality_evaluation", 0, str(len(result["items"])))
        return jsonify(result)
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400


@app.route("/api/process-quality-evaluations", methods=["GET"])
@check_auth
@check_permission("process_quality_evaluation:view")
def process_quality_list():
    return jsonify(ProcessQualityEvaluationService.list_evaluations(
        year_month=request.args.get("year_month", ""),
        status=request.args.get("status", ""),
        process_id=request.args.get("process_id", type=int),
        user_id=request.args.get("user_id", type=int),
        keyword=request.args.get("keyword", "").strip(),
        page=request.args.get("page", 1, type=int),
        per_page=min(request.args.get("per_page", 100, type=int), 500),
    ))


@app.route("/api/process-quality-evaluations/<int:evaluation_id>/review", methods=["PUT"])
@check_auth
@check_permission("process_quality_evaluation:review")
def process_quality_review(evaluation_id):
    try:
        result = ProcessQualityEvaluationService.review(evaluation_id, request.get_json() or {}, g.current_user)
        safe_audit_log("process_quality_evaluation_review", "process_quality_evaluation", evaluation_id, result["status"])
        return jsonify(result)
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400


@app.route("/api/process-quality-evaluations/stats", methods=["GET"])
@check_auth
@check_permission("process_quality_evaluation:stats")
def process_quality_stats():
    return jsonify(ProcessQualityEvaluationService.stats(request.args.get("year_month", "")))


@app.route("/api/process-quality-evaluations/rules", methods=["GET"])
@check_auth
def process_quality_rules():
    if not _can_read(g.current_user):
        return jsonify({"error": "无权限"}), 403
    return jsonify(ProcessQualityEvaluationService.rules())


@app.route("/api/process-quality-evaluations/rules", methods=["PUT"])
@check_auth
@check_permission("process_quality_evaluation:rules")
def process_quality_save_rules():
    try:
        result = ProcessQualityEvaluationService.save_rules(request.get_json() or {})
        safe_audit_log("process_quality_evaluation_rules", "system_setting", 0, "updated")
        return jsonify(result)
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400
