"""
qr-system — Shared domain constants (Brooks R1/R6 fix)
Centralizes magic values that were scattered across services, routes, and templates.
"""
from enum import Enum

class OrderStatus(str, Enum):
    """订单状态 — 对应 orders.status 列"""
    PENDING = 'pending'
    PRODUCING = 'producing'
    COMPLETED = 'completed'
    CANCELLED = 'cancelled'
    PAUSED = 'paused'

class ProductCategory(str, Enum):
    """产品分类 — 对应 products.category 列"""
    STRUCTURE = '结构件'
    MACHINING = '机加工'

class MaterialStockType(str, Enum):
    """物料库存操作类型"""
    IN = 'in'
    OUT = 'out'

# HTTP & Auth
SECONDS_PER_DAY = 86400
SECONDS_PER_WEEK = 604800

# Pagination
DEFAULT_PAGE_SIZE = 20
MAX_PAGE_LIMIT = 500

# File uploads
MAX_ATTACHMENT_SIZE_KB = 1024

# Import limits
MAX_IMPORT_ROWS = 5000
MAX_PREVIEW_ROWS = 330

# Login security
MAX_LOGIN_ATTEMPTS = 5
LOGIN_LOCKOUT_MINUTES = 30
