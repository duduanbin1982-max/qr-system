"""Administrative API for explicit performance department scopes."""

from flask import g, jsonify, request

from modules.route_decorators import app, check_auth, check_permission
from modules.services.performance_authorization_service import (
    PerformanceAuthorizationService,
)


@app.route(
    "/api/performance/department-scopes/<int:user_id>", methods=["GET"]
)
@check_auth
@check_permission("users:admin")
def get_performance_department_scopes(user_id):
    return jsonify(
        PerformanceAuthorizationService.get_department_scopes(
            user_id, g.current_user
        )
    )


@app.route(
    "/api/performance/department-scopes/<int:user_id>", methods=["PUT"]
)
@check_auth
@check_permission("users:admin")
def replace_performance_department_scopes(user_id):
    data = request.get_json(silent=True) or {}
    return jsonify(
        PerformanceAuthorizationService.replace_department_scopes(
            user_id, data.get("department_ids"), g.current_user
        )
    )
