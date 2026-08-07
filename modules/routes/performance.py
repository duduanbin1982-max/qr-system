"""Performance evaluation routes."""
from flask import jsonify, request, g
from modules.domain.errors import LegacyLedgerReadOnlyError
from modules.route_decorators import app, check_auth
from modules.services.performance_authorization_service import (
    PerformanceAuthorizationService,
)
from modules.services.performance_service import PerformanceService


def _actor():
    return getattr(g, "current_user", {}) or {}


def _forbidden(exc):
    return jsonify({"error": str(exc), "code": "forbidden"}), 403


@app.route('/api/performance/overview', methods=['GET'])
@check_auth
def performance_overview():
    try:
        return jsonify(
            PerformanceService.overview(
                request.args.get('year_month', ''), actor=_actor()
            )
        )
    except PermissionError as exc:
        return _forbidden(exc)


@app.route('/api/performance/scores', methods=['GET'])
@check_auth
def performance_scores():
    try:
        result = PerformanceService.list_scores(
            year_month=request.args.get('year_month', ''),
            warning_level=request.args.get('warning_level', ''),
            search=request.args.get('search', ''),
            position_id=request.args.get('position_id', ''),
            user_id=request.args.get('user_id'),
            department_id=request.args.get('department_id'),
            page=request.args.get('page', 1),
            per_page=request.args.get('per_page', 50),
            actor=_actor(),
        )
        return jsonify(result)
    except PermissionError as exc:
        return _forbidden(exc)


@app.route('/api/performance/rules', methods=['GET'])
@check_auth
def performance_rules():
    try:
        PerformanceAuthorizationService.require_view_access(_actor())
        return jsonify(PerformanceService.rules())
    except PermissionError as exc:
        return _forbidden(exc)


@app.route('/api/performance/generate', methods=['POST'])
@check_auth
def performance_generate():
    raise LegacyLedgerReadOnlyError(
        "Legacy 绩效台账只读，请使用版本化批次接口"
    )


@app.route('/api/performance/reviews', methods=['POST'])
@check_auth
def performance_review_save():
    raise LegacyLedgerReadOnlyError(
        "Legacy 绩效复核只读，请使用版本化主管复核接口"
    )
