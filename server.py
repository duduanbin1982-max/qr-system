#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
扫码报工生产管理系统 V2 — 入口文件
Flask + SQLite，内网部署。路由通过模块化装饰器注册。
"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from flask import render_template, make_response, g
from modules.app import app
from modules.config import PUBLIC_DIR
from modules.db import close_db

# 注册 teardown 回调
app.teardown_appcontext(close_db)

# 加载路由模块（装饰器在 import 时自动注册 @app.route）
from modules.routes.registry import register_routes

register_routes()
# CORS + OPTIONS 统一在 app.py 的 @app.after_request 中处理

# ============================================================
# Static files
# ============================================================
@app.route('/')
def index():
    resp = make_response(render_template('static/index.html', nonce=getattr(g, 'csp_nonce', '')))
    resp.headers['Cache-Control'] = 'no-cache, no-store, must-revalidate'
    resp.headers['Pragma'] = 'no-cache'
    resp.headers['Expires'] = '0'
    return resp

@app.route('/<path:filename>')
def static_files(filename):
    """Serve static assets (js/, css/, vendor/, etc.) from PUBLIC_DIR.
    
    Safety: reject paths starting with 'api/' to prevent shadowing API routes.
    HTML files are rendered as Jinja2 templates for CSP nonce injection.
    """
    if filename.startswith('api/') or filename.startswith('api'):
        from flask import abort
        abort(404)
    try:
        if filename in ('index.html', 'index-v3.html'):
            resp = make_response(render_template('static/index.html', nonce=getattr(g, 'csp_nonce', '')))
        elif filename.endswith('.html'):
            resp = make_response(render_template(filename, nonce=getattr(g, 'csp_nonce', '')))
        else:
            resp = app.send_static_file(filename)
        resp.headers['Cache-Control'] = 'no-cache, no-store, must-revalidate'
        resp.headers['Pragma'] = 'no-cache'
        resp.headers['Expires'] = '0'
        return resp
    except Exception:
        from flask import abort
        abort(404)

# ============================================================
if __name__ == '__main__':
    from modules.db import init_db
    init_db()
    print('=== 扫码报工生产管理系统 V2 ===')
    import ssl
    ssl_cert = os.environ.get("SSL_CERT_FILE", "server.crt")
    ssl_key = os.environ.get("SSL_KEY_FILE", "server.key")
    ssl_ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    ssl_ctx.load_cert_chain(ssl_cert, ssl_key)
    app.run(host="0.0.0.0", port=3000, debug=False, ssl_context=ssl_ctx)
