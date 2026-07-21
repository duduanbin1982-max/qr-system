# P3-14: Department/Team Hierarchy Management
from flask import request, jsonify
from modules.route_decorators import app, check_auth, check_permission, safe_audit_log
from modules.services.department_service import DepartmentService


@app.route("/api/departments", methods=["GET"])
@check_auth
def list_departments():
    return jsonify(DepartmentService.list_departments())


@app.route("/api/departments", methods=["POST"])
@check_auth
@check_permission("users:edit")
def create_department():
    data = request.get_json() or {}
    name = DepartmentService.create_department(data)
    safe_audit_log("create_department", "department", 0, "Created: " + name)
    return jsonify({"message": "ok"}), 201


@app.route("/api/departments/<int:dep_id>", methods=["PUT"])
@check_auth
@check_permission("users:edit")
def update_department(dep_id):
    data = request.get_json() or {}
    DepartmentService.update_department(dep_id, data)
    return jsonify({"message": "ok"})


@app.route("/api/departments/<int:dep_id>", methods=["DELETE"])
@check_auth
@check_permission("users:edit")
def delete_department(dep_id):
    try:
        DepartmentService.delete_department(dep_id)
    except LookupError as exc:
        return jsonify({"error": str(exc)}), 404
    safe_audit_log("delete_department", "department", dep_id)
    return jsonify({"message": "ok"})
