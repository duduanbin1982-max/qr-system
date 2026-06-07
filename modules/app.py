"""
qr-system — Flask 应用实例
独立模块，解决循环导入问题：所有路由文件和 server.py 都从这里导入 app
"""
from flask import Flask, request, jsonify
from modules.middleware.rate_limit import apply_global_rate_limit
from flasgger import Swagger
import os

_base = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PUBLIC_DIR = os.path.join(_base, 'public')

app = Flask(__name__, static_folder=PUBLIC_DIR, template_folder=PUBLIC_DIR)
app.jinja_env.variable_start_string = '{$'
app.jinja_env.variable_end_string = '$}'
_secret = os.environ.get('SECRET_KEY')
if _secret:
    app.secret_key = _secret
app.config["MAX_CONTENT_LENGTH"] = 16 * 1024 * 1024  # 限制请求体最大 16MB
from modules.middleware.error_handler import register_error_handlers
register_error_handlers(app)

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

swagger = Swagger(app, config=swagger_config, template=swagger_template)


@app.before_request
def api_version_prefix():
    """透明支持 /api/v1/ 前缀 → 内部路由不变，未来版本化准备"""
    if request.path.startswith('/api/v1/'):
        request.environ['PATH_INFO'] = request.path.replace('/api/v1/', '/api/', 1)

# ============================================================
# CORS 白名单 + 安全头中间件
# ============================================================
ALLOWED_ORIGINS = {
    'https://192.168.1.75:3000',
    'http://192.168.1.75:3000',
    'http://localhost:3000',
    # 公网域名/端口在此添加
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
    elif not origin:
        response.headers['Access-Control-Allow-Origin'] = '*'
    else:
        # 非白名单来源：返回默认 origin（不暴露 '*'）
        response.headers['Access-Control-Allow-Origin'] = 'https://192.168.1.75:3000'

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

    # Content-Security-Policy（宽松版 — 1326个内联事件不允许 strict）
    response.headers['Content-Security-Policy'] = (
        "default-src 'self'; "
        "script-src 'self' 'unsafe-inline' 'unsafe-eval' cdn.jsdelivr.net; "
        "style-src 'self' 'unsafe-inline'; "
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
    """健康检查端点（负载均衡探测用）"""
    if request.method == 'OPTIONS':
        return '', 204
    return jsonify({'status': 'ok', 'version': '2.0'})
