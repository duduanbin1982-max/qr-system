"""Process handoff quality review routes."""
from flask import jsonify, request, g

from modules.route_decorators import app, check_auth, check_permission, safe_audit_log
from modules.services.handoff_review_service import HandoffReviewService


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
    return _legacy_response(HandoffReviewService.list_reviews(
        year_month=request.args.get('year_month', ''),
        status=request.args.get('status', ''),
        user_id=request.args.get('user_id', type=int),
        page=request.args.get('page', 1, type=int),
        per_page=request.args.get('per_page', 100, type=int),
    ))


@app.route('/api/handoff-reviews/<int:review_id>/status', methods=['PUT'])
@check_auth
@check_permission('performance:edit')
def handoff_review_status(review_id):
    try:
        result = HandoffReviewService.update_status(review_id, request.get_json() or {}, g.current_user)
        safe_audit_log('handoff_review_status', 'handoff_review', review_id, result.get('status', ''))
        return _legacy_response(result)
    except ValueError as e:
        return _legacy_response({'error': str(e)}, 400)
