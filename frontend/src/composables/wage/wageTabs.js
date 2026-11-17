const WAGE_TAB_DEFINITIONS_SOURCE = [
  { id: 'ledger', label: '批次台账', group: '核算', permissions: ['wages:view_all', 'wages:prepare', 'wages:approve'] },
  { id: 'settlement', label: '导出对账', group: '结算', permissions: ['wages:view_all', 'wages:export', 'wages:receipt', 'wages:reconcile', 'wages:close'] },
  { id: 'exceptions', label: '异常处理', group: '核算', permissions: ['wages:view_all', 'wages:prepare', 'wages:approve'] },
  { id: 'adjustment', label: '调整项', group: '核算', permissions: ['wages:view_all', 'wages:prepare', 'wages:approve'] },
  { id: 'priceversions', label: '工价版本', group: '核算', permissions: ['wages:prepare', 'wages:approve'] },
  { id: 'my', label: '我的工资', group: '查询', permissions: ['wages:view_self', 'wages:view_all', 'wages:prepare', 'wages:approve'] },
  { id: 'piece', label: '实时预估', group: '查询', permissions: ['wages:view'] },
  { id: 'monthly', label: '月度汇总', group: '分析', icon: '📊', permissions: ['wages:view_all'] },
  { id: 'process', label: '工序分析', group: '分析', icon: '🔧', permissions: ['wages:view_all'] },
  { id: 'compare', label: '工资对比', group: '分析', icon: '📈', permissions: ['wages:view_all'] },
  { id: 'trend', label: '历史趋势', group: '分析', icon: '📈', permissions: ['wages:view_all'] },
  { id: 'position', label: '岗位汇总', group: '分析', icon: '👥', permissions: ['wages:view_all'] },
  { id: 'predict', label: '工资预测', group: '分析', icon: '🔮', permissions: ['wages:view_all'] },
]

export const WAGE_TAB_DEFINITIONS = Object.freeze(
  WAGE_TAB_DEFINITIONS_SOURCE.map(tab => Object.freeze(tab))
)

export function getVisibleWageTabs(canPermission) {
  return WAGE_TAB_DEFINITIONS
    .filter(tab => tab.permissions.some(permission => canPermission(permission)))
    .map(tab => ({ ...tab }))
}

export function resolveWageTab(requestedTab, storedTab, visibleTabs) {
  const allowed = new Set(visibleTabs.map(tab => tab.id))
  if (allowed.has(requestedTab)) return requestedTab
  if (allowed.has(storedTab)) return storedTab
  return ['ledger', 'settlement', 'exceptions', 'my', 'piece']
    .find(tabId => allowed.has(tabId)) || visibleTabs[0]?.id || 'my'
}
