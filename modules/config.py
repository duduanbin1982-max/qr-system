"""
qr-system — 配置常量、权限定义、预置角色、工具函数
"""
import os
import json

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_DIR = os.path.join(BASE_DIR, 'data')
PUBLIC_DIR = os.path.join(BASE_DIR, 'public')
os.makedirs(DATA_DIR, exist_ok=True)
os.makedirs(PUBLIC_DIR, exist_ok=True)

DB_PATH = os.path.join(DATA_DIR, 'production.db')
SESSION_TIMEOUT_HOURS = 0  # 登录超时时间（小时），0表示永不过期
SECRET_KEY = os.environ.get('SECRET_KEY', 'qrsys-...2024')

# ============================================================
# Permission System — 权限系统
# ============================================================
PERMISSION_DEFS = {
    'orders':      ('订单', ['view','create','edit','delete']),
    'customers':   ('客户', ['view','create','edit','delete']),
    'products':    ('产品', ['view','create','edit','delete']),
    'processes':   ('工序', ['view','create','edit','delete']),
    'routes':      ('工艺路线', ['view','create','edit','delete']),
    'prices':      ('工价', ['view','create','edit','delete']),
    'users':       ('用户', ['view','create','edit','delete']),
    'roles':       ('角色', ['view','create','edit','delete']),
    'role_groups': ('角色组', ['view','create','edit','delete']),
    'positions':   ('岗位', ['view','create','edit','delete']),
    'inventory':   ('库存', ['view','create','edit','delete']),
    'shipments':   ('发货', ['view','create','edit','delete']),
    'scan':        ('扫码报工', ['view','edit']),
    'stats':       ('统计', ['view']),
    'trace':       ('追溯', ['view']),
    'approvals':   ('审批', ['view','create','edit']),
    'reports':     ('报表', ['view']),
    'dashboard':   ('工作台', ['view']),
    'board':       ('看板', ['view']),
    'settings':    ('系统设置', ['manage']),
    'logs':        ('操作日志', ['view']),
}
SYSTEM_MANAGE_PERM = 'settings:manage'

# 预置角色权限配置
PREDEFINED_ROLES = {
    1: {  # 系统管理员 — 全部
        'name': '系统管理员', 'code': 'admin',
        'description': '系统内置管理员，拥有全部权限',
        'group_id': 1, 'level': 1,
        'permissions': ['*']  # * 表示全部
    },
    2: {  # 普通员工 — 仅扫码报工
        'name': '普通员工', 'code': 'worker',
        'description': '普通工人，可进行报工操作',
        'group_id': 2, 'level': 1,
        'permissions': ['scan:view', 'scan:edit']
    },
    # 以下为新增预置
    'production_manager': {
        'name': '生产主管', 'code': 'production_manager',
        'description': '管理生产订单、工艺和工价',
        'group_id': 2, 'level': 2,
        'permissions': [
            'orders:view','orders:create','orders:edit','orders:delete',
            'products:view', 'customers:view',
            'processes:view', 'routes:view','routes:create','routes:edit','routes:delete',
            'prices:view','prices:create','prices:edit','prices:delete',
            'scan:view', 'scan:edit', 'stats:view', 'trace:view', 'reports:view', 'board:view',
            'approvals:view', 'approvals:edit','inventory:view',
        ]
    },
    'qc_inspector': {
        'name': '质检员', 'code': 'qc_inspector',
        'description': '质检岗位，扫码报工+追溯+统计',
        'group_id': 2, 'level': 3,
        'permissions': ['scan:view', 'scan:edit', 'trace:view', 'stats:view', 'products:view']
    },
    'warehouse_keeper': {
        'name': '仓库管理员', 'code': 'warehouse_keeper',
        'description': '管理库存和发货',
        'group_id': 2, 'level': 3,
        'permissions': [
            'inventory:view','inventory:create','inventory:edit','inventory:delete',
            'shipments:view','shipments:create','shipments:edit','shipments:delete',
            'products:view',
        ]
    },
}

def expand_permissions(perm_list):
    """展开权限列表，['*'] 返回所有权限，否则展开为 'resource:action'"""
    if '*' in perm_list:
        result = []
        for res, (_, actions) in PERMISSION_DEFS.items():
            for act in actions:
                result.append(f'{res}:{act}')
        result.append(SYSTEM_MANAGE_PERM)
        return result
    return perm_list

# ============================================================
# 中文转拼音首字母（用于产品编码自动生成）
# ============================================================
def _get_pinyin_initial(char):
    """单个汉字转拼音首字母，大写。无法识别则返回空字符串。"""
    py_map = {
        # 档位
        '三':'S', '档':'D', '两':'L', '单':'D', '双':'S',
        # 数字
        '一':'Y', '二':'E', '四':'S', '五':'W', '六':'L', '七':'Q', '八':'B', '九':'J', '十':'S',
        # 尺寸形状
        '宽':'K', '窄':'Z', '高':'G', '低':'D', '短':'D', '长':'C',
        '小':'X', '大':'D', '厚':'H', '薄':'B',
        '圆':'Y', '方':'F', '直':'Z',
        # 类型
        '普':'P', '通':'T', '型':'X',
        # 方向
        '上':'S', '下':'X', '左':'Z', '右':'Y',
        # 开合
        '开':'K', '口':'K',
        # 特殊功能（本次补充）
        '静':'J', '音':'Y', '分':'F', '体':'T',
        # 角
        '角':'J',
    }
    return py_map.get(char, '')

def generate_product_code(product_name, model, spec, upper_opening, plate_thickness, style=''):
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
    # 上开档（纯数字）
    opening = clean_num(upper_opening)
    if opening:
        parts.append(opening)
    # 板厚（纯数字）
    thickness = clean_num(plate_thickness)
    if thickness:
        parts.append(thickness)
    # 款式
    if style and str(style).strip():
        parts.append(str(style).strip())

    return '-'.join(parts)
