"""
qr-system — Flask 应用实例
独立模块，解决循环导入问题：所有路由文件和 server.py 都从这里导入 app
"""
from flask import Flask, request, jsonify
from flasgger import Swagger
import os
from dotenv import load_dotenv
from modules.config import DB_PATH

# Load .env file (production secrets)
_env_file = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '.env')
if os.path.exists(_env_file):
    load_dotenv(_env_file)

_base = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PUBLIC_DIR = os.path.join(_base, 'public')

app = Flask(__name__, static_folder=PUBLIC_DIR, template_folder=PUBLIC_DIR)
app.config['TEMPLATES_AUTO_RELOAD'] = True
app.config["START_TIME"] = 1780931489.9495177  # for uptime tracking
app.jinja_env.variable_start_string = '{$'
app.jinja_env.variable_end_string = '$}'
_secret = os.environ.get('SECRET_KEY')
if _secret:
    app.secret_key = _secret
app.config["MAX_CONTENT_LENGTH"] = 16 * 1024 * 1024  # 限制请求体最大 16MB

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

from modules.app_extensions import register_app_extensions
register_app_extensions(app)

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
        if os.path.exists(DB_PATH):
            status['db_size_mb'] = round(os.path.getsize(DB_PATH) / (1024 * 1024), 2)
    except Exception as e:
        status['status'] = 'degraded'
        status['db'] = str(e)[:200]
    return jsonify(status), 200 if status['status'] == 'ok' else 503
