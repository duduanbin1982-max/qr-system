"""
qr-system — 用户管理

薄层：HTTP 解析 → 调用 UserService → 格式化响应。
"""
from flask import request, jsonify, g, send_file

from modules.app import app
from modules.services.setting_service import SettingsService
from modules.middleware.audit import audit_log
from modules.middleware.auth import check_auth, check_permission
from modules.middleware.validate import validate_json
import os
from modules.middleware.helpers import get_json_body
from modules.services.user_service import UserService



@app.route('/api/users', methods=['GET'])
@check_auth
@check_permission('users:view')
def list_users():
    page = max(request.args.get('page', 1, type=int), 1)
    limit_raw = request.args.get('limit', SettingsService.get_value('page_size', '20'), type=int)
    limit = min(max(int(limit_raw or 20), 1), 200)
    role_filter = request.args.get('role', '').strip()
    role_not = request.args.get('not_role', '').strip()
    keyword = request.args.get('keyword', '').strip()
    status = request.args.get('status', '').strip()
    return jsonify(UserService.list_users(page, limit, role_filter, role_not, keyword, status))


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
    data = UserService.list_users(1, 9999, role_filter=role_filter, keyword=keyword, status=status)
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
    try:
        return jsonify(UserService.get_user_detail(uid))
    except ValueError as e:
        return jsonify({'error': str(e)}), 404

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
    return jsonify(UserService.list_user_documents(uid))

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
    try:
        result = UserService.upload_user_document(
            uid, file, request.form.get("doc_type", ""), g.current_user.get("id"), UPLOAD_DIR
        )
    except LookupError as e:
        return jsonify({"error": str(e)}), 404
    try:
        audit_log("upload_document", "user", uid, f"Uploaded: {result['filename']}")
    except Exception:
        pass
    return jsonify({"message": "Upload success", "filename": result["filename"], "size": result["size"]})

@app.route("/api/users/<int:uid>/documents/<int:doc_id>", methods=["GET"])
@check_auth
@check_permission("users:view")
def download_user_document(uid, doc_id):
    """Download a document"""
    try:
        doc, filepath = UserService.get_user_document_file(uid, doc_id, UPLOAD_DIR)
    except LookupError as e:
        return jsonify({"error": str(e)}), 404
    except FileNotFoundError as e:
        return jsonify({"error": str(e)}), 404
    return send_file(filepath, as_attachment=True, download_name=doc["doc_name"])

@app.route("/api/users/<int:uid>/documents/<int:doc_id>", methods=["DELETE"])
@check_auth
@check_permission("users:edit")
def delete_user_document(uid, doc_id):
    """Delete a document"""
    try:
        doc = UserService.delete_user_document(uid, doc_id, UPLOAD_DIR)
    except LookupError as e:
        return jsonify({"error": str(e)}), 404
    try:
        audit_log("delete_document", "user", uid, f"Deleted: {doc['doc_name']}")
    except Exception:
        pass
    return jsonify({"message": "Document deleted"})
