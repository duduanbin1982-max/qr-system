"""
qr-system — 系统设置

注：Swagger docstring 仅供文档参考。
"""
import json
from datetime import datetime

from flask import request, jsonify, g

from modules.app import app
from modules.db import get_setting, clear_settings_cache
from modules.middleware.auth import check_auth, check_permission, audit_log
from modules.middleware.helpers import get_json_body
from modules.services.setting_service import SettingsService

# 允许的设置 key 白名单（模块级常量）
ALLOWED_KEYS = {
    'company_name', 'contact', 'phone', 'address', 'description',
    'default_password', 'approval_enabled', 'auto_order_no', 'page_size',
    # 工艺管理
    'process_order_mode',    # sequential | out_of_order
    'delivery_warning_days', # 交期预警天数（0=不预警）
    'limit_by_prev_process', # 报工不超上道累计（1/0）
    'limit_by_order_qty',    # 报工累计不超订单数（1/0）
    # session security
    'session_timeout_hours',   # 会话超时（小时），0=不过期
    'session_idle_minutes',    # 闲置登出（分钟），0=不禁用
    # 看板
    'board_token',             # 数据看板访问令牌
    # 邮件
    'smtp_host', 'smtp_port', 'smtp_user', 'smtp_password',
    'smtp_from', 'smtp_tls', 'report_recipients',
    # 性能
    'slow_request_threshold_ms', # 慢请求阈值（毫秒）
}


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
        'company_name': get_setting('company_name', ''),
    })

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

    # 处理待删除的 key（前端 _deleted_keys 列表）
    deleted_keys = data.pop('_deleted_keys', [])
    if not isinstance(deleted_keys, list):
        deleted_keys = []

    for k in list(data.keys()):
        k_stripped = k.strip()
        if not k_stripped:
            return jsonify({'error': '设置项名称不能为空'}), 400
        if k_stripped not in ALLOWED_KEYS:
            return jsonify({'error': f'不允许的设置项: {k_stripped}'}), 400
        v = data[k]
        if v is None:
            v = ''
        # 数字类型校验
        if k_stripped == 'page_size':
            try:
                v = int(v)
                if v < 1 or v > 500:
                    return jsonify({'error': '每页条数需在 1-500 之间'}), 400
            except (ValueError, TypeError):
                return jsonify({'error': '每页条数必须为整数'}), 400
        # 工艺管理校验
        if k_stripped == 'process_order_mode':
            v = str(v).strip()
            if v not in ('sequential', 'out_of_order'):
                return jsonify({'error': '报工模式只能为 sequential 或 out_of_order'}), 400
        if k_stripped == 'delivery_warning_days':
            try:
                v = int(v)
                if v < 0:
                    return jsonify({'error': '交期预警天数不能为负数'}), 400
                if v > 365:
                    return jsonify({'error': '交期预警天数不能超过 365'}), 400
            except (ValueError, TypeError):
                return jsonify({'error': '交期预警天数必须为整数'}), 400
        if k_stripped in ('limit_by_prev_process', 'limit_by_order_qty'):
            v = str(v).strip()
            if v not in ('0', '1', ''):
                return jsonify({'error': f'{k_stripped} 只能为 0 或 1'}), 400
        # auto_order_no 校验
        if k_stripped == 'auto_order_no':
            v = str(v).strip()
            if len(v) > 32:
                return jsonify({'error': '订单号前缀不能超过32个字符'}), 400
        # 布尔类型校验
        if k_stripped == 'approval_enabled':
            v = str(v).strip()
            if v not in ('0', '1', ''):
                return jsonify({'error': '审批启用只能为 0 或 1'}), 400
        # 重写为规范化 key
        del data[k]
        data[k_stripped] = str(v)

    try:
        # Filter to ALLOWED_KEYS for deletion
        valid_deletes = [k for k in deleted_keys if k in ALLOWED_KEYS]
        SettingsService.save(data, valid_deletes)
    except Exception:
        return jsonify({'error': '保存失败，请重试'}), 500

    try:
        clear_settings_cache()
    except Exception:
        pass  # 缓存清理失败不影响主流程
    # 逐 key 记录变更（截断到 1900 字符，避免超 audit_log 2000 限制）
    try:
        parts = [f'{k}={str(v)[:80]}' for k, v in data.items()]
        if deleted_keys:
            parts.append(f'_deleted={",".join(deleted_keys[:20])}')
        audit_log('save_settings', detail=', '.join(parts)[:1900])
    except Exception:
        pass
    return jsonify({'message': '保存成功'})

# ============================================================
