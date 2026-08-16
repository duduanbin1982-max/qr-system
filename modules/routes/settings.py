"""
qr-system — 系统设置

注：Swagger docstring 仅供文档参考。
"""
from flask import g, request, jsonify

from modules.route_decorators import (
    app,
    check_auth,
    check_permission,
    get_json_body,
    safe_audit_log,
)
from modules.services.company_profile_service import CompanyProfileService
from modules.services.setting_service import SettingsService

@app.route('/api/settings/public', methods=['GET'])
def get_public_settings():
    """
    公开端点：获取公司名称等非敏感设置（无需登录）
    ---
    tags:
      - Settings
    summary: 公开端点：获取公司名称等非敏感设置（无需登录）
    responses:
      200:
        description: OK
    security:
      - Bearer: []
    """
    return jsonify({
        **CompanyProfileService.get_public_profile(),
    })


@app.route('/api/settings/allowed-keys', methods=['GET'])
@check_auth
@check_permission('settings:manage')
def allowed_keys():
    """Return the list of allowed setting keys (single source of truth)."""
    return jsonify({'allowed_keys': SettingsService.get_allowed_keys()})

@app.route('/api/settings', methods=['GET'])
@check_auth
@check_permission('settings:manage')
def get_settings():
    return jsonify({'settings': SettingsService.get_all()})

@app.route('/api/settings', methods=['POST'])
@check_auth
@check_permission('settings:manage')
def save_settings():
    data = get_json_body()
    if not data:
        return jsonify({'error': '提交数据为空'}), 400

    deleted_keys = data.pop('_deleted_keys', [])
    if not isinstance(deleted_keys, list):
        deleted_keys = []

    try:
        SettingsService.save(data, deleted_keys)
    except ValueError as e:
        return jsonify({'error': str(e)}), 400

    try:
        SettingsService.clear_cache()
    except Exception:
        pass

    parts = [f'{k}={str(v)[:80]}' for k, v in data.items()]
    if deleted_keys:
        parts.append(f'_deleted={",".join(deleted_keys[:20])}')
    safe_audit_log('save_settings', detail=', '.join(parts)[:1900])
    return jsonify({'message': '保存成功'})


@app.route('/api/settings/company-info', methods=['GET'])
@check_auth
@check_permission('company_info:view')
def get_company_info():
    return jsonify({'profile': CompanyProfileService.get_profile()})


@app.route('/api/settings/company-info/history', methods=['GET'])
@check_auth
@check_permission('company_info:view')
def get_company_info_history():
    from modules.route_decorators import has_permission

    return jsonify(CompanyProfileService.list_revisions(
        allow_sensitive_history=has_permission(
            g.current_user, 'company_info:audit_history'
        ),
        limit=request.args.get('limit', 100),
    ))


@app.route('/api/settings/company-info', methods=['PUT', 'POST'])
@check_auth
@check_permission('company_info:edit')
def save_company_info():
    """Update scoped company fields with optimistic concurrency control."""
    data = get_json_body()
    if not data:
        return jsonify({'error': '提交数据为空'}), 400
    version = data.pop('version', None)
    result = CompanyProfileService.update_profile(data, version, g.current_user)
    return jsonify({**result, 'message': '保存成功'})

# ============================================================
