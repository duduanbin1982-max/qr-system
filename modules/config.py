"""
qr-system — 配置常量、权限定义、预置角色、工具函数
"""
import os
import json
from typing import Any, Dict, List, Optional, Tuple

from modules.permission_catalog import ACTION_PERMISSION_DEFS, ALL_PERMISSION_CODES

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_DIR = os.path.join(BASE_DIR, 'data')
PUBLIC_DIR = os.path.join(BASE_DIR, 'public')
os.makedirs(DATA_DIR, exist_ok=True)
os.makedirs(PUBLIC_DIR, exist_ok=True)

DB_PATH = os.environ.get('DB_PATH') or os.path.join(DATA_DIR, 'production.db')
SESSION_TIMEOUT_HOURS = 8  # 登录超时时间（小时），0表示永不过期
SESSION_IDLE_MINUTES = 480  # idle timeout (8 hours)

# File upload whitelist (lowercase extensions with dot)
ALLOWED_UPLOAD_EXTENSIONS = {
    # Documents
    ".pdf", ".doc", ".docx", ".xls", ".xlsx", ".csv", ".txt",
    # Images
    ".jpg", ".jpeg", ".png", ".gif", ".bmp", ".webp", ".svg",
    # Archives
    ".zip", ".rar", ".7z",
    # CAD/Drawings
    ".dwg", ".dxf", ".step", ".stp", ".igs", ".iges",
}
SECRET_KEY = os.environ.get('SECRET_KEY')
if not SECRET_KEY:
    raise RuntimeError('SECRET_KEY 环境变量未设置！请在生产环境通过 ecosystem.config.js 或系统环境变量设置强密钥。')

# ============================================================
# Permission System — 权限系统
# ============================================================
PERMISSION_DEFS = ACTION_PERMISSION_DEFS
SYSTEM_MANAGE_PERM = 'settings:manage'

# 预置角色权限配置
# 注：所有键统一为字符串 code
PREDEFINED_ROLES = {
    'admin': {  # 系统管理员 — 全部
        'name': '系统管理员', 'code': 'admin',
        'description': '系统内置管理员，拥有全部权限',
        'group_id': 1, 'level': 1,
        'permissions': ['*']  # * 表示全部
    },
    'worker': {  # 普通员工 — 仅扫码报工
        'name': '普通员工', 'code': 'worker',
        'description': '普通工人，可进行报工操作',
        'group_id': 2, 'level': 1,
        'permissions': ['page:scan', 'scan:view', 'scan:report']
    },
    # 以下为新增预置
    'production_manager': {
        'name': '生产主管', 'code': 'production_manager',
        'description': '管理生产订单、工艺和工价',
        'group_id': 2, 'level': 2,
        'permissions': [
            'page:production', 'page:production.orders', 'page:production.customers',
            'page:production.materials', 'page:production.trace', 'page:production.approvals',
            'page:production.quality', 'page:production.rework',
            'page:scan', 'page:stats', 'page:reports', 'page:inventory', 'page:board',
            'orders:view','orders:create','orders:edit','orders:delete',
            'products:view', 'customers:view',
            'processes:view', 'routes:view','routes:create','routes:edit','routes:delete',
            'prices:view','prices:create','prices:edit','prices:delete',
            'scan:view', 'scan:report', 'stats:view', 'trace:view', 'reports:view', 'board:view',
            'approvals:view', 'approvals:edit','inventory:view','materials:view','quality:view','rework:view','rework:create','rework:edit',
        ]
    },
    'qc_inspector': {
        'name': '质检员', 'code': 'qc_inspector',
        'description': '质检岗位，扫码报工+追溯+统计',
        'group_id': 2, 'level': 3,
        'permissions': [
            'page:scan', 'page:production', 'page:production.trace', 'page:stats',
            'scan:view', 'scan:report', 'trace:view', 'stats:view', 'products:view'
        ]
    },
    'warehouse_keeper': {
        'name': '仓库管理员', 'code': 'warehouse_keeper',
        'description': '管理库存和发货',
        'group_id': 2, 'level': 3,
        'permissions': [
            'page:inventory', 'page:shipments',
            'inventory:view','inventory:create','inventory:edit','inventory:delete',
            'shipments:view','shipments:create','shipments:edit','shipments:delete',
            'products:view',
        ]
    },
}

# Permissions that grant global data scope (view all data regardless of position)
GLOBAL_DATA_SCOPE_PERMS = {
    "orders:view", "stats:view", "inventory:view", "*",
    "shipments:view", "reports:view", "dashboard:view",
    "scan:view", "scan:report",
}

def expand_permissions(perm_list: List[str]) -> List[str]:
    """展开权限列表，['*'] 返回所有权限，否则展开为 'resource:action'"""
    if '*' in perm_list:
        return list(ALL_PERMISSION_CODES)
    return perm_list

# ============================================================
# 中文转拼音首字母（用于产品编码自动生成）
# ============================================================
def _get_pinyin_initial(char: str) -> str:
    """单个汉字转拼音首字母，大写。无法识别则返回空字符串。"""
    py_map = {
        '三':'S', '档':'D', '两':'L', '单':'D', '双':'S',
        '一':'Y', '二':'E', '四':'S', '五':'W', '六':'L', '七':'Q', '八':'B', '九':'J', '十':'S',
        '宽':'K', '窄':'Z', '高':'G', '低':'D', '短':'D', '长':'C',
        '小':'X', '大':'D', '厚':'H', '薄':'B',
        '圆':'Y', '方':'F', '直':'Z',
        '普':'P', '通':'T', '型':'X',
        '上':'S', '下':'X', '左':'Z', '右':'Y',
        '开':'K', '口':'K',
        '静':'J', '音':'Y', '分':'F', '体':'T',
        '角':'J',
        '中':'Z','重':'Z','新':'X','全':'Q','钢':'G','铁':'T','铜':'T','铝':'L','不':'B','超':'C','特':'T','精':'J',
        '加':'J','工':'G','冲':'C','压':'Y','焊':'H','切':'Q','折':'Z','卷':'J','车':'C','铣':'X','磨':'M','钻':'Z',
        '前':'Q','后':'H','内':'N','顶':'D','底':'D','侧':'C','正':'Z','反':'F',
        # Role/management characters
        '管':'G','理':'L','员':'Y','检':'J','质':'Z','统':'T','计':'J','财':'C','务':'W',
        '采':'C','购':'G','销':'X','售':'S','仓':'C','库':'K','运':'Y','维':'W','修':'X',
        '人':'R','事':'S','行':'X','政':'Z','经':'J','总':'Z','监':'J','主':'Z','副':'F',
        '组':'Z','长':'Z','班':'B','普':'P','通':'T','操':'C','作':'Z','设':'S','备':'B',
        '安':'A','环':'H','保':'B','审':'S','核':'H','批':'P','发':'F','收':'S','付':'F',
        '进':'J','出':'C','存':'C','盘':'P','点':'D','调':'D','拨':'B','退':'T','换':'H',
    }
    return py_map.get(char, '')

def generate_product_code(product_name, model, spec, upper_opening, plate_thickness, style='', lower_opening='', category='结构件'):
    """
    根据产品名称、型号、规格、上开档尺寸、板厚、款式自动生成产品编码。
    格式：产品名称-型号(全大写)-规格前2字拼音首大写字母-上开档-板厚-款式(汉字)
    例如：破碎锤-SB81-FT-330-25-正坤2-1订单
    空字段自动省略
    """
    def clean_num(s):
        return ''.join(c for c in str(s) if c.isdigit())

    def spec_pinyin(s):
        """取规格前2字，转拼音首字母大写"""
        s = str(s).strip()
        result = []
        for ch in s[:2]:
            p = _get_pinyin_initial(ch)
            if p:
                result.append(p)
        return ''.join(result)

    parts = []
    # 产品名称
    if product_name and str(product_name).strip():
        parts.append(str(product_name).strip())
    # 型号（全大写）
    if model and str(model).strip():
        parts.append(str(model).strip().upper())
    # 规格前2字拼音首大写字母
    if spec and str(spec).strip():
        px = spec_pinyin(spec)
        if px:
            parts.append(px)
    # 口尺寸（结构件专用）
    if category == '结构件':
        opening = clean_num(upper_opening)
        if opening:
            parts.append(opening)
        lo = clean_num(lower_opening)
        if lo:
            parts.append(lo)
    # 板厚（纯数字）
    thickness = clean_num(plate_thickness)
    if thickness:
        parts.append(thickness)
    # 款式
    if style and str(style).strip():
        parts.append(str(style).strip())

    return '-'.join(parts)
