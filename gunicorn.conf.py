import os
from dotenv import load_dotenv
_env_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env")
if os.path.exists(_env_path):
    load_dotenv(_env_path)

# gunicorn config for qr-system
import gunicorn

# 隐藏 Server 响应头（默认暴露 gunicorn 版本号）
gunicorn.SERVER = 'webserver'

base_dir = os.path.dirname(os.path.abspath(__file__))
chdir = base_dir
bind = '127.0.0.1:3000'
certfile = os.environ.get('SSL_CERT_FILE', 'server.crt')
keyfile = os.environ.get('SSL_KEY_FILE', 'server.key')
workers = 2        # SQLite WAL mode supports concurrent reads, BEGIN IMMEDIATE handles write conflicts
timeout = 120
accesslog = 'logs/gunicorn_access.log'
errorlog = 'logs/gunicorn_error.log'
loglevel = 'info'
raw_env = [
    'SECRET_KEY=' + os.environ['SECRET_KEY']  # fail-secure: crash if not set
]

def on_starting(server):
    os.chdir(base_dir)
    from modules.db import init_db
    init_db()
