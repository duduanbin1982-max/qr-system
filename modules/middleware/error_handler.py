"""
qr-system — 全局错误处理

统一异常格式，生产环境隐藏内部错误细节。
"""
import traceback
import logging
from flask import jsonify

logger = logging.getLogger('qr-system')


def handle_unexpected_error(e: Exception, context: str = '') -> tuple:
    """统一处理未预期异常：记录完整 traceback，返回通用错误消息。
    
    Args:
        e: 异常对象
        context: 操作上下文描述（如 '创建订单'）
    
    Returns:
        (jsonify_response, status_code) 元组
    """
    logger.error(f'Unexpected error [{context}]: {type(e).__name__}: {e}')
    logger.error(traceback.format_exc())
    return jsonify({'error': '服务器内部错误，请稍后重试'}), 500


def register_error_handlers(app):
    """注册 Flask 全局错误处理器"""
    
    @app.errorhandler(400)
    def bad_request(e):
        return jsonify({'error': '请求参数无效'}), 400
    
    @app.errorhandler(404)
    def not_found(e):
        return jsonify({'error': '资源不存在'}), 404
    
    @app.errorhandler(405)
    def method_not_allowed(e):
        return jsonify({'error': '不支持的请求方法'}), 405
    
    @app.errorhandler(413)
    def too_large(e):
        return jsonify({'error': '请求体过大，最大允许 16MB'}), 413
    
    @app.errorhandler(429)
    def rate_limited(e):
        return jsonify({'error': '请求过于频繁，请稍后再试'}), 429
    
    @app.errorhandler(500)
    def internal_error(e):
        logger.error(f'Internal server error: {e}')
        logger.error(traceback.format_exc())
        return jsonify({'error': '服务器内部错误，请稍后重试'}), 500

