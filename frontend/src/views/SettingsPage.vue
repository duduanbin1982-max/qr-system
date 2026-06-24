<!-- SettingsPage.vue — Lightweight Tab Controller -->
<template>
<div style="padding:var(--space-6)">
    <div class="card"><div class="card-header"><h3>&#x2699;&#xFE0F; &#x7CFB;&#x7EDF;&#x8BBE;&#x7F6E;</h3></div></div>
    <!-- Tab bar -->
    <div style="display:flex;gap:var(--space-1);margin-bottom:var(--space-5);border-bottom:2px solid var(--border-light);padding-bottom:0;overflow-x:auto">
      <button v-for="t in tabs" :key="t.key"
        class="tab-btn" :class="{active: activeTab===t.key}"
        @click="activeTab=t.key">
        {{ t.label }}
      </button>
    </div>

    <!-- Dynamic tab content -->
    <div v-if="!tabs.length" class="card"><div class="card-body">当前角色没有系统设置子页面权限。</div></div>
    <component v-else :is="currentComponent" />
  </div>
</template>

<script>
import { ref, computed, watchEffect } from 'vue'
import { auth } from '@/lib/auth.js'
import { filterAllowedTabs } from '@/lib/permissions.js'
import CompanyInfo    from './settings/CompanyInfo.vue'
import AdminUsers     from './settings/AdminUsers.vue'
import AuditLogs      from './settings/AuditLogs.vue'
import ProcessConfig  from './settings/ProcessConfig.vue'
import RoleGroups     from './settings/RoleGroups.vue'
import RoleManage     from './settings/RoleManage.vue'
import Positions      from './settings/Positions.vue'
import ApprovalConfig from './settings/ApprovalConfig.vue'

export default {
  components: { CompanyInfo, AdminUsers, AuditLogs, ProcessConfig, RoleGroups, RoleManage, Positions, ApprovalConfig },
  setup() {
    const allTabs = [
      { key:'company-info',    page:'company-info',    label:'\u{1F3E2} \u516C\u53F8\u8D44\u6599',   component: 'CompanyInfo' },
      { key:'admin-users',     page:'admin-users',     label:'\u{1F465} \u7BA1\u7406\u5458\u7BA1\u7406', component: 'AdminUsers' },
      { key:'audit-logs',      page:'audit-logs',      label:'\u{1F4CB} \u64CD\u4F5C\u65E5\u5FD7',     component: 'AuditLogs' },
      { key:'process-config',  page:'process-config',  label:'\u2699\uFE0F \u5DE5\u827A\u7BA1\u7406',   component: 'ProcessConfig' },
      { key:'role-groups',     page:'role-groups',     label:'\u{1F454} \u89D2\u8272\u7EC4',           component: 'RoleGroups' },
      { key:'role-manage',     page:'role-manage',     label:'\u{1F465} \u89D2\u8272\u7BA1\u7406',     component: 'RoleManage' },
      { key:'positions',       page:'positions',       label:'\u{1F4BC} \u5C97\u4F4D\u7BA1\u7406',     component: 'Positions' },
      { key:'approval-config', page:'approval-config', label:'\u2705 \u5BA1\u6279\u914D\u7F6E',         component: 'ApprovalConfig' },
    ]
    const tabs = computed(() => filterAllowedTabs(allTabs, auth.user))

    const STORAGE_KEY = 'settingsTab'
    const activeTab = ref(localStorage.getItem(STORAGE_KEY) || 'company-info')

    watchEffect(() => {
      if (!tabs.value.length) {
        activeTab.value = ''
        return
      }
      if (!tabs.value.some(t => t.key === activeTab.value)) {
        activeTab.value = tabs.value[0].key
      }
      localStorage.setItem(STORAGE_KEY, activeTab.value)
    })

    const currentComponent = computed(() => {
      const t = tabs.value.find(t => t.key === activeTab.value)
      return t ? t.component : 'CompanyInfo'
    })

    return { tabs, activeTab, currentComponent }
  }
}
</script>
