"""
qr-system — SettingsService
"""
from modules.services import BaseService

# Setting key whitelist — single source of truth
ALLOWED_KEYS = {
    'company_name', 'contact', 'phone', 'address', 'description',
    'default_password', 'approval_enabled', 'auto_order_no', 'page_size',
    'process_order_mode', 'delivery_warning_days',
    'limit_by_prev_process', 'limit_by_order_qty',
    'session_timeout_hours', 'session_idle_minutes',
    'board_token', 'board_token_created_at',
    'smtp_host', 'smtp_port', 'smtp_user', 'smtp_password',
    'smtp_from', 'smtp_tls', 'report_recipients',
    'slow_request_threshold_ms',
}


# Sensitive keys — never returned via GET /api/settings
SENSITIVE_KEYS = {'smtp_password', 'board_token'}

# Per-key validators: (parse_fn, min, max, error_msg)
SETTING_VALIDATORS = {
    'page_size': (int, 1, 500, '每页条数需在 1-500 之间'),
    'delivery_warning_days': (int, 0, 365, '交期预警天数需在 0-365 之间'),
    'process_order_mode': (str, None, None, '报工模式只能为 sequential 或 out_of_order'),
    'limit_by_prev_process': (str, None, None, '只能为 0 或 1'),
    'limit_by_order_qty': (str, None, None, '只能为 0 或 1'),
    'approval_enabled': (str, None, None, '审批启用只能为 0 或 1'),
    'auto_order_no': (str, None, None, '订单号前缀不能超过32个字符'),
}

def validate_setting(key, value):
    """Validate a single setting value. Returns (normalized_value, None) or (None, error_msg)."""
    if key not in ALLOWED_KEYS:
        return None, f'不允许的设置项: {key}'
    if value is None:
        return '', None
    if key not in SETTING_VALIDATORS:
        return str(value), None
    parse_fn, vmin, vmax, err_msg = SETTING_VALIDATORS[key]
    try:
        parsed = parse_fn(value)
    except (ValueError, TypeError):
        return None, err_msg
    
    # Special validations
    if key == 'process_order_mode':
        if parsed not in ('sequential', 'out_of_order'):
            return None, err_msg
    elif key in ('limit_by_prev_process', 'limit_by_order_qty', 'approval_enabled'):
        if str(parsed).strip() not in ('0', '1', ''):
            return None, err_msg
    elif key == 'auto_order_no':
        if len(str(parsed)) > 32:
            return None, err_msg
    else:
        if vmin is not None and parsed < vmin:
            return None, err_msg
        if vmax is not None and parsed > vmax:
            return None, err_msg
    
    return str(parsed), None


class SettingsService:

    @staticmethod
    def get_allowed_keys():
        """Return the list of allowed setting keys (for frontend sync)."""
        return sorted(ALLOWED_KEYS)

    @staticmethod
    def get_all():
        db = BaseService.db()
        rows = db.execute("SELECT * FROM system_settings").fetchall()
        return {r["key"]: r["value"] for r in rows if r["key"] not in SENSITIVE_KEYS}

    @staticmethod
    def save(updates, deleted_keys):
        """Save settings with validation."""
        # Validate all updates first
        validated = {}
        for k, v in updates.items():
            val, err = validate_setting(k, v)
            if err:
                raise ValueError(err)
            validated[k] = val
        
        # Filter deletes
        valid_deletes = [k for k in deleted_keys if k in ALLOWED_KEYS]
        
        db = BaseService.db()
        with BaseService.transaction() as txn:
            for k, v in validated.items():
                txn.execute(
                    "INSERT INTO system_settings (key, value, updated_at) "
                    "VALUES (?,?,datetime('now','localtime')) "
                    "ON CONFLICT(key) DO UPDATE SET value=excluded.value, updated_at=excluded.updated_at",
                    (k, v)
                )
            for k in valid_deletes:
                txn.execute("DELETE FROM system_settings WHERE key = ?", (k,))
