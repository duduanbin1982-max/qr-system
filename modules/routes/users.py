"""
qr-system — 用户管理

薄层：HTTP 解析 → 调用 UserService → 格式化响应。
"""
from flask import request, jsonify, g, send_file

from modules.app import app
from modules.db import get_setting, get_db
from modules.middleware.auth import check_auth, check_permission, audit_log
from modules.middleware.validate import validate_json
import os
import uuid
from flask import send_file
from modules.middleware.helpers import get_json_body
from modules.services.user_service import UserService



@app.route('/api/users', methods=['GET'])
@check_auth
@check_permission('users:view')
def list_users():
    page = max(request.args.get('page', 1, type=int), 1)
    limit_raw = request.args.get('limit', get_setting('page_size', '20'), type=int)
    limit = min(max(int(limit_raw or 20), 1), 200)
    role_filter = request.args.get('role', '').strip()
    keyword = request.args.get('keyword', '').strip()
    status = request.args.get('status', '').strip()
    return jsonify(UserService.list_users(page, limit, role_filter, keyword, status))


@app.route('/api/users', methods=['POST'])
@check_auth
@check_permission('users:create')
@validate_json('create_user')
def create_user():
    data = get_json_body()
    try:
        # P1-2: Pass caller for admin-creation permission check
        data['_caller_user_id'] = g.current_user.get('id') if hasattr(g, 'current_user') else None
        uid, password = UserService.create_user(data)
    except ValueError as e:
        code = 409 if '已存在' in str(e) else 400
        return jsonify({'error': str(e)}), code
    try:
        audit_log('create_user', 'user', uid, f'{data.get("username")}/{data.get("name")}')
    except Exception:
        pass
    return jsonify({'message': '添加成功', 'id': uid, 'password': password if password else ''})


@app.route('/api/users/<int:uid>', methods=['PUT'])
@check_auth
@check_permission('users:edit')
@validate_json('update_user')
def update_user(uid):
    data = get_json_body()
    try:
        UserService.update_user(uid, data, g.current_user.get("id"))
    except ValueError as e:
        return jsonify({'error': str(e)}), 404 if '不存在' in str(e) else 400
    # Log update without password (but note if password was changed)
    audit_data = dict(data)
    has_pwd = bool(audit_data.get('password'))
    audit_data.pop('password', None)
    if has_pwd:
        audit_data['password_changed'] = True
    try:
        audit_log('update_user', 'user', uid, str(audit_data))
    except Exception:
        pass
    return jsonify({'message': '更新成功'})

# P0-1: Soft-delete restore + permanent delete
@app.route('/api/users/<int:uid>/restore', methods=['POST'])
@check_auth
@check_permission('users:delete')
def user_restore_api(uid):
    try:
        UserService.restore_user(uid)
    except ValueError as e:
        return jsonify({'error': str(e)}), 400
    try:
        audit_log('restore_user', 'user', uid)
    except Exception:
        pass
    return jsonify({'message': 'user restored'})

@app.route('/api/users/<int:uid>/permanent', methods=['DELETE'])
@check_auth
@check_permission('users:admin')
def user_permanent_delete_api(uid):
    try:
        UserService.permanent_delete_user(uid)
    except ValueError as e:
        return jsonify({'error': str(e)}), 400
    try:
        audit_log('permanent_delete_user', 'user', uid)
    except Exception:
        pass
    return jsonify({'message': 'user permanently deleted'})


@app.route('/api/users/<int:uid>', methods=['DELETE'])
@check_auth
@check_permission('users:delete')
def delete_user(uid):
    try:
        UserService.delete_user(uid, g.current_user.get('id'))
    except ValueError as e:
        return jsonify({'error': str(e)}), 400
    try:
        audit_log('delete_user', 'user', uid)
    except Exception:
        pass
    return jsonify({'message': '删除成功'})


@app.route('/api/users/<int:uid>/reset-password', methods=['POST'])
@check_auth
@check_permission('users:admin')
def reset_password(uid):
    data = get_json_body()
    try:
        new_pw = UserService.reset_password(uid, data.get('password'))
    except ValueError as e:
        return jsonify({'error': str(e)}), 404
    try:
        audit_log('reset_password', 'user', uid)
    except Exception:
        pass
    return jsonify({'message': '密码已重置'})


@app.route('/api/users/<int:uid>/unlock', methods=['POST'])
@check_auth
@check_permission('users:admin')
def unlock_user(uid):
    try:
        UserService.unlock_user(uid)
    except ValueError as e:
        return jsonify({'error': str(e)}), 404
    try:
        audit_log('unlock_user', 'user', uid)
    except Exception:
        pass
    return jsonify({'message': '账户已解锁'})

@app.route('/api/users/batch-delete', methods=['POST'])
@check_auth
@check_permission('users:delete')
def batch_delete_users():
    """Delete multiple users in a single transaction."""
    data = get_json_body()
    ids = data.get('ids', [])
    if not ids or not isinstance(ids, list):
        return jsonify({'error': '无效的用户ID列表'}), 400
    try:
        deleted = UserService.batch_delete_users(ids, g.current_user.get('id'))
    except ValueError as e:
        return jsonify({'error': str(e)}), 400
    try:
        audit_log('batch_delete_users', 'user', 0, f'deleted {deleted} users: {ids[:10]}')
    except Exception:
        pass
    return jsonify({'message': f'成功删除 {deleted} 个用户', 'deleted': deleted})


# Phase 2: Excel import/export + detail
@app.route('/api/users/import', methods=['POST'])
@check_auth
@check_permission('users:create')
def import_users():
    import tempfile, os as _os
    if 'file' not in request.files:
        return jsonify({'error': '???Excel??'}), 400
    file = request.files['file']
    if not file.filename or not file.filename.lower().endswith('.xlsx'):
        return jsonify({'error': '???.xlsx??'}), 400
    tmp = tempfile.NamedTemporaryFile(delete=False, suffix='.xlsx')
    try:
        file.save(tmp.name)
        tmp.close()
        result = UserService.import_users(tmp.name)
    except ValueError as e:
        return jsonify({'error': str(e)}), 400
    finally:
        if _os.path.exists(tmp.name):
            _os.unlink(tmp.name)
    try:
        audit_log('import_users', 'user', 0, f'imported {result.get("success",0)} users')
    except Exception:
        pass
    return jsonify(result)

@app.route('/api/users/export', methods=['GET'])
@check_auth
@check_permission('users:view')
def export_users():
    import openpyxl, io
    role_filter = request.args.get('role', '').strip()
    keyword = request.args.get('keyword', '').strip()
    status = request.args.get('status', '').strip()
    data = UserService.list_users(1, 9999, role_filter, keyword, status)
    users = data.get('users', [])
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = 'Users'
    ws.append(['???', '??', '??', '???', '??', '??', '??', '??'])
    for u in users:
        ws.append([u.get('username',''), u.get('name',''), u.get('employee_no',''),
                   u.get('phone',''), u.get('email',''), u.get('position_name',''),
                   '???' if u.get('role')=='admin' else '??',
                   '??' if u.get('status')=='active' else '???' if u.get('status')=='deleted' else '??'])
    output = io.BytesIO()
    wb.save(output)
    output.seek(0)
    return send_file(output,
        mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
        as_attachment=True, download_name='users_export.xlsx')

@app.route('/api/users/<int:uid>/detail', methods=['GET'])
@check_auth
@check_permission('users:view')
def user_detail(uid):
    user = UserService.get_user(uid)
    if not user:
        return jsonify({'error': '?????'}), 404
    import sqlite3; db=sqlite3.connect("/home/dubin/qr-system/data/production.db"); db.row_factory=sqlite3.Row
    # Get role names
    roles = db.execute(
        'SELECT r.name FROM user_roles ur JOIN roles r ON ur.role_id=r.id WHERE ur.user_id=?',
        (uid,)
    ).fetchall()
    user['role_names'] = [r['name'] for r in roles]
    # Get assigned processes
    procs = db.execute(
        'SELECT p.id, p.name FROM user_processes up JOIN processes p ON up.process_id=p.id WHERE up.user_id=?',
        (uid,)
    ).fetchall()
    user['assigned_processes'] = [dict(p) for p in procs]
    # Get work stats
    stats = db.execute(
        'SELECT COUNT(*) as total_records, SUM(quantity) as total_quantity FROM work_records WHERE user_id=? AND status="approved"',
        (uid,)
    ).fetchone()
    user['work_stats'] = dict(stats) if stats else {}
    return jsonify(user)

@app.route('/api/users/batch-status', methods=['POST'])
@check_auth
@check_permission('users:edit')
def batch_update_status():
    data = get_json_body()
    ids = data.get('ids', [])
    status = data.get('status', '')
    try:
        count = UserService.batch_update_status(ids, status, g.current_user.get('id'))
    except ValueError as e:
        return jsonify({'error': str(e)}), 400
    try:
        audit_log('batch_update_status', 'user', 0, f'updated {count} users to {status}')
    except Exception:
        pass
    return jsonify({'message': f'updated {count} users', 'updated': count})



# ============================================================
# P3-13: Employee Document Attachments
# ============================================================

UPLOAD_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "uploads", "employee_docs")

@app.route("/api/users/<int:uid>/documents", methods=["GET"])
@check_auth
@check_permission("users:view")
def list_user_documents(uid):
    """List all documents for a user"""
    db = get_db()
    docs = db.execute(
        "SELECT id, user_id, doc_name, doc_type, file_size, uploaded_by, created_at FROM employee_documents WHERE user_id = ? ORDER BY created_at DESC",
        (uid,)
    ).fetchall()
    return jsonify([dict(d) for d in docs])

@app.route("/api/users/<int:uid>/documents", methods=["POST"])
@check_auth
@check_permission("users:edit")
def upload_user_document(uid):
    """Upload a document for a user"""
    if "file" not in request.files:
        return jsonify({"error": "No file provided"}), 400
    file = request.files["file"]
    if file.filename == "":
        return jsonify({"error": "No file selected"}), 400
    db = get_db()
    # Check user exists
    user = db.execute("SELECT id FROM users WHERE id = ?", (uid,)).fetchone()
    if not user:
        return jsonify({"error": "User not found"}), 404
    os.makedirs(UPLOAD_DIR, exist_ok=True)
    ext = file.filename.rsplit(".", 1)[-1].lower() if "." in file.filename else ""
    safe_name = f"{uid}_{uuid.uuid4().hex}"
    if ext:
        safe_name += f".{ext}"
    filepath = os.path.join(UPLOAD_DIR, safe_name)
    file.save(filepath)
    file_size = os.path.getsize(filepath)
    doc_type = request.form.get("doc_type", "")
    db.execute(
        "INSERT INTO employee_documents (user_id, doc_name, doc_type, file_path, file_size, uploaded_by) VALUES (?,?,?,?,?,?)",
        (uid, file.filename, doc_type, safe_name, file_size, g.current_user.get("id"))
    )
    db.commit()
    try:
        audit_log("upload_document", "user", uid, f"Uploaded: {file.filename}")
    except Exception:
        pass
    return jsonify({"message": "Upload success", "filename": file.filename, "size": file_size})

@app.route("/api/users/<int:uid>/documents/<int:doc_id>", methods=["GET"])
@check_auth
@check_permission("users:view")
def download_user_document(uid, doc_id):
    """Download a document"""
    db = get_db()
    doc = db.execute(
        "SELECT * FROM employee_documents WHERE id = ? AND user_id = ?",
        (doc_id, uid)
    ).fetchone()
    if not doc:
        return jsonify({"error": "Document not found"}), 404
    filepath = os.path.join(UPLOAD_DIR, doc["file_path"])
    if not os.path.exists(filepath):
        return jsonify({"error": "File not found on disk"}), 404
    return send_file(filepath, as_attachment=True, download_name=doc["doc_name"])

@app.route("/api/users/<int:uid>/documents/<int:doc_id>", methods=["DELETE"])
@check_auth
@check_permission("users:edit")
def delete_user_document(uid, doc_id):
    """Delete a document"""
    db = get_db()
    doc = db.execute(
        "SELECT * FROM employee_documents WHERE id = ? AND user_id = ?",
        (doc_id, uid)
    ).fetchone()
    if not doc:
        return jsonify({"error": "Document not found"}), 404
    filepath = os.path.join(UPLOAD_DIR, doc["file_path"])
    if os.path.exists(filepath):
        os.remove(filepath)
    db.execute("DELETE FROM employee_documents WHERE id = ?", (doc_id,))
    db.commit()
    try:
        audit_log("delete_document", "user", uid, f"Deleted: {doc['doc_name']}")
    except Exception:
        pass
    return jsonify({"message": "Document deleted"})
