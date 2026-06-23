"""Settings read helpers decoupled from route/service layers."""
import importlib


def get_setting(key, default=''):
    return importlib.import_module('modules.db').get_setting(key, default)


def clear_settings_cache():
    return importlib.import_module('modules.db').clear_settings_cache()


def get_page_size(default=20):
    value = get_setting('page_size', '')
    try:
        return int(value) if value else default
    except (ValueError, TypeError):
        return default
