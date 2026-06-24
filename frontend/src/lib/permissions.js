export const SIDEBAR_ITEMS = [
  { page: 'dashboard', icon: '📊', label: '工作台', permission: 'page:dashboard' },
  { page: 'production', icon: '🏭', label: '生产管理', permission: 'page:production' },
  { page: 'scan', icon: '📱', label: '扫码报工', permission: 'page:scan' },
  { page: 'inventory', icon: '🏗️', label: '库存管理', permission: 'page:inventory' },
  { page: 'shipments', icon: '🚚', label: '发货管理', permission: 'page:shipments' },
  { page: 'stats', icon: '📈', label: '统计报表', permission: 'page:stats' },
  { page: 'reports', icon: '📊', label: '数据分析', permission: 'page:reports' },
  { page: 'wages', icon: '💰', label: '工资核算', permission: 'page:wages' },
  { page: 'basic-settings', icon: '⚙️', label: '基础设置', permission: 'page:basic-settings' },
  { page: 'settings', icon: '⚙️', label: '系统设置', permission: 'page:settings' },
]

export const PAGE_RULES = {
  dashboard: { permission: 'page:dashboard', label: '工作台' },
  production: { permission: 'page:production', label: '生产管理' },
  orders: { permission: 'page:production.orders', label: '订单管理', parent: 'production' },
  customers: { permission: 'page:production.customers', label: '客户管理', parent: 'production' },
  materials: { permission: 'page:production.materials', label: '物料管理', parent: 'production' },
  trace: { permission: 'page:production.trace', label: '产品追溯', parent: 'production' },
  approvals: { permission: 'page:production.approvals', label: '审批管理', parent: 'production' },
  schedule: { permission: 'page:production.schedule', label: '生产排程', parent: 'production' },
  rework: { permission: 'page:production.rework', label: '返工管理', parent: 'production' },
  quality: { permission: 'page:production.quality', label: '质量检验', parent: 'production' },
  scan: { permission: 'page:scan', label: '扫码报工' },
  inventory: { permission: 'page:inventory', label: '库存管理' },
  shipments: { permission: 'page:shipments', label: '发货管理' },
  stats: { permission: 'page:stats', label: '统计报表' },
  reports: { permission: 'page:reports', label: '数据分析' },
  wages: { permission: 'page:wages', label: '工资核算' },
  board: { permission: 'page:board', label: '数据看板' },
  'basic-settings': { permission: 'page:basic-settings', label: '基础设置' },
  users: { permission: 'page:basic-settings.users', label: '员工管理', parent: 'basic-settings' },
  processes: { permission: 'page:basic-settings.processes', label: '工序管理', parent: 'basic-settings' },
  routes: { permission: 'page:basic-settings.routes', label: '工序路线', parent: 'basic-settings' },
  prices: { permission: 'page:basic-settings.prices', label: '工价管理', parent: 'basic-settings' },
  products: { permission: 'page:basic-settings.products', label: '产品管理', parent: 'basic-settings' },
  'all-products': { permission: 'page:basic-settings.products', label: '产品管理', parent: 'basic-settings' },
  'structure-products': { permission: 'page:basic-settings.products', label: '产品管理', parent: 'basic-settings' },
  'machining-products': { permission: 'page:basic-settings.products', label: '产品管理', parent: 'basic-settings' },
  'all-processes': { permission: 'page:basic-settings.processes', label: '工序管理', parent: 'basic-settings' },
  'structure-processes': { permission: 'page:basic-settings.processes', label: '工序管理', parent: 'basic-settings' },
  'machining-processes': { permission: 'page:basic-settings.processes', label: '工序管理', parent: 'basic-settings' },
  'all-prices': { permission: 'page:basic-settings.prices', label: '工价管理', parent: 'basic-settings' },
  'structure-prices': { permission: 'page:basic-settings.prices', label: '工价管理', parent: 'basic-settings' },
  'machining-prices': { permission: 'page:basic-settings.prices', label: '工价管理', parent: 'basic-settings' },
  settings: { permission: 'page:settings', label: '系统设置' },
  'company-info': { permission: 'page:settings.company-info', label: '公司资料', parent: 'settings' },
  'admin-users': { permission: 'page:settings.admin-users', label: '管理员管理', parent: 'settings' },
  'audit-logs': { permission: 'page:settings.audit-logs', label: '操作日志', parent: 'settings' },
  'process-config': { permission: 'page:settings.process-config', label: '工艺管理', parent: 'settings' },
  'role-groups': { permission: 'page:settings.role-groups', label: '角色组', parent: 'settings' },
  'role-manage': { permission: 'page:settings.role-manage', label: '角色管理', parent: 'settings' },
  positions: { permission: 'page:settings.positions', label: '岗位管理', parent: 'settings' },
  'approval-config': { permission: 'page:settings.approval-config', label: '审批配置', parent: 'settings' },
}

export const ACTION_PAGE_MAP = {
  dashboard: ['page:dashboard'],
  orders: ['page:production', 'page:production.orders'],
  customers: ['page:production', 'page:production.customers'],
  materials: ['page:production', 'page:production.materials'],
  trace: ['page:production', 'page:production.trace'],
  approvals: ['page:production', 'page:production.approvals'],
  schedule: ['page:production', 'page:production.schedule'],
  rework: ['page:production', 'page:production.rework'],
  quality: ['page:production', 'page:production.quality'],
  scan: ['page:scan'],
  inventory: ['page:inventory'],
  shipments: ['page:shipments'],
  stats: ['page:stats'],
  reports: ['page:reports'],
  wages: ['page:wages'],
  board: ['page:board'],
  users: ['page:basic-settings', 'page:basic-settings.users'],
  processes: ['page:basic-settings', 'page:basic-settings.processes'],
  routes: ['page:basic-settings', 'page:basic-settings.routes'],
  prices: ['page:basic-settings', 'page:basic-settings.prices'],
  products: ['page:basic-settings', 'page:basic-settings.products'],
  roles: ['page:settings', 'page:settings.role-manage'],
  role_groups: ['page:settings', 'page:settings.role-groups'],
  positions: ['page:settings', 'page:settings.positions'],
  logs: ['page:settings', 'page:settings.audit-logs'],
  settings: [
    'page:settings',
    'page:settings.company-info',
    'page:settings.admin-users',
    'page:settings.audit-logs',
    'page:settings.process-config',
    'page:settings.role-groups',
    'page:settings.role-manage',
    'page:settings.positions',
    'page:settings.approval-config',
  ],
}

export function getPermissionList(user) {
  return Array.isArray(user?.permissions) ? user.permissions : []
}

export function hasPermission(user, permission) {
  if (!permission) return true
  const permissions = getPermissionList(user)
  return permissions.includes('*') || permissions.includes(permission)
}

export function hasAnyPermission(user, permissions) {
  if (!permissions || permissions.length === 0) return true
  return permissions.some(permission => hasPermission(user, permission))
}

export function canOpenPage(user, page) {
  if (!page || page === 'login') return true
  const rule = PAGE_RULES[page]
  if (!rule) return false
  return hasPermission(user, rule.permission)
}

export function getLandingPage(user) {
  const item = SIDEBAR_ITEMS.find(sidebarItem => canOpenPage(user, sidebarItem.page))
  return item?.page || 'no-permission'
}

export function filterAllowedTabs(tabs, user) {
  return tabs.filter(tab => canOpenPage(user, tab.page || tab.key))
}

export function firstAllowedTab(tabs, user) {
  return filterAllowedTabs(tabs, user)[0]?.key || ''
}

export function normalizeRolePermissions(codes) {
  if (!Array.isArray(codes)) return []
  if (codes.includes('*')) return ['*']
  const normalized = new Set(codes.filter(Boolean))
  for (const code of codes) {
    if (typeof code !== 'string' || code.startsWith('page:') || !code.includes(':')) continue
    const [resource] = code.split(':')
    for (const pageCode of ACTION_PAGE_MAP[resource] || []) {
      normalized.add(pageCode)
    }
    if (code === 'users:admin') {
      normalized.add('page:settings')
      normalized.add('page:settings.admin-users')
    }
  }
  return Array.from(normalized)
}
