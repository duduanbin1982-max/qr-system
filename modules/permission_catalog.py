"""统一权限目录：页面显示权限 + 业务操作权限。

页面权限使用 ``page:*`` 编码，业务权限继续沿用 ``resource:action`` 编码。
角色配置、侧边栏显示、Tab 显示和路由拦截都应以本目录为准。
"""

ACTION_LABELS = {
    "view": "查看",
    "create": "新增",
    "edit": "编辑",
    "delete": "删除",
    "manage": "管理",
    "export": "导出",
    "report": "报工",
    "admin": "管理员",
}

ACTION_PERMISSION_DEFS = {
    "dashboard": ("工作台", ["view"]),
    "orders": ("订单", ["view", "create", "edit", "delete"]),
    "customers": ("客户", ["view", "create", "edit", "delete"]),
    "products": ("产品", ["view", "create", "edit", "delete"]),
    "processes": ("工序", ["view", "create", "edit", "delete"]),
    "routes": ("工序路线", ["view", "create", "edit", "delete"]),
    "prices": ("工价", ["view", "create", "edit", "delete"]),
    "users": ("用户/员工", ["view", "create", "edit", "delete", "admin"]),
    "roles": ("角色", ["view", "create", "edit", "delete"]),
    "role_groups": ("角色组", ["view", "create", "edit", "delete"]),
    "positions": ("岗位", ["view", "create", "edit", "delete"]),
    "inventory": ("库存", ["view", "create", "edit", "delete"]),
    "shipments": ("发货", ["view", "create", "edit", "delete"]),
    "scan": ("扫码报工", ["view", "report"]),
    "stats": ("统计报表", ["view", "export"]),
    "trace": ("产品追溯", ["view"]),
    "approvals": ("审批", ["view", "create", "edit"]),
    "reports": ("数据分析", ["view"]),
    "board": ("数据看板", ["view"]),
    "settings": ("系统设置", ["manage", "edit"]),
    "logs": ("操作日志", ["view", "delete"]),
    "materials": ("物料", ["view", "manage"]),
    "quality": ("质量检验", ["view", "edit", "delete"]),
    "rework": ("返工", ["view", "create", "edit"]),
    "schedule": ("生产排程", ["view"]),
    "wages": ("工资核算", ["view", "edit"]),
}


SIDEBAR_ITEMS = [
    {"page": "dashboard", "code": "page:dashboard", "icon": "📊", "label": "工作台"},
    {"page": "production", "code": "page:production", "icon": "🏭", "label": "生产管理"},
    {"page": "scan", "code": "page:scan", "icon": "📱", "label": "扫码报工"},
    {"page": "inventory", "code": "page:inventory", "icon": "🏗️", "label": "库存管理"},
    {"page": "shipments", "code": "page:shipments", "icon": "🚚", "label": "发货管理"},
    {"page": "stats", "code": "page:stats", "icon": "📈", "label": "统计报表"},
    {"page": "reports", "code": "page:reports", "icon": "📊", "label": "数据分析"},
    {"page": "wages", "code": "page:wages", "icon": "💰", "label": "工资核算"},
    {"page": "basic-settings", "code": "page:basic-settings", "icon": "⚙️", "label": "基础设置"},
    {"page": "settings", "code": "page:settings", "icon": "⚙️", "label": "系统设置"},
]


PAGE_RULES = [
    {"page": "dashboard", "code": "page:dashboard", "label": "工作台"},
    {
        "page": "production",
        "code": "page:production",
        "label": "生产管理",
        "children": [
            {"page": "orders", "code": "page:production.orders", "label": "订单管理"},
            {"page": "customers", "code": "page:production.customers", "label": "客户管理"},
            {"page": "materials", "code": "page:production.materials", "label": "物料管理"},
            {"page": "trace", "code": "page:production.trace", "label": "产品追溯"},
            {"page": "approvals", "code": "page:production.approvals", "label": "审批管理"},
            {"page": "schedule", "code": "page:production.schedule", "label": "生产排程"},
            {"page": "rework", "code": "page:production.rework", "label": "返工管理"},
            {"page": "quality", "code": "page:production.quality", "label": "质量检验"},
        ],
    },
    {"page": "scan", "code": "page:scan", "label": "扫码报工"},
    {"page": "inventory", "code": "page:inventory", "label": "库存管理"},
    {"page": "shipments", "code": "page:shipments", "label": "发货管理"},
    {"page": "stats", "code": "page:stats", "label": "统计报表"},
    {"page": "reports", "code": "page:reports", "label": "数据分析"},
    {"page": "wages", "code": "page:wages", "label": "工资核算"},
    {"page": "board", "code": "page:board", "label": "数据看板"},
    {
        "page": "basic-settings",
        "code": "page:basic-settings",
        "label": "基础设置",
        "children": [
            {"page": "users", "code": "page:basic-settings.users", "label": "员工管理"},
            {"page": "processes", "code": "page:basic-settings.processes", "label": "工序管理"},
            {"page": "routes", "code": "page:basic-settings.routes", "label": "工序路线"},
            {"page": "prices", "code": "page:basic-settings.prices", "label": "工价管理"},
            {"page": "products", "code": "page:basic-settings.products", "label": "产品管理"},
        ],
    },
    {
        "page": "settings",
        "code": "page:settings",
        "label": "系统设置",
        "children": [
            {"page": "company-info", "code": "page:settings.company-info", "label": "公司资料"},
            {"page": "admin-users", "code": "page:settings.admin-users", "label": "管理员管理"},
            {"page": "audit-logs", "code": "page:settings.audit-logs", "label": "操作日志"},
            {"page": "process-config", "code": "page:settings.process-config", "label": "工艺管理"},
            {"page": "role-groups", "code": "page:settings.role-groups", "label": "角色组"},
            {"page": "role-manage", "code": "page:settings.role-manage", "label": "角色管理"},
            {"page": "positions", "code": "page:settings.positions", "label": "岗位管理"},
            {"page": "approval-config", "code": "page:settings.approval-config", "label": "审批配置"},
        ],
    },
]


ACTION_PAGE_MAP = {
    "dashboard": ["page:dashboard"],
    "orders": ["page:production", "page:production.orders"],
    "customers": ["page:production", "page:production.customers"],
    "materials": ["page:production", "page:production.materials"],
    "trace": ["page:production", "page:production.trace"],
    "approvals": ["page:production", "page:production.approvals"],
    "schedule": ["page:production", "page:production.schedule"],
    "rework": ["page:production", "page:production.rework"],
    "quality": ["page:production", "page:production.quality"],
    "scan": ["page:scan"],
    "inventory": ["page:inventory"],
    "shipments": ["page:shipments"],
    "stats": ["page:stats"],
    "reports": ["page:reports"],
    "wages": ["page:wages"],
    "board": ["page:board"],
    "users": ["page:basic-settings", "page:basic-settings.users"],
    "processes": ["page:basic-settings", "page:basic-settings.processes"],
    "routes": ["page:basic-settings", "page:basic-settings.routes"],
    "prices": ["page:basic-settings", "page:basic-settings.prices"],
    "products": ["page:basic-settings", "page:basic-settings.products"],
    "roles": ["page:settings", "page:settings.role-manage"],
    "role_groups": ["page:settings", "page:settings.role-groups"],
    "positions": ["page:settings", "page:settings.positions"],
    "logs": ["page:settings", "page:settings.audit-logs"],
    "settings": [
        "page:settings",
        "page:settings.company-info",
        "page:settings.admin-users",
        "page:settings.audit-logs",
        "page:settings.process-config",
        "page:settings.role-groups",
        "page:settings.role-manage",
        "page:settings.positions",
        "page:settings.approval-config",
    ],
}

PAGE_OPERATION_BINDINGS = {
    "page:dashboard": ["dashboard"],
    "page:production.orders": ["orders"],
    "page:production.customers": ["customers"],
    "page:production.materials": ["materials"],
    "page:production.trace": ["trace"],
    "page:production.approvals": ["approvals"],
    "page:production.schedule": ["schedule"],
    "page:production.rework": ["rework"],
    "page:production.quality": ["quality"],
    "page:scan": ["scan"],
    "page:inventory": ["inventory"],
    "page:shipments": ["shipments"],
    "page:stats": ["stats"],
    "page:reports": ["reports"],
    "page:wages": ["wages"],
    "page:board": ["board"],
    "page:basic-settings.users": ["users"],
    "page:basic-settings.processes": ["processes"],
    "page:basic-settings.routes": ["routes"],
    "page:basic-settings.prices": ["prices"],
    "page:basic-settings.products": ["products"],
    "page:settings.company-info": ["settings"],
    "page:settings.admin-users": ["users"],
    "page:settings.audit-logs": ["logs"],
    "page:settings.process-config": ["settings"],
    "page:settings.role-groups": ["role_groups"],
    "page:settings.role-manage": ["roles"],
    "page:settings.positions": ["positions"],
    "page:settings.approval-config": ["settings", "approvals"],
}


def _page_nodes(nodes):
    for node in nodes:
        yield node
        for child in node.get("children", []):
            yield child


PAGE_PERMISSION_CODES = [node["code"] for node in _page_nodes(PAGE_RULES)]
ACTION_PERMISSION_CODES = [
    f"{resource}:{action}"
    for resource, (_, actions) in ACTION_PERMISSION_DEFS.items()
    for action in actions
]
ALL_PERMISSION_CODES = PAGE_PERMISSION_CODES + ACTION_PERMISSION_CODES


def _action_permission_nodes():
    groups = []
    for resource, (label, actions) in ACTION_PERMISSION_DEFS.items():
        groups.append({
            "key": f"action:{resource}",
            "label": label,
            "type": "action-resource",
            "children": [
                {
                    "key": f"{resource}:{action}",
                    "code": f"{resource}:{action}",
                    "label": ACTION_LABELS.get(action, action),
                    "type": "action",
                }
                for action in actions
            ],
        })
    return groups


def _operation_nodes_for_page(page_code):
    resources = PAGE_OPERATION_BINDINGS.get(page_code, [])
    operations = []
    for resource in resources:
        if resource not in ACTION_PERMISSION_DEFS:
            continue
        resource_label, actions = ACTION_PERMISSION_DEFS[resource]
        for action in actions:
            code = f"{resource}:{action}"
            operations.append({
                "key": f"{page_code}:{code}",
                "code": code,
                "resource": resource,
                "action": action,
                "label": ACTION_LABELS.get(action, action),
                "resource_label": resource_label,
                "type": "action",
            })
    return operations


def _merged_page_node(page, parent_codes=None):
    parent_codes = parent_codes or []
    page_code = page["code"]
    children = [
        _merged_page_node(child, [*parent_codes, page_code])
        for child in page.get("children", [])
    ]
    return {
        "key": page_code,
        "code": page_code,
        "page": page.get("page", ""),
        "label": page["label"],
        "type": "module" if children else "page",
        "parent_codes": parent_codes,
        "operations": _operation_nodes_for_page(page_code),
        "children": children,
    }


def build_merged_permission_tree():
    return [_merged_page_node(page) for page in PAGE_RULES]


def build_permission_payload():
    permissions = [
        {
            "code": resource,
            "label": label,
            "actions": actions,
            "action_labels": [
                {
                    "code": f"{resource}:{action}",
                    "action": action,
                    "label": ACTION_LABELS.get(action, action),
                }
                for action in actions
            ],
        }
        for resource, (label, actions) in ACTION_PERMISSION_DEFS.items()
    ]
    tree = [
        {
            "key": "page-permissions",
            "label": "页面显示权限",
            "type": "group",
            "children": [
                {
                    **page,
                    "key": page["code"],
                    "type": "page",
                    "children": [
                        {**child, "key": child["code"], "type": "page"}
                        for child in page.get("children", [])
                    ],
                }
                for page in PAGE_RULES
            ],
        },
        {
            "key": "action-permissions",
            "label": "业务操作权限",
            "type": "group",
            "children": _action_permission_nodes(),
        },
    ]
    return {
        "tree": tree,
        "mergedTree": build_merged_permission_tree(),
        "permissions": permissions,
        "codes": ALL_PERMISSION_CODES,
        "pages": PAGE_RULES,
        "sidebar": SIDEBAR_ITEMS,
        "action_labels": ACTION_LABELS,
        "page_operation_bindings": PAGE_OPERATION_BINDINGS,
    }


def infer_page_permissions(permission_codes):
    """根据旧业务权限推导应补充的 page:* 权限，用于兼容老角色。"""
    codes = set(permission_codes or [])
    if "*" in codes:
        return []
    inferred = set()
    for code in codes:
        if not isinstance(code, str) or ":" not in code or code.startswith("page:"):
            continue
        resource = code.split(":", 1)[0]
        inferred.update(ACTION_PAGE_MAP.get(resource, []))
        if code == "users:admin":
            inferred.update(["page:settings", "page:settings.admin-users"])
    return [code for code in PAGE_PERMISSION_CODES if code in inferred]
