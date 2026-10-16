<!-- SettingsPage.vue — Lightweight Tab Controller -->
<template>
<div style="padding:var(--space-6)">
    <div class="card"><div class="card-header"><h3>&#x2699;&#xFE0F; &#x7CFB;&#x7EDF;&#x8BBE;&#x7F6E;</h3></div></div>
    <!-- Tab bar -->
    <div style="display:flex;gap:var(--space-1);margin-bottom:var(--space-5);border-bottom:2px solid var(--border-light);padding-bottom:0;overflow-x:auto">
      <button v-for="t in tabs" :key="t.key"
        class="tab-btn" :class="{active: activeTab===t.key}"
        @click="changeTab(t.key)">
        {{ t.label }}
      </button>
    </div>

    <!-- Dynamic tab content -->
    <div v-if="!tabs.length" class="card"><div class="card-body">当前角色没有系统设置子页面权限。</div></div>
    <component v-else ref="activeComponent" :is="currentComponent" />
  </div>
</template>

<script>
import CompanyInfo    from './settings/CompanyInfo.vue'
import AdminUsers     from './settings/AdminUsers.vue'
import AuditLogs      from './settings/AuditLogs.vue'
import ProcessConfig  from './settings/ProcessConfig.vue'
import RoleGroups     from './settings/RoleGroups.vue'
import RoleManage     from './settings/RoleManage.vue'
import Positions      from './settings/Positions.vue'
import ApprovalConfig from './settings/ApprovalConfig.vue'
import { useSettingsWorkspace } from '@/composables/settings/useSettingsWorkspace.js'

export default {
  components: { CompanyInfo, AdminUsers, AuditLogs, ProcessConfig, RoleGroups, RoleManage, Positions, ApprovalConfig },
  setup() {
    return useSettingsWorkspace()
  }
}
</script>
