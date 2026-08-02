#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
扫码报工生产管理系统 — 入口文件
Flask + SQLite，内网部署。路由通过模块化装饰器注册。
"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from flask import abort, g, make_response, redirect, render_template
from modules.app import app
from modules.config import PUBLIC_DIR
from modules.db import close_db
from modules.runtime_version import get_application_version

# 注册 teardown 回调
app.teardown_appcontext(close_db)

# 加载路由模块（装饰器在 import 时自动注册 @app.route）
from modules.routes.registry import register_routes

register_routes()
# CORS + OPTIONS 统一在 app.py 的 @app.after_request 中处理

# ============================================================
# Static files
# ============================================================
LEGACY_PAGE_REDIRECTS = {
    "reports.html": "/?page=reports",
    "audit-logs.html": "/?page=settings&settings_tab=audit-logs",
    "batch-qr.html": "/?page=orders",
}

STANDALONE_HTML_PAGES = frozenset({
    "mobile.html",
    "mobile_inspection.html",
    "board.html",
    "bigscreen.html",
    "offline.html",
    "swagger-ui.html",
})


@app.route('/')
def index():
    resp = make_response(render_template('static/index.html', nonce=getattr(g, 'csp_nonce', '')))
    resp.headers['Cache-Control'] = 'no-cache, no-store, must-revalidate'
    resp.headers['Pragma'] = 'no-cache'
    resp.headers['Expires'] = '0'
    return resp

@app.route('/<path:filename>')
def static_files(filename):
    """Serve explicit HTML entrypoints and static assets from PUBLIC_DIR."""
    if filename.startswith('api/') or filename.startswith('api'):
        abort(404)
    if filename in LEGACY_PAGE_REDIRECTS:
        return redirect(LEGACY_PAGE_REDIRECTS[filename], code=302)
    if (
        filename.endswith('.html')
        and filename not in STANDALONE_HTML_PAGES
        and filename not in ('index.html', 'index-v3.html')
    ):
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
        abort(404)

# ============================================================
if __name__ == '__main__':
    from modules.db import init_db
    init_db()
    print(f'=== 扫码报工生产管理系统 v{get_application_version()} ===')
    import ssl
    ssl_cert = os.environ.get("SSL_CERT_FILE", "server.crt")
    ssl_key = os.environ.get("SSL_KEY_FILE", "server.key")
    ssl_ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    ssl_ctx.load_cert_chain(ssl_cert, ssl_key)
    app.run(host="0.0.0.0", port=3000, debug=False, ssl_context=ssl_ctx)
