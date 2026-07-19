"""Performance evaluation routes."""
from flask import jsonify, request, g
from modules.route_decorators import app, check_auth, check_permission, handle_unexpected_error, safe_audit_log
from modules.services.performance_service import PerformanceService


@app.route('/api/performance/overview', methods=['GET'])
@check_auth
@check_permission('performance:view')
def performance_overview():
    try:
        return jsonify(PerformanceService.overview(request.args.get('year_month', '')))
    except Exception as e:
        return handle_unexpected_error(e, 'database operation')


@app.route('/api/performance/scores', methods=['GET'])
@check_auth
@check_permission('performance:view')
def performance_scores():
    try:
        result = PerformanceService.list_scores(
            year_month=request.args.get('year_month', ''),
            warning_level=request.args.get('warning_level', ''),
            search=request.args.get('search', ''),
            position_id=request.args.get('position_id', ''),
            page=request.args.get('page', 1, type=int),
            per_page=request.args.get('per_page', 50, type=int),
        )
        return jsonify(result)
    except Exception as e:
        return handle_unexpected_error(e, 'database operation')


@app.route('/api/performance/rules', methods=['GET'])
@check_auth
@check_permission('performance:view')
def performance_rules():
    try:
        return jsonify(PerformanceService.rules())
    except Exception as e:
        return handle_unexpected_error(e, 'database operation')


@app.route('/api/performance/generate', methods=['POST'])
@check_auth
@check_permission('performance:create')
def performance_generate():
    try:
        data = request.get_json() or {}
        result = PerformanceService.generate_month(data.get('year_month') or request.args.get('year_month', ''))
        safe_audit_log('performance_generate', 'performance', 0, result.get('year_month', ''))
        return jsonify(result)
    except Exception as e:
        return handle_unexpected_error(e, 'database operation')


@app.route('/api/performance/reviews', methods=['POST'])
@check_auth
@check_permission('performance:edit')
def performance_review_save():
    try:
        user = g.current_user if hasattr(g, 'current_user') else {}
        result = PerformanceService.save_review(request.get_json() or {}, user.get('id'))
        safe_audit_log('performance_review_save', 'performance_review', 0, result.get('year_month', ''))
        return jsonify(result)
    except ValueError as e:
        return jsonify({'error': str(e)}), 400
    except Exception as e:
        return handle_unexpected_error(e, 'database operation')


@app.route('/api/performance/plans', methods=['GET'])
@check_auth
@check_permission('performance:view')
def performance_plans():
    try:
        plans = PerformanceService.list_plans(
            year_month=request.args.get('year_month', ''),
            status=request.args.get('status', ''),
            user_id=request.args.get('user_id', type=int),
        )
        return jsonify({'plans': plans})
    except Exception as e:
        return handle_unexpected_error(e, 'database operation')


@app.route('/api/performance/plans', methods=['POST'])
@check_auth
@check_permission('performance:create')
def performance_plan_create():
    try:
        user = g.current_user if hasattr(g, 'current_user') else {}
        plan_id = PerformanceService.create_plan(request.get_json() or {}, user.get('id'))
        safe_audit_log('performance_plan_create', 'performance_plan', plan_id, '')
        return jsonify({'ok': True, 'id': plan_id})
    except ValueError as e:
        return jsonify({'error': str(e)}), 400
    except Exception as e:
        return handle_unexpected_error(e, 'database operation')


@app.route('/api/performance/plans/<int:plan_id>', methods=['PUT'])
@check_auth
@check_permission('performance:edit')
def performance_plan_update(plan_id):
    try:
        result = PerformanceService.update_plan(plan_id, request.get_json() or {})
        safe_audit_log('performance_plan_update', 'performance_plan', plan_id, '')
        return jsonify(result)
    except Exception as e:
        return handle_unexpected_error(e, 'database operation')
