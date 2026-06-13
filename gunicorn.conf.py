import os
from dotenv import load_dotenv
_env_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env")
if os.path.exists(_env_path):
    load_dotenv(_env_path)

# gunicorn config for qr-system
import os
import gunicorn

# 隐藏 Server 响应头（默认暴露 gunicorn 版本号）
gunicorn.SERVER = 'webserver'

chdir = '/home/dubin/qr-system'
bind = '127.0.0.1:3000'
certfile = 'server.crt'
keyfile = 'server.key'
workers = 2        # SQLite WAL mode supports concurrent reads, BEGIN IMMEDIATE handles write conflicts
timeout = 120
accesslog = 'logs/gunicorn_access.log'
errorlog = 'logs/gunicorn_error.log'
loglevel = 'info'
raw_env = [
    'SECRET_KEY=' + os.environ.get('SECRET_KEY', 'change-me')
]

def on_starting(server):
    os.chdir('/home/dubin/qr-system')
    from modules.db import init_db
    init_db()
