// ProductionSettings — 生产管理（8个子模块：订单/客户/物料/追溯/审批/排程/返工/质检）
import { ref, computed } from '../../vendor/vue.esm.js'

import OrderList      from '../orders/OrderList.js'
import CustomerList   from '../customers/CustomerList.js'
import MaterialList   from '../materials/MaterialList.js?v=75'
import TracePage      from '../trace/TracePage.js'
import ApprovalPage   from '../approvals/ApprovalPage.js'
import GanttChart     from '../schedule/GanttChart.js'
import ReworkList     from '../rework/ReworkList.js'
import InspectionList from '../quality/InspectionList.js'

export default {
  template: '#production-settings-template',
  components: { OrderList, CustomerList, MaterialList, TracePage, ApprovalPage, GanttChart, ReworkList, InspectionList },
  setup() {
    const tabs = [
      { key: 'orders',     label: '📋 订单管理',   component: 'OrderList' },
      { key: 'customers',  label: '🏢 客户管理',   component: 'CustomerList' },
      { key: 'materials',  label: '📦 物料管理',   component: 'MaterialList' },
      { key: 'trace',      label: '🔍 产品追溯',   component: 'TracePage' },
      { key: 'approvals',  label: '✅ 审批管理',   component: 'ApprovalPage' },
      { key: 'schedule',   label: '📅 生产排程',   component: 'GanttChart' },
      { key: 'rework',     label: '🔧 返工管理',   component: 'ReworkList' },
      { key: 'quality',    label: '🔎 质量检验',   component: 'InspectionList' },
    ]

    const STORAGE_KEY = 'productionTab'
    const activeTab = ref(localStorage.getItem(STORAGE_KEY) || 'orders')
    const loaded = ref({})

    function switchTab(key) {
      activeTab.value = key
      localStorage.setItem(STORAGE_KEY, key)
      loaded.value[key] = true
    }

    loaded.value[activeTab.value] = true

    return { tabs, activeTab, loaded, switchTab }
  }
}
