"""Full-process quality evaluation APIs."""

from flask import g, jsonify, request

from modules.domain.errors import DomainError
from modules.route_decorators import app, check_auth, check_permission, has_permission, safe_audit_log
from modules.services.process_quality_evaluation_service import ProcessQualityEvaluationService
from modules.services.process_quality_evaluation_waiver_service import (
    ProcessQualityEvaluationWaiverService,
)


def _quality_pagination(default=100, maximum=500):
    """Parse pagination without silently accepting invalid client input."""
    raw_page = request.args.get("page")
    raw_per_page = request.args.get("per_page")
    try:
        page = int(raw_page) if raw_page is not None else 1
        per_page = int(raw_per_page) if raw_per_page is not None else default
    except (TypeError, ValueError) as exc:
        raise ValueError("分页参数必须是整数") from exc
    if page < 1:
        raise ValueError("页码必须大于等于1")
    if per_page < 1 or per_page > maximum:
        raise ValueError(f"每页数量必须在1到{maximum}之间")
    return page, per_page


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
    try:
        page, per_page = _quality_pagination()
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400
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
        page=page,
        per_page=per_page,
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
    return jsonify(ProcessQualityEvaluationWaiverService.task_disposal_summary(
        allow_live=has_permission(g.current_user, "process_quality_evaluation:waive_live")
    ))


@app.route("/api/process-quality-evaluations/tasks/audits", methods=["GET"])
@check_auth
@check_permission("process_quality_evaluation:waive")
def process_quality_task_audits():
    try:
        page, per_page = _quality_pagination()
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400
    return jsonify(ProcessQualityEvaluationWaiverService.task_audits(
        keyword=request.args.get("keyword", "").strip(),
        page=page,
        per_page=per_page,
    ))


@app.route("/api/process-quality-evaluations/tasks/waive", methods=["POST"])
@check_auth
@check_permission("process_quality_evaluation:waive")
def process_quality_task_waive():
    try:
        result = ProcessQualityEvaluationWaiverService.waive_tasks(
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


@app.route("/api/process-quality-evaluations/tasks/waiver-preview", methods=["POST"])
@check_auth
@check_permission("process_quality_evaluation:waive")
def process_quality_task_waiver_preview():
    try:
        return jsonify(ProcessQualityEvaluationWaiverService.waiver_preview(
            request.get_json() or {},
            allow_live=has_permission(g.current_user, "process_quality_evaluation:waive_live"),
        ))
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
    except DomainError as exc:
        return jsonify(exc.to_payload()), exc.status_code
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
    except DomainError as exc:
        return jsonify(exc.to_payload()), exc.status_code
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400


@app.route("/api/process-quality-evaluations", methods=["GET"])
@check_auth
@check_permission("process_quality_evaluation:view")
def process_quality_list():
    try:
        page, per_page = _quality_pagination()
        return jsonify(ProcessQualityEvaluationService.list_evaluations(
            year_month=request.args.get("year_month", ""),
            status=request.args.get("status", ""),
            process_id=request.args.get("process_id", type=int),
            user_id=request.args.get("user_id", type=int),
            keyword=request.args.get("keyword", "").strip(),
            page=page,
            per_page=per_page,
        ))
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400


@app.route("/api/process-quality-evaluations/mine", methods=["GET"])
@check_auth
def process_quality_mine():
    if not _can_read(g.current_user):
        return jsonify({"error": "无权限"}), 403
    try:
        page, per_page = _quality_pagination()
        return jsonify(ProcessQualityEvaluationService.my_evaluations(
            g.current_user,
            year_month=request.args.get("year_month", ""),
            page=page,
            per_page=per_page,
        ))
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400


@app.route("/api/process-quality-evaluations/<int:evaluation_id>/review", methods=["PUT"])
@check_auth
@check_permission("process_quality_evaluation:review")
def process_quality_review(evaluation_id):
    try:
        result = ProcessQualityEvaluationService.review(evaluation_id, request.get_json() or {}, g.current_user)
        safe_audit_log("process_quality_evaluation_review", "process_quality_evaluation", evaluation_id, result["status"])
        return jsonify(result)
    except DomainError as exc:
        return jsonify(exc.to_payload()), exc.status_code
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
        payload = request.get_json(silent=True)
        result = ProcessQualityEvaluationService.save_rules({} if payload is None else payload)
        safe_audit_log("process_quality_evaluation_rules", "system_setting", 0, "updated")
        return jsonify(result)
    except DomainError as exc:
        return jsonify(exc.to_payload()), exc.status_code
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
        payload = request.get_json(silent=True)
        result = ProcessQualityEvaluationService.save_template(
            {} if payload is None else payload, g.current_user
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
        payload = request.get_json(silent=True)
        result = ProcessQualityEvaluationService.save_template(
            {} if payload is None else payload, g.current_user, template_id
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
    except DomainError as exc:
        return jsonify(exc.to_payload()), exc.status_code
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
    try:
        page, per_page = _quality_pagination()
        return jsonify(ProcessQualityEvaluationService.list_appeals(
            request.args.get("status", ""), g.current_user, mine=mine,
            year_month=request.args.get("year_month", ""),
            page=page,
            per_page=per_page,
        ))
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400


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
    except DomainError as exc:
        return jsonify(exc.to_payload()), exc.status_code
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400
