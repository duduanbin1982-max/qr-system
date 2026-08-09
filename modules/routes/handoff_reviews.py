"""Process handoff quality review routes."""
from flask import jsonify, request, g

from modules.domain.errors import DomainError
from modules.route_decorators import app, check_auth, check_permission, safe_audit_log
from modules.services.handoff_review_service import HandoffReviewService


def _legacy_pagination(default=100, maximum=500):
    raw_page = request.args.get('page')
    raw_per_page = request.args.get('per_page')
    try:
        page = int(raw_page) if raw_page is not None else 1
        per_page = int(raw_per_page) if raw_per_page is not None else default
    except (TypeError, ValueError) as exc:
        raise ValueError('分页参数必须是整数') from exc
    if page < 1:
        raise ValueError('页码必须大于等于1')
    if per_page < 1 or per_page > maximum:
        raise ValueError(f'每页数量必须在1到{maximum}之间')
    return page, per_page


def _legacy_response(payload, status=200):
    response = jsonify(payload)
    response.headers['Deprecation'] = 'true'
    response.headers['Link'] = '</api/process-quality-evaluations>; rel="successor-version"'
    return response, status


@app.route('/api/handoff-reviews/pending', methods=['GET'])
@check_auth
@check_permission('scan:view')
def handoff_review_pending():
    context = HandoffReviewService.pending_context(
        request.args.get('order_id', type=int),
        request.args.get('to_process_id', request.args.get('process_id', type=int), type=int),
        g.current_user.get('id'),
        request.args.get('serial_no', '').strip(),
    )
    return _legacy_response(context)


@app.route('/api/handoff-reviews', methods=['POST'])
@check_auth
@check_permission('scan:report')
def handoff_review_create():
    try:
        result = HandoffReviewService.create_review(request.get_json() or {}, g.current_user)
        safe_audit_log('handoff_review_create', 'handoff_review', result.get('id', 0), result.get('status', ''))
        return _legacy_response(result)
    except ValueError as e:
        return _legacy_response({'error': str(e)}, 400)


@app.route('/api/handoff-reviews', methods=['GET'])
@check_auth
@check_permission('performance:view')
def handoff_review_list():
    try:
        page, per_page = _legacy_pagination()
        return _legacy_response(HandoffReviewService.list_reviews(
            year_month=request.args.get('year_month', ''),
            status=request.args.get('status', ''),
            user_id=request.args.get('user_id', type=int),
            page=page,
            per_page=per_page,
        ))
    except ValueError as exc:
        return _legacy_response({'error': str(exc)}, 400)


@app.route('/api/handoff-reviews/<int:review_id>/status', methods=['PUT'])
@check_auth
@check_permission('process_quality_evaluation:review')
def handoff_review_status(review_id):
    try:
        result = HandoffReviewService.update_status(review_id, request.get_json() or {}, g.current_user)
        safe_audit_log('handoff_review_status', 'handoff_review', review_id, result.get('status', ''))
        return _legacy_response(result)
    except DomainError as e:
        return _legacy_response(e.to_payload(), e.status_code)
    except ValueError as e:
        return _legacy_response({'error': str(e)}, 400)
