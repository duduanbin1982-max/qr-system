"""
qr-system — 系统设置

注：Swagger docstring 仅供文档参考。
"""
from flask import request, jsonify

from modules.app import app
from modules.middleware.audit import safe_audit_log
from modules.middleware.auth import check_auth, check_permission
from modules.middleware.helpers import get_json_body
from modules.services.setting_service import SettingsService, ALLOWED_KEYS

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
        'company_name': SettingsService.get_value('company_name', ''),
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
    except Exception:
        return jsonify({'error': '保存失败，请重试'}), 500

    try:
        SettingsService.clear_cache()
    except Exception:
        pass

    parts = [f'{k}={str(v)[:80]}' for k, v in data.items()]
    if deleted_keys:
        parts.append(f'_deleted={",".join(deleted_keys[:20])}')
    safe_audit_log('save_settings', detail=', '.join(parts)[:1900])
    return jsonify({'message': '保存成功'})


@app.route('/api/settings/company-info', methods=['POST'])
@check_auth
@check_permission('settings:manage')
def save_company_info():
    """Save only company info fields (scoped)."""
    data = get_json_body()
    if not data:
        return jsonify({'error': '提交数据为空'}), 400

    COMPANY_KEYS = {'company_name', 'contact', 'phone', 'address', 'description'}
    filtered = {k: v for k, v in data.items() if k in COMPANY_KEYS}

    try:
        SettingsService.save(filtered, [])
    except ValueError as e:
        return jsonify({'error': str(e)}), 400
    except Exception:
        return jsonify({'error': '保存失败，请重试'}), 500

    try:
        SettingsService.clear_cache()
    except Exception:
        pass

    parts = [f'{k}={str(v)[:80]}' for k, v in filtered.items()]
    safe_audit_log('save_company_info', detail=', '.join(parts)[:1900])
    return jsonify({'message': '保存成功'})

# ============================================================
