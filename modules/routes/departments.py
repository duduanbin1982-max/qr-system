# P3-14: Department/Team Hierarchy Management
from flask import request, jsonify
from modules.app import app
from modules.middleware.audit import audit_log
from modules.middleware.auth import check_auth, check_permission
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
    try:
        name = DepartmentService.create_department(data)
    except ValueError as exc:
        status = 409 if "already exists" in str(exc) else 400
        return jsonify({"error": str(exc)}), status
    try:
        audit_log("create_department", "department", 0, "Created: " + name)
    except Exception:
        pass
    return jsonify({"message": "ok"}), 201


@app.route("/api/departments/<int:dep_id>", methods=["PUT"])
@check_auth
@check_permission("users:edit")
def update_department(dep_id):
    data = request.get_json() or {}
    try:
        DepartmentService.update_department(dep_id, data)
    except LookupError as exc:
        return jsonify({"error": str(exc)}), 404
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400
    return jsonify({"message": "ok"})


@app.route("/api/departments/<int:dep_id>", methods=["DELETE"])
@check_auth
@check_permission("users:edit")
def delete_department(dep_id):
    try:
        DepartmentService.delete_department(dep_id)
    except LookupError as exc:
        return jsonify({"error": str(exc)}), 404
    try:
        audit_log("delete_department", "department", dep_id)
    except Exception:
        pass
    return jsonify({"message": "ok"})
