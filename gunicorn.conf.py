# gunicorn config for qr-system
import os
import gunicorn

# 隐藏 Server 响应头（默认暴露 gunicorn 版本号）
gunicorn.SERVER = 'webserver'

chdir = '/home/dubin/qr-system'
bind = '0.0.0.0:3000'
certfile = 'server.crt'
keyfile = 'server.key'
workers = 1        # SQLite — 单 worker 避免写锁竞争 + 迁移竞态
timeout = 120
accesslog = 'logs/gunicorn_access.log'
errorlog = 'logs/gunicorn_error.log'
loglevel = 'info'
raw_env = [
    'SECRET_KEY=1d0cf9fe2aa958d4300e53fc02e09243c1d4d324b13c1fff18507aa3badea773'
]

def on_starting(server):
    os.chdir('/home/dubin/qr-system')
    from modules.db import init_db
    init_db()
    server.log.info('Database initialized')
