"""Full-process quality evaluation APIs."""

from flask import g, jsonify, request

from modules.route_decorators import app, check_auth, check_permission, has_permission, safe_audit_log
from modules.services.process_quality_evaluation_service import ProcessQualityEvaluationService


def _can_read(user):
    return has_permission(user, "process_quality_evaluation:view") or has_permission(
        user, "process_quality_evaluation:submit"
    ) or has_permission(user, "process_quality_evaluation:waive") or has_permission(
        user, "process_quality_evaluation:rules"
    )


@app.route("/api/process-quality-evaluations/tasks", methods=["GET"])
@check_auth
def process_quality_tasks():
    if not _can_read(g.current_user):
        return jsonify({"error": "无权限"}), 403
    can_view_all = has_permission(g.current_user, "process_quality_evaluation:view") or has_permission(
        g.current_user, "process_quality_evaluation:waive"
    ) or has_permission(
        g.current_user, "process_quality_evaluation:rules"
    )
    requested_all = can_view_all and request.args.get("scope") == "all"
    evaluator_id = request.args.get("evaluator_user_id", type=int) if requested_all else g.current_user["id"]
    result = ProcessQualityEvaluationService.pending_tasks(
        evaluator_user_id=evaluator_id,
        status=request.args.get("status", "pending"),
        keyword=request.args.get("keyword", "").strip(),
        page=request.args.get("page", 1, type=int),
        per_page=min(request.args.get("per_page", 100, type=int), 500),
        include_target_identity=requested_all,
    )
    result["pending_count"] = ProcessQualityEvaluationService.pending_count(g.current_user["id"])
    result["pending_required_count"] = ProcessQualityEvaluationService.pending_required_count(
        g.current_user["id"]
    )
    return jsonify(result)


@app.route("/api/process-quality-evaluations/tasks/disposal-summary", methods=["GET"])
@check_auth
@check_permission("process_quality_evaluation:waive")
def process_quality_task_disposal_summary():
    return jsonify(ProcessQualityEvaluationService.task_disposal_summary(
        allow_live=has_permission(g.current_user, "process_quality_evaluation:waive_live")
    ))


@app.route("/api/process-quality-evaluations/tasks/audits", methods=["GET"])
@check_auth
@check_permission("process_quality_evaluation:waive")
def process_quality_task_audits():
    return jsonify(ProcessQualityEvaluationService.task_audits(
        keyword=request.args.get("keyword", "").strip(),
        page=request.args.get("page", 1, type=int),
        per_page=min(request.args.get("per_page", 100, type=int), 500),
    ))


@app.route("/api/process-quality-evaluations/tasks/waive", methods=["POST"])
@check_auth
@check_permission("process_quality_evaluation:waive")
def process_quality_task_waive():
    try:
        result = ProcessQualityEvaluationService.waive_tasks(
            request.get_json() or {}, g.current_user,
            allow_live=has_permission(g.current_user, "process_quality_evaluation:waive_live"),
        )
        safe_audit_log(
            "process_quality_evaluation_task_waive",
            "process_quality_evaluation_task",
            0,
            f"count={result['count']} code={result['reason_code']} "
            f"reason={(request.get_json() or {}).get('reason', '')[:120]}",
        )
        return jsonify(result)
    except PermissionError as exc:
        return jsonify({"error": str(exc)}), 403
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400


@app.route("/api/process-quality-evaluations/tasks/<int:task_id>/skip", methods=["POST"])
@check_auth
@check_permission("process_quality_evaluation:submit")
def process_quality_task_skip(task_id):
    try:
        result = ProcessQualityEvaluationService.skip_task(
            task_id, request.get_json() or {}, g.current_user
        )
        safe_audit_log("process_quality_evaluation_skip", "process_quality_evaluation_task", task_id, "skipped")
        return jsonify(result)
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400


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


@app.route("/api/process-quality-evaluations/mine", methods=["GET"])
@check_auth
def process_quality_mine():
    if not _can_read(g.current_user):
        return jsonify({"error": "无权限"}), 403
    return jsonify(ProcessQualityEvaluationService.my_evaluations(
        g.current_user,
        year_month=request.args.get("year_month", ""),
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


@app.route("/api/process-quality-evaluations/references", methods=["GET"])
@check_auth
@check_permission("process_quality_evaluation:rules")
def process_quality_references():
    return jsonify(ProcessQualityEvaluationService.references())


@app.route("/api/process-quality-evaluations/templates", methods=["GET"])
@check_auth
@check_permission("process_quality_evaluation:rules")
def process_quality_template_list():
    return jsonify({"items": ProcessQualityEvaluationService.list_templates(request.args.get("status", ""))})


@app.route("/api/process-quality-evaluations/templates", methods=["POST"])
@check_auth
@check_permission("process_quality_evaluation:rules")
def process_quality_template_create():
    try:
        result = ProcessQualityEvaluationService.save_template(
            request.get_json() or {}, g.current_user
        )
        safe_audit_log("process_quality_template_create", "process_quality_evaluation_template", result["id"], "created")
        return jsonify(result)
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400


@app.route("/api/process-quality-evaluations/templates/<int:template_id>", methods=["PUT"])
@check_auth
@check_permission("process_quality_evaluation:rules")
def process_quality_template_update(template_id):
    try:
        result = ProcessQualityEvaluationService.save_template(
            request.get_json() or {}, g.current_user, template_id
        )
        safe_audit_log("process_quality_template_update", "process_quality_evaluation_template", template_id, "updated")
        return jsonify(result)
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400


@app.route("/api/process-quality-evaluations/<int:evaluation_id>/appeals", methods=["POST"])
@check_auth
def process_quality_appeal_create(evaluation_id):
    if not _can_read(g.current_user):
        return jsonify({"error": "无权限"}), 403
    try:
        result = ProcessQualityEvaluationService.create_appeal(
            evaluation_id, request.get_json() or {}, g.current_user
        )
        safe_audit_log("process_quality_appeal_create", "process_quality_evaluation", evaluation_id, "pending")
        return jsonify(result)
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400


@app.route("/api/process-quality-evaluations/appeals", methods=["GET"])
@check_auth
def process_quality_appeal_list():
    can_review = has_permission(g.current_user, "process_quality_evaluation:review")
    mine = request.args.get("scope") == "mine"
    if not mine and not can_review:
        return jsonify({"error": "无权限"}), 403
    if mine and not _can_read(g.current_user):
        return jsonify({"error": "无权限"}), 403
    return jsonify(ProcessQualityEvaluationService.list_appeals(
        request.args.get("status", ""), g.current_user, mine=mine,
        year_month=request.args.get("year_month", ""),
    ))


@app.route("/api/process-quality-evaluations/appeals/<int:appeal_id>/review", methods=["PUT"])
@check_auth
@check_permission("process_quality_evaluation:review")
def process_quality_appeal_review(appeal_id):
    try:
        result = ProcessQualityEvaluationService.review_appeal(
            appeal_id, request.get_json() or {}, g.current_user
        )
        safe_audit_log("process_quality_appeal_review", "process_quality_evaluation_appeal", appeal_id, result["status"])
        return jsonify(result)
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400
