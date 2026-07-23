import {
  ACTION_PAGE_MAP,
  PAGE_RULE_TREE,
  SIDEBAR_ITEMS,
} from './permissionFallback.generated.js'

function flattenFallbackPageRules(nodes, parent = '') {
  const rules = {}
  for (const node of nodes || []) {
    if (!node?.page || !node?.code) continue
    rules[node.page] = {
      permission: node.code,
      label: node.label || node.page,
      parent: parent || undefined,
    }
    Object.assign(rules, flattenFallbackPageRules(node.children || [], node.page))
  }
  return rules
}

export { ACTION_PAGE_MAP, SIDEBAR_ITEMS }
export const PAGE_RULES = flattenFallbackPageRules(PAGE_RULE_TREE)

let runtimeSidebarItems = SIDEBAR_ITEMS
let runtimePageRules = PAGE_RULES
let runtimeActionPageMap = ACTION_PAGE_MAP

const IMPLIED_PERMISSIONS = {
  'quality:edit': ['quality:review'],
}

function flattenPageRules(nodes, parent = '') {
  const rules = {}
  for (const node of nodes || []) {
    if (!node?.page || !node?.code) continue
    rules[node.page] = {
      permission: node.code,
      label: node.label || node.page,
      parent: parent || undefined,
    }
    Object.assign(rules, flattenPageRules(node.children || [], node.page))
  }
  return rules
}

function collectParentCodes(nodes, parentCodes = [], result = {}) {
  for (const node of nodes || []) {
    if (!node?.code) continue
    result[node.code] = parentCodes
    collectParentCodes(node.children || [], [...parentCodes, node.code], result)
  }
  return result
}

function buildActionPageMap(pages, bindings) {
  const parentCodes = collectParentCodes(pages)
  const nextMap = { ...ACTION_PAGE_MAP }
  for (const [pageCode, resources] of Object.entries(bindings || {})) {
    for (const resource of resources || []) {
      const codes = new Set(nextMap[resource] || [])
      for (const parentCode of parentCodes[pageCode] || []) codes.add(parentCode)
      codes.add(pageCode)
      nextMap[resource] = Array.from(codes)
    }
  }
  return nextMap
}

export function applyPermissionCatalog(payload = {}) {
  const pages = Array.isArray(payload.pages) ? payload.pages : []
  const sidebar = Array.isArray(payload.sidebar) ? payload.sidebar : []
  if (pages.length) {
    runtimePageRules = { ...PAGE_RULES, ...flattenPageRules(pages) }
    runtimeActionPageMap = buildActionPageMap(pages, payload.page_operation_bindings || {})
  }
  if (sidebar.length) {
    runtimeSidebarItems = sidebar
      .filter(item => item?.page && item?.code)
      .map(item => ({
        page: item.page,
        icon: item.icon || '',
        label: item.label || item.page,
        permission: item.code,
      }))
  }
}

export function resetPermissionCatalog() {
  runtimeSidebarItems = SIDEBAR_ITEMS
  runtimePageRules = PAGE_RULES
  runtimeActionPageMap = ACTION_PAGE_MAP
}

export function getSidebarItems() {
  return runtimeSidebarItems
}

export function getPermissionList(user) {
  return Array.isArray(user?.permissions) ? user.permissions : []
}

export function hasPermission(user, permission) {
  if (!permission) return true
  const permissions = getPermissionList(user)
  if (permissions.includes('*') || permissions.includes(permission)) return true
  return permissions.some(granted => (IMPLIED_PERMISSIONS[granted] || []).includes(permission))
}

export function hasAnyPermission(user, permissions) {
  if (!permissions || permissions.length === 0) return true
  return permissions.some(permission => hasPermission(user, permission))
}

export function canOpenPage(user, page) {
  if (!page || page === 'login') return true
  const rule = runtimePageRules[page]
  if (!rule) return false
  return hasPermission(user, rule.permission)
}

export function getLandingPage(user) {
  const item = getSidebarItems().find(sidebarItem => canOpenPage(user, sidebarItem.page))
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
  for (const [granted, implied] of Object.entries(IMPLIED_PERMISSIONS)) {
    if (!normalized.has(granted)) continue
    implied.forEach(code => normalized.add(code))
  }
  for (const code of codes) {
    if (typeof code !== 'string' || code.startsWith('page:') || !code.includes(':')) continue
    const [resource] = code.split(':')
    for (const pageCode of runtimeActionPageMap[resource] || []) {
      normalized.add(pageCode)
    }
    if (code === 'users:admin') {
      normalized.add('page:settings')
      normalized.add('page:settings.admin-users')
    }
  }
  return Array.from(normalized)
}
