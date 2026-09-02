<!-- AdminUsers.vue -->
<template>
<div>
    <div>
      <div class="account-mode-tabs" role="tablist" aria-label="账号类型">
        <button type="button" :class="['account-mode-tab', { active: accountMode==='admin' }]" @click="setAccountMode('admin')">系统管理员</button>
        <button type="button" :class="['account-mode-tab', { active: accountMode==='service' }]" @click="setAccountMode('service')">业务专用账号</button>
      </div>
      <div class="summary-bar" style="margin-bottom:var(--space-4)">
        <div class="summary-item"><span class="s-icon">👥</span><div><div class="s-val">{{ systemAdminList.length }}</div><div class="s-label">系统管理员</div></div></div>
        <div class="summary-item"><span class="s-icon">🔐</span><div><div class="s-val">{{ serviceAccountList.length }}</div><div class="s-label">业务专用账号</div></div></div>
        <div class="summary-item"><span class="s-icon">✅</span><div><div class="s-val text-success">{{ currentAccountList.filter(u=>u.status==='active').length }}</div><div class="s-label">当前启用</div></div></div>
        <div class="summary-item"><span class="s-icon">⛔</span><div><div class="s-val text-warning">{{ currentAccountList.filter(u=>u.status!=='active').length }}</div><div class="s-label">当前停用/删除</div></div></div>
      </div>
      <div class="card">
        <div class="card-header">
          <div><h3>{{ accountMode==='admin' ? '系统管理员' : '业务专用账号' }}</h3></div>
          <div style="display:flex;gap:var(--space-2);align-items:center">
            <input class="form-input" v-model="adminSearch" placeholder="🔍 搜索..." style="width:160px;padding:6px 10px;font-size:var(--text-sm)">
            <button class="btn btn-default btn-sm" @click="loadAllUsers">🔄</button>
            <button v-if="accountMode==='admin'" class="btn btn-primary btn-sm" @click="openAddAdmin">+ 添加管理员</button>
            <button v-if="accountMode==='service' && selectedAdmins.length" class="btn btn-danger btn-sm" @click="batchDeleteAdmins">🗑️ 删除({{ selectedAdmins.length }})</button>
          </div>
        </div>
        <div class="card-body">
          <div v-if="adminLoading" style="text-align:center;padding:40px;color:var(--text-placeholder)">⏳ 加载中...</div>
          <div v-else>
            <div v-if="filteredAdminList.length" class="table-wrap">
              <table class="data-table">
                <thead><tr>
                  <th style="width:36px;text-align:center"><input v-if="accountMode==='service'" type="checkbox" :checked="isAllSelected" @change="toggleSelectAllAdmins"></th>
                  <th style="width:40px;text-align:center">#</th>
                  <th>用户名</th><th>账号类型</th><th>角色</th><th>权限</th><th>昵称</th><th>所属组别</th><th>电子邮箱</th><th>手机号</th><th style="width:70px">工号</th><th style="width:80px">状态</th><th>最后登录</th><th style="width:80px;text-align:center;white-space:nowrap">操作</th>
                </tr></thead>
                <tbody>
                  <tr v-for="(u, idx) in filteredAdminList" :key="u.id">
                    <td style="text-align:center"><input v-if="!u.is_admin_user" type="checkbox" :value="u.id" v-model="selectedAdmins" :disabled="u.status==='deleted'"></td>
                    <td style="text-align:center"><span class="badge" style="background:var(--primary-light);color:var(--primary-dark);min-width:28px;text-align:center">{{ idx+1 }}</span></td>
                    <td style="font-weight:500">{{ u.username }}</td>
                    <td><span class="badge" :class="u.is_admin_user?'danger':'pending'">{{ u.is_admin_user ? '系统管理员' : '专用账号' }}</span></td>
                    <td><div class="role-badges"><span v-for="role in userRoleNames(u)" :key="role" class="role-badge">{{ role }}</span></div></td>
                    <td><span class="permission-count">{{ userPermissionSummary(u) }}</span></td>
                    <td>{{ u.nickname || u.name || '-' }}</td>
                    <td><span class="group-tag">{{ u.group_name || '-' }}</span></td>
                    <td style="color:var(--text-placeholder)">{{ u.email || '-' }}</td>
                    <td>{{ u.phone || '-' }}</td>
                    <td>{{ u.employee_no || '-' }}</td>
                    <td><span class="badge" :class="u.status==='active'?'completed':u.status==='deleted'?'danger':'pending'">{{ u.status==='active'?'正常':u.status==='deleted'?(u.purged_at?'已匿名化':'已删除'):'停用' }}</span></td>
                    <td style="font-size:var(--text-xs);color:var(--text-placeholder)">{{ u.last_active || '无' }}</td>
                    <td style="text-align:center;white-space:nowrap">
                      <button v-if="u.status!=='deleted'" class="o-abtn edit" @click="openEditAdmin(u)">✏️</button>
                      <button v-if="u.status==='deleted' && !u.purged_at" class="o-abtn" style="background:var(--success-light);color:var(--success)" @click="restoreAdminUser(u.id)" title="恢复">🔄</button>
                      <button v-if="u.status==='deleted' && !u.purged_at" class="o-abtn" style="background:var(--danger-light);color:var(--danger)" @click="permanentDeleteAdminUser(u.id)" title="匿名化身份">◉</button>
                      <button v-if="u.status!=='deleted'" class="o-abtn del" @click="deleteAdminUser(u)">🗑️</button>
                    </td>
                  </tr>
                </tbody>
              </table>
            </div>
            <div v-else class="empty"><div class="empty-text">{{ accountMode==='admin' ? '暂无系统管理员' : '暂无业务专用账号' }}</div></div>
          </div>
        </div>
      </div>
    </div>

    <!-- Admin Add/Edit Modal -->
    <div v-if="showAdminModal" class="modal-overlay" >
      <div class="modal" style="max-width:520px">
        <div class="modal-header"><span>{{ adminModalEdit ? (accountMode==='admin' ? '编辑系统管理员' : '编辑业务专用账号') : '新增系统管理员' }}</span><span class="modal-close" @click="showAdminModal=false">&times;</span></div>
        <div class="modal-body">
          <div class="form-group"><label>用户名 *</label><input class="form-input" v-model="adminForm.username" :disabled="adminModalEdit"></div>
          <div class="form-group"><label>姓名 *</label><input class="form-input" v-model="adminForm.name"></div>
          <div class="form-group"><label>昵称</label><input class="form-input" v-model="adminForm.nickname"></div>
          <div class="form-group"><label>所属组别</label>
            <select class="form-input" v-model="adminForm.group_name">
              <option value="">— 选择角色组 —</option>
              <option v-for="g in roleGroups" :key="g.id" :value="g.name">{{ g.name }}</option>
            </select>
          </div>
          <div class="form-group"><label>状态</label><select class="form-input" v-model="adminForm.status"><option value="active">启用</option><option value="inactive">停用</option></select></div>
          <div class="form-group"><label>{{ adminModalEdit ? '新密码（留空不修改）' : '密码' }}</label><input class="form-input" v-model="adminForm.password" type="password"></div>
          <div class="form-group"><label>电子邮箱</label><input class="form-input" v-model="adminForm.email"></div>
          <div class="form-group"><label>手机号</label><input class="form-input" v-model="adminForm.phone"></div>
          <div class="form-group"><label>工号</label><input class="form-input" v-model="adminForm.employee_no"></div>
          <div v-if="adminModalEdit" class="form-group">
            <label>角色分配</label>
            <div style="display:flex;flex-wrap:wrap;gap:var(--space-2);margin-top:6px;max-height:180px;overflow-y:auto">
              <label v-for="r in allRoles" :key="r.id" style="display:flex;align-items:center;gap:var(--space-1);padding:var(--space-1) 10px;background:var(--bg-table-header);border:1px solid var(--border-light);border-radius:var(--radius-sm);cursor:pointer;font-size:var(--text-sm);user-select:none">
                <input type="checkbox" :value="r.id" @change="toggleUserRole(r.id)" :checked="userRoleIds.includes(r.id)" style="accent-color:var(--primary);margin:0">
                {{ r.name }}
                <span style="font-size:var(--text-2xs);color:var(--text-placeholder)">({{ r.group_name || '无组' }})</span>
              </label>
              <span v-if="!allRoles.length" style="color:var(--text-placeholder);font-size:var(--text-xs)">暂无角色</span>
            </div>
          </div>
        </div>
        <div class="modal-footer">
          <button class="btn btn-default" @click="showAdminModal=false">取消</button>
          <button class="btn btn-primary" @click="saveAdmin">💾 保存</button>
        </div>
      </div>
    </div>
</div>
</template>

<script>
import { useAdminUsers } from '@/composables/settings/useAdminUsers.js'

export default {
  setup() {
    return useAdminUsers()
  }
}
</script>

<style scoped>
.account-mode-tabs {
  display: inline-flex;
  gap: 2px;
  margin-bottom: var(--space-3);
  padding: 2px;
  border: 1px solid var(--border-light);
  border-radius: var(--radius-sm);
  background: var(--bg-table-header);
}

.account-mode-tab {
  min-height: 34px;
  padding: 0 14px;
  border: 0;
  border-radius: calc(var(--radius-sm) - 1px);
  background: transparent;
  color: var(--text-secondary);
  cursor: pointer;
  font-size: var(--text-sm);
}

.account-mode-tab.active {
  background: var(--bg-card);
  color: var(--primary);
  box-shadow: 0 1px 2px rgb(0 0 0 / 10%);
  font-weight: 600;
}

.role-badges {
  display: flex;
  flex-wrap: wrap;
  gap: 4px;
  min-width: 120px;
}

.role-badge,
.permission-count {
  display: inline-block;
  padding: 2px 6px;
  border-radius: var(--radius-sm);
  background: var(--bg-table-header);
  color: var(--text-secondary);
  font-size: var(--text-xs);
  white-space: nowrap;
}
</style>
