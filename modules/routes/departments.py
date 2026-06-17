# P3-14: Department/Team Hierarchy Management
from flask import request, jsonify
from modules.app import app
from modules.middleware.audit import audit_log
from modules.middleware.auth import check_auth, check_permission
from modules.db import get_db

SQL_LIST = """SELECT id, name, description, parent_id, sort_order, status, created_at
FROM departments WHERE status='active' ORDER BY sort_order"""


@app.route("/api/departments", methods=["GET"])
@check_auth
def list_departments():
    db = get_db()
    rows = db.execute(SQL_LIST).fetchall()
    deps = [dict(r) for r in rows]
    tree = []
    dep_map = {d["id"]: d for d in deps}
    for d in deps:
        d.setdefault("children", [])
    for d in deps:
        pid = d.get("parent_id")
        if pid and pid in dep_map:
            dep_map[pid].setdefault("children", []).append(d)
        else:
            tree.append(d)
    return jsonify({"departments": tree, "flat": deps})


@app.route("/api/departments", methods=["POST"])
@check_auth
@check_permission("users:edit")
def create_department():
    data = request.get_json() or {}
    name = (data.get("name") or "").strip()
    if not name:
        return jsonify({"error": "Department name required"}), 400
    db = get_db()
    existing = db.execute("SELECT id FROM departments WHERE name = ?", (name,)).fetchone()
    if existing:
        return jsonify({"error": "Department name already exists"}), 409
    db.execute(
        """INSERT INTO departments (name, description, parent_id, sort_order) VALUES (?,?,?,?)""",
        (name, data.get("description", ""), data.get("parent_id"), data.get("sort_order", 0))
    )
    db.commit()
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
    db = get_db()
    dep = db.execute("SELECT id FROM departments WHERE id = ?", (dep_id,)).fetchone()
    if not dep:
        return jsonify({"error": "Not found"}), 404
    sets = []  # whitelist
    params = []
    for f in ["name", "description", "parent_id", "sort_order", "status"]:
        if f in data:
            sets.append(f + " = ?")
            params.append(data[f])
    if not sets:
        return jsonify({"error": "No fields"}), 400
    params.append(dep_id)
    sql = "UPDATE departments SET " + ", ".join(sets) + " WHERE id = ?"
    db.execute(sql, params)
    db.commit()
    return jsonify({"message": "ok"})


@app.route("/api/departments/<int:dep_id>", methods=["DELETE"])
@check_auth
@check_permission("users:edit")
def delete_department(dep_id):
    db = get_db()
    dep = db.execute("""SELECT id FROM departments WHERE id = ? AND status='active'""", (dep_id,)).fetchone()
    if not dep:
        return jsonify({"error": "Not found"}), 404
    db.execute("""UPDATE departments SET status = 'inactive' WHERE id = ?""", (dep_id,))
    db.commit()
    try:
        audit_log("delete_department", "department", dep_id)
    except Exception:
        pass
    return jsonify({"message": "ok"})
