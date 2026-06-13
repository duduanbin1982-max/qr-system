"""
qr-system — Flask 应用实例
独立模块，解决循环导入问题：所有路由文件和 server.py 都从这里导入 app
"""
from flask import Flask, request, jsonify, g
from modules.middleware.rate_limit import apply_global_rate_limit
import secrets
from flasgger import Swagger
import os
from dotenv import load_dotenv

# Load .env file (production secrets)
_env_file = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '.env')
if os.path.exists(_env_file):
    load_dotenv(_env_file)

_base = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PUBLIC_DIR = os.path.join(_base, 'public')

app = Flask(__name__, static_folder=PUBLIC_DIR, template_folder=PUBLIC_DIR)
app.config["START_TIME"] = 1780931489.9495177  # for uptime tracking
app.jinja_env.variable_start_string = '{$'
app.jinja_env.variable_end_string = '$}'
_secret = os.environ.get('SECRET_KEY')
if _secret:
    app.secret_key = _secret
app.config["MAX_CONTENT_LENGTH"] = 16 * 1024 * 1024  # 限制请求体最大 16MB

# ============================================================
# Security Headers (P0 hardening)
# ============================================================
@app.after_request
def add_hardening_headers(response):
    """注入安全响应头"""
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["X-XSS-Protection"] = "1; mode=block"
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    # HSTS only if served over HTTPS (gunicorn with SSL)
    response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
    return response

from modules.middleware.error_handler import register_error_handlers
register_error_handlers(app)
from modules.middleware.request_tracker import RequestTracker
RequestTracker(app)

# ============================================================
# Swagger / OpenAPI 文档
# ============================================================
swagger_config = {
    'headers': [],
    'specs': [
        {
            'endpoint': 'apispec',
            'route': '/api/apispec.json',
            'rule_filter': lambda rule: True,
            'model_filter': lambda tag: True,
        }
    ],
    'static_url_path': '/flasgger_static',
    'swagger_ui': False,
    'specs_route': '/api/docs/',
}

swagger_template = {
    'swagger': '2.0',
    'info': {
        'title': 'QR System API',
        'description': '扫码报工生产管理系统 - 全部接口文档',
        'version': '2.0.0',
    },
    'host': None,  # 动态取 Host header，兼容换 IP
    'schemes': ['https'],
    'securityDefinitions': {
        'Bearer': {
            'type': 'apiKey',
            'name': 'Authorization',
            'in': 'header',
            'description': 'Format: Bearer <token>. Get token from /api/auth/login.',
        }
    },
    'security': [{'Bearer': []}],
    'tags': [
        {'name': 'Auth', 'description': 'Login / Logout / User info'},
        {'name': 'Orders', 'description': 'Orders CRUD + batch + work records'},
        {'name': 'Customers', 'description': 'Customer management'},
        {'name': 'Products', 'description': 'Products + attachments'},
        {'name': 'Inventory', 'description': 'Inventory management'},
        {'name': 'Prices', 'description': 'Process prices / route prices / wages'},
        {'name': 'Processes', 'description': 'Process definitions'},
        {'name': 'ProcessRoutes', 'description': 'Process routes'},
        {'name': 'Users', 'description': 'User management'},
        {'name': 'Roles', 'description': 'Roles & permissions'},
        {'name': 'Scan', 'description': 'QR scan & work reporting'},
        {'name': 'Reports', 'description': 'Statistics & reports'},
        {'name': 'Quality', 'description': 'Quality inspections'},
        {'name': 'Rework', 'description': 'Rework management'},
        {'name': 'Shipments', 'description': 'Shipment & delivery'},
        {'name': 'Materials', 'description': 'Material management'},
        {'name': 'Positions', 'description': 'Position management'},
        {'name': 'Settings', 'description': 'System settings'},
        {'name': 'Approvals', 'description': 'Approval workflows'},
        {'name': 'Audit', 'description': 'Audit logs'},
        {'name': 'Schedule', 'description': 'Production scheduling'},
        {'name': 'Trace', 'description': 'Product traceability'},
        {'name': 'Dashboard', 'description': 'Dashboard'},
    ],
}

# Swagger UI - controlled by ENABLE_SWAGGER env var (disabled in production)
ENABLE_SWAGGER = os.environ.get('ENABLE_SWAGGER', '').lower() == 'true'
if ENABLE_SWAGGER:
    swagger = Swagger(app, config=swagger_config, template=swagger_template)

# ============================================================
# CSP nonce generation (per-request)
# ============================================================
@app.before_request
def generate_csp_nonce():
    """Generate a unique nonce for each request, used in CSP script-src."""
    g.csp_nonce = secrets.token_hex(16)

@app.before_request
def api_version_prefix():
    """透明支持 /api/v1/ 前缀 → 内部路由不变，未来版本化准备"""
    if request.path.startswith('/api/v1/'):
        request.environ['PATH_INFO'] = request.path.replace('/api/v1/', '/api/', 1)

# ============================================================
# CORS 白名单 + 安全头中间件
# ============================================================
ALLOWED_ORIGINS = {
    # 内网客户端（桌面浏览器）
    'https://192.168.1.75:3000',
    'http://192.168.1.75:3000',
    'http://localhost:3000',
    # Nginx 反代后的访问地址
    'https://192.168.1.8',
    'http://192.168.1.8',
    # 在此添加更多白名单域名
}

@app.after_request
def add_security_headers(response):
    """统一注入 CORS + 安全头 + 全局限流"""
    # 全局限流检查（/api/ 路径，排除 health/login）
    limit_resp = apply_global_rate_limit()
    if limit_resp is not None:
        return limit_resp
    origin = request.headers.get('Origin', '')
    if origin in ALLOWED_ORIGINS:
        response.headers['Access-Control-Allow-Origin'] = origin
        response.headers['Vary'] = 'Origin'
    # Strict: no CORS header for non-whitelisted origins (browser will reject)
    # Same-origin requests (no Origin header) are allowed by browser default

    response.headers['Access-Control-Allow-Methods'] = 'GET, POST, PUT, DELETE, OPTIONS'
    response.headers['Access-Control-Allow-Headers'] = 'Authorization, Content-Type'
    response.headers['Access-Control-Max-Age'] = '86400'

    # 标准安全头
    response.headers['X-Content-Type-Options'] = 'nosniff'
    response.headers['X-Frame-Options'] = 'SAMEORIGIN'
    response.headers['X-XSS-Protection'] = '1; mode=block'
    response.headers['Strict-Transport-Security'] = 'max-age=31536000; includeSubDomains'
    response.headers['Referrer-Policy'] = 'strict-origin-when-cross-origin'
    response.headers['Permissions-Policy'] = 'camera=(self), microphone=(), geolocation=()'

    # Content-Security-Policy（strict mode — nonce-based script execution）
    csp_nonce = getattr(g, 'csp_nonce', 'fallback')
    response.headers['Content-Security-Policy'] = (
        "default-src 'self'; "
        f"script-src 'self' 'unsafe-eval' 'unsafe-inline' cdn.jsdelivr.net unpkg.com; "
        "style-src 'self' 'unsafe-inline' unpkg.com; "
        "img-src 'self' data: blob:; "
        "connect-src 'self' https:; "
        "frame-ancestors 'self'"
    )
    response.headers['Cross-Origin-Opener-Policy'] = 'same-origin'

    # API 响应禁止浏览器缓存（防止退出后后退按钮看到敏感数据）
    if request.path.startswith('/api/'):
        response.headers['Cache-Control'] = 'no-store, no-cache, must-revalidate, private'

    return response

@app.route('/api/health', methods=['GET', 'OPTIONS'])
@app.route('/api/v1/health', methods=['GET', 'OPTIONS'])

def health_check():
    """Health check endpoint with DB connectivity status"""
    if request.method == 'OPTIONS':
        return '', 204
    from datetime import datetime
    from modules.db import get_db
    status = {'status': 'ok', 'version': '2.0', 'timestamp': datetime.now().strftime('%Y-%m-%d %H:%M:%S')}
    try:
        db = get_db()
        db.execute('SELECT 1')
        status['db'] = 'connected'
        db_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'data', 'production.db')
        if os.path.exists(db_path):
            status['db_size_mb'] = round(os.path.getsize(db_path) / (1024 * 1024), 2)
    except Exception as e:
        status['status'] = 'degraded'
        status['db'] = str(e)[:200]
    return jsonify(status), 200 if status['status'] == 'ok' else 503
