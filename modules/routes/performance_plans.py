"""Evidence-backed performance improvement plan API."""

from flask import g, jsonify, request

from modules.domain.errors import DomainError, LegacyLedgerReadOnlyError
from modules.route_decorators import app, check_auth, safe_audit_log
from modules.services.performance_improvement_service import (
    PerformanceImprovementService,
)


def _actor():
    return getattr(g, "current_user", {}) or {}


def _error(exc):
    if isinstance(exc, PermissionError):
        return jsonify({"error": str(exc), "code": "forbidden"}), 403
    if isinstance(exc, DomainError):
        return jsonify(exc.to_payload()), exc.status_code
    return jsonify({"error": str(exc), "code": "validation_error"}), 400


@app.route("/api/performance/plans", methods=["GET"])
@check_auth
def list_performance_improvement_plans():
    try:
        return jsonify(
            PerformanceImprovementService.list_plans(
                {
                    "production_month": request.args.get("production_month", ""),
                    "status": request.args.get("status", ""),
                    "user_id": request.args.get("user_id", type=int),
                },
                _actor(),
            )
        )
    except (ValueError, PermissionError) as exc:
        return _error(exc)


@app.route("/api/performance/plans", methods=["POST"])
@check_auth
def create_performance_improvement_plan():
    try:
        result = PerformanceImprovementService.create_plan(
            request.get_json(silent=True) or {}, _actor()
        )
        safe_audit_log(
            "performance_plan_v2_create",
            "performance_improvement_plan_v2",
            result["plan_id"],
            result["status"],
        )
        return jsonify(result), 201
    except (ValueError, PermissionError) as exc:
        return _error(exc)


@app.route("/api/performance/plans/<int:plan_id>", methods=["GET"])
@check_auth
def get_performance_improvement_plan(plan_id):
    try:
        return jsonify(PerformanceImprovementService.get_plan(plan_id, _actor()))
    except (ValueError, PermissionError) as exc:
        return _error(exc)


@app.route("/api/performance/plans/<int:plan_id>/transitions", methods=["POST"])
@check_auth
def transition_performance_improvement_plan(plan_id):
    try:
        result = PerformanceImprovementService.transition(
            plan_id, request.get_json(silent=True) or {}, _actor()
        )
        safe_audit_log(
            "performance_plan_v2_transition",
            "performance_improvement_plan_v2",
            plan_id,
            result["status"],
        )
        return jsonify(result)
    except (ValueError, PermissionError) as exc:
        return _error(exc)


@app.route("/api/performance/plans/<int:plan_id>/evidence", methods=["POST"])
@check_auth
def add_performance_improvement_evidence(plan_id):
    try:
        result = PerformanceImprovementService.add_evidence(
            plan_id, request.get_json(silent=True) or {}, _actor()
        )
        safe_audit_log(
            "performance_plan_v2_evidence_add",
            "performance_improvement_plan_v2",
            plan_id,
            str(result["evidence_id"]),
        )
        return jsonify(result), 201
    except (ValueError, PermissionError) as exc:
        return _error(exc)


@app.route("/api/performance/plans/<int:plan_id>/reassessments", methods=["POST"])
@check_auth
def reassess_performance_improvement_plan(plan_id):
    try:
        result = PerformanceImprovementService.reassess(
            plan_id, request.get_json(silent=True) or {}, _actor()
        )
        safe_audit_log(
            "performance_plan_v2_reassess",
            "performance_improvement_plan_v2",
            plan_id,
            result["status"],
        )
        return jsonify(result), 201
    except (ValueError, PermissionError) as exc:
        return _error(exc)


@app.route("/api/performance/plans/<int:plan_id>", methods=["PUT"])
@check_auth
def reject_legacy_performance_plan_update(plan_id):
    del plan_id
    exc = LegacyLedgerReadOnlyError("旧绩效改进计划覆盖式写接口已停用")
    return jsonify(exc.to_payload()), exc.status_code
