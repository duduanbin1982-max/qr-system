"""qr-system - SettingsService (Repository-refactored)"""
from modules.services import BaseService
from modules.repositories.setting_repository import SettingRepository

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

SENSITIVE_KEYS = {'smtp_password', 'board_token'}

SETTING_VALIDATORS = {
    'page_size': (int, 1, 500, 'Page size must be 1-500'),
    'delivery_warning_days': (int, 0, 365, 'Delivery warning days must be 0-365'),
    'process_order_mode': (str, None, None, 'Process order mode must be sequential or out_of_order'),
    'limit_by_prev_process': (str, None, None, 'Must be 0 or 1'),
    'limit_by_order_qty': (str, None, None, 'Must be 0 or 1'),
    'approval_enabled': (str, None, None, 'Must be 0 or 1'),
    'auto_order_no': (str, None, None, 'Order no prefix max 32 chars'),
}

def validate_setting(key, value):
    if key not in ALLOWED_KEYS:
        return None, 'Invalid setting: ' + key
    if value is None:
        return '', None
    if key not in SETTING_VALIDATORS:
        return str(value), None
    parse_fn, vmin, vmax, err_msg = SETTING_VALIDATORS[key]
    try:
        parsed = parse_fn(value)
    except (ValueError, TypeError):
        return None, err_msg
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
        return sorted(ALLOWED_KEYS)

    @staticmethod
    def get_all():
        rows = SettingRepository.get_all()
        return {r["key"]: r["value"] for r in rows if r["key"] not in SENSITIVE_KEYS}

    @staticmethod
    def save(updates, deleted_keys):
        validated = {}
        for k, v in updates.items():
            val, err = validate_setting(k, v)
            if err:
                raise ValueError(err)
            validated[k] = val
        valid_deletes = [k for k in deleted_keys if k in ALLOWED_KEYS]
        with BaseService.transaction() as txn:
            for k, v in validated.items():
                SettingRepository.upsert_txn(k, v, db=txn)
            for k in valid_deletes:
                SettingRepository.delete_txn(k, db=txn)
