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
    "stock": "库存调整",
    "consume": "物料消耗",
    "export": "导出",
    "report": "报工",
    "serial_backfill": "序列号跨工序补报",
    "serial_backfill_approve": "序列号补报审批",
    "admin": "管理员",
    "audit": "审核",
    "submit": "提交评价",
    "review": "质量核验",
    "waive": "历史任务豁免",
    "waive_live": "生产中例外豁免",
    "stats": "统计分析",
    "rules": "规则配置",
    "inspect": "执行检验",
    "standards": "质量标准",
    "plans": "检验方案",
    "disposition": "不合格处置",
    "capa": "CAPA闭环",
    "supplier": "供应商质量",
    "calibration": "量具校准",
    "complete": "完成出库",
    "cancel": "取消/冲销",
    "receive": "签收",
    "finance": "收退款",
    "logistics": "物流维护",
    "unlinked": "无订单发货",
    "view_self": "查看本人工资",
    "view_all": "查看全部工资",
    "prepare": "工资制单",
    "approve": "工资审批",
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
    "shipments": (
        "发货",
        [
            "view", "create", "edit", "delete", "complete", "cancel",
            "receive", "finance", "logistics", "unlinked",
        ],
    ),
    "scan": (
        "扫码报工",
        ["view", "report", "serial_backfill", "serial_backfill_approve"],
    ),
    "stats": ("统计报表", ["view", "export"]),
    "trace": ("产品追溯", ["view"]),
    "approvals": ("审批", ["view", "create", "edit"]),
    "reports": ("数据分析", ["view"]),
    "board": ("数据看板", ["view"]),
    "settings": ("系统设置", ["manage", "edit"]),
    "logs": ("操作日志", ["view", "delete"]),
    "materials": ("物料", ["view", "create", "edit", "delete", "stock", "consume", "manage"]),
    "suppliers": ("供应商", ["view", "create", "edit", "delete"]),
    "quality": ("质量管理", ["view", "inspect", "standards", "plans", "disposition", "review", "capa", "supplier", "calibration", "edit", "delete"]),
    "rework": ("返工", ["view", "create", "edit"]),
    "schedule": ("生产排程", ["view", "edit"]),
    "wages": (
        "工资核算",
        ["view", "edit", "view_self", "view_all", "prepare", "approve", "export"],
    ),
    "performance": ("绩效量化", ["view", "create", "edit", "delete", "export"]),
    "work_time": ("工时管理", ["view", "create", "edit", "audit", "export"]),
    "process_quality_evaluation": (
        "工序质量评价",
        ["view", "submit", "review", "waive", "waive_live", "stats", "rules"],
    ),
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
    {"page": "performance", "code": "page:performance", "icon": "🎯", "label": "绩效管理"},
    {"page": "quality-management", "code": "page:quality-management", "icon": "🛡️", "label": "质量管理"},
    {"page": "process-quality-evaluation", "code": "page:process-quality-evaluation", "icon": "✅", "label": "工序质量评价"},
    {"page": "work-time", "code": "page:work-time", "icon": "⏱️", "label": "工时管理"},
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
        ],
    },
    {"page": "scan", "code": "page:scan", "label": "扫码报工"},
    {"page": "inventory", "code": "page:inventory", "label": "库存管理"},
    {"page": "shipments", "code": "page:shipments", "label": "发货管理"},
    {"page": "stats", "code": "page:stats", "label": "统计报表"},
    {"page": "reports", "code": "page:reports", "label": "数据分析"},
    {"page": "wages", "code": "page:wages", "label": "工资核算"},
    {"page": "performance", "code": "page:performance", "label": "绩效管理"},
    {"page": "quality-management", "code": "page:quality-management", "label": "质量管理"},
    {"page": "process-quality-evaluation", "code": "page:process-quality-evaluation", "label": "工序质量评价"},
    {"page": "work-time", "code": "page:work-time", "label": "工时管理"},
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
    "suppliers": ["page:production", "page:production.materials"],
    "trace": ["page:production", "page:production.trace"],
    "approvals": ["page:production", "page:production.approvals"],
    "schedule": ["page:production", "page:production.schedule"],
    "rework": ["page:production", "page:production.rework"],
    "quality": ["page:quality-management"],
    "scan": ["page:scan"],
    "inventory": ["page:inventory"],
    "shipments": ["page:shipments"],
    "stats": ["page:stats"],
    "reports": ["page:reports"],
    "wages": ["page:wages"],
    "performance": ["page:performance"],
    "process_quality_evaluation": ["page:process-quality-evaluation"],
    "work_time": ["page:work-time"],
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
    "page:production.materials": ["materials", "suppliers"],
    "page:production.trace": ["trace"],
    "page:production.approvals": ["approvals"],
    "page:production.schedule": ["schedule"],
    "page:production.rework": ["rework"],
    "page:quality-management": ["quality"],
    "page:scan": ["scan"],
    "page:inventory": ["inventory"],
    "page:shipments": ["shipments"],
    "page:stats": ["stats"],
    "page:reports": ["reports"],
    "page:wages": ["wages"],
    "page:performance": ["performance"],
    "page:process-quality-evaluation": ["process_quality_evaluation"],
    "page:work-time": ["work_time"],
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

PERMISSION_IMPLICATIONS = {
    "wages:view_self": ["wages:view"],
    "wages:view_all": ["wages:view"],
    "wages:prepare": ["wages:view", "wages:view_all"],
    "wages:approve": ["wages:view", "wages:view_all"],
    "wages:export": ["wages:view", "wages:view_all"],
    "quality:edit": ["quality:review"],
    "shipments:edit": [
        "shipments:complete",
        "shipments:cancel",
        "shipments:receive",
        "shipments:finance",
        "shipments:logistics",
    ],
    "shipments:delete": ["shipments:cancel"],
    "materials:manage": [
        "materials:view",
        "materials:create",
        "materials:edit",
        "materials:delete",
        "materials:stock",
        "materials:consume",
        "suppliers:view",
        "suppliers:create",
        "suppliers:edit",
        "suppliers:delete",
    ],
    "materials:view": ["suppliers:view"],
    "materials:create": ["materials:view", "suppliers:view"],
    "materials:edit": ["materials:view", "suppliers:view"],
    "materials:delete": ["materials:view"],
    "materials:stock": ["materials:view"],
    "materials:consume": ["materials:view"],
    "suppliers:view": ["materials:view"],
    "suppliers:create": ["materials:view", "suppliers:view"],
    "suppliers:edit": ["materials:view", "suppliers:view"],
    "suppliers:delete": ["materials:view", "suppliers:view"],
}


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

DEFAULT_ROLE_PERMISSION_ADDITIONS = {
    "production_manager": [
        "page:performance",
        "performance:view",
        "performance:create",
        "performance:edit",
        "performance:export",
        "page:process-quality-evaluation",
        "process_quality_evaluation:view",
        "process_quality_evaluation:review",
        "process_quality_evaluation:stats",
        "process_quality_evaluation:rules",
        "page:work-time",
        "work_time:view",
        "work_time:create",
        "work_time:edit",
        "work_time:audit",
        "work_time:export",
    ],
    "qc_inspector": [
        "page:performance",
        "performance:view",
        "page:process-quality-evaluation",
        "process_quality_evaluation:view",
        "process_quality_evaluation:review",
        "process_quality_evaluation:waive",
        "process_quality_evaluation:stats",
    ],
    "warehouse_keeper": ["page:performance", "performance:view"],
}


def default_role_permission_additions(role_code):
    permissions = DEFAULT_ROLE_PERMISSION_ADDITIONS.get(role_code, [])
    return list(dict.fromkeys(permissions + infer_page_permissions(permissions)))
