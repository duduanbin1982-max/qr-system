"""qr-system - Request Tracking and Slow Request Logging Middleware"""
import uuid
import time
import logging
from flask import request, g

logger = logging.getLogger('qr-system')


class RequestTracker:
    """Request tracking and slow request logging middleware."""
    default_slow_threshold = 1.0

    def __init__(self, app, slow_threshold=None):
        self.app = app
        self.slow_threshold = slow_threshold or self.default_slow_threshold
        self._register()

    def _get_threshold(self):
        """Read slow threshold from system_settings, fall back to default."""
        try:
            from modules.db import get_setting
            val = get_setting('slow_request_threshold_ms', '')
            if val and val.isdigit():
                return int(val) / 1000.0
        except Exception:
            pass
        return self.slow_threshold

    def _register(self):
        @self.app.before_request
        def before_request():
            g.request_id = str(uuid.uuid4())[:8]
            g.request_start = time.time()

        @self.app.after_request
        def after_request(response):
            elapsed = time.time() - g.get('request_start', 0)
            elapsed_ms = int(elapsed * 1000)
            response.headers['X-Request-ID'] = g.get('request_id', '')
            response.headers['X-Response-Time-Ms'] = str(elapsed_ms)

            threshold = self._get_threshold()
            if elapsed > threshold:
                uid = g.get('current_user', {}).get('id', '-') if hasattr(g, 'current_user') else '-'
                logger.warning(
                    'SLOW [%s] uid=%s %s %s %dms from %s',
                    g.get('request_id', ''),
                    uid,
                    request.method, request.path,
                    elapsed_ms,
                    request.remote_addr or '127.0.0.1'
                )
            return response
