<template>
  <section class="scope-grid">
    <div class="card scope-users-card">
      <div class="card-header"><h3>授权用户</h3></div>
      <div class="card-body"><input v-model="search" class="form-input" placeholder="搜索姓名或工号"><div class="scope-user-list"><button v-for="user in filteredUsers" :key="user.id" class="scope-user" :class="{active:Number(user.id)===Number(selectedUserId)}" @click="$emit('select-user', user.id)"><strong>{{ user.name || user.username }}</strong><span>{{ user.employee_no || user.username || '-' }}</span></button><p v-if="!filteredUsers.length" class="empty">暂无用户。</p></div></div>
    </div>
    <div class="card scope-departments-card">
      <div class="card-header"><div><h3>部门数据范围</h3><p>只限定部门历史快照的可见与复核范围。</p></div><button class="btn btn-primary btn-sm" :disabled="!selectedUserId" @click="$emit('save', localDepartmentIds)">保存范围</button></div>
      <div class="card-body department-checks"><label v-for="department in departments" :key="department.id"><input v-model="localDepartmentIds" type="checkbox" :value="Number(department.id)"><span><strong>{{ department.name }}</strong><small>{{ department.status === 'inactive' ? '停用' : '在用' }}</small></span></label><p v-if="!departments.length" class="empty">暂无部门数据。</p></div>
      <div class="scope-foot">角色与绩效动作权限由角色管理维护，本页不做修改。</div>
    </div>
  </section>
</template>

<script>
export default {
  props: { users: { type: Array, default: () => [] }, departments: { type: Array, default: () => [] }, selectedUserId: { type: [Number, String], default: null }, departmentIds: { type: Array, default: () => [] } },
  emits: ['select-user', 'save'],
  data() { return { search: '', localDepartmentIds: [...this.departmentIds].map(Number) } },
  computed: { filteredUsers() { const term = this.search.trim().toLowerCase(); if (!term) return this.users; return this.users.filter(user => `${user.name || ''} ${user.username || ''} ${user.employee_no || ''}`.toLowerCase().includes(term)) } },
  watch: { departmentIds: { deep: true, handler(value) { this.localDepartmentIds = [...value].map(Number) } } },
}
</script>

<style scoped>
.scope-grid{display:grid;grid-template-columns:minmax(240px,340px) minmax(0,1fr);gap:var(--space-4)}.scope-grid>.card{margin:0}.scope-users-card .card-body{display:grid;gap:10px}.scope-user-list{display:grid;gap:4px;max-height:520px;overflow:auto}.scope-user{display:flex;justify-content:space-between;gap:10px;width:100%;padding:9px 10px;border:1px solid transparent;border-radius:var(--radius-md);background:transparent;text-align:left;cursor:pointer}.scope-user:hover{background:var(--bg-hover)}.scope-user.active{border-color:var(--primary);background:var(--primary-light);color:var(--primary)}.scope-user span{color:var(--text-placeholder);font-size:var(--text-xs-alt)}.scope-departments-card .card-header h3{margin:0}.scope-departments-card .card-header p{margin:4px 0 0;color:var(--text-placeholder);font-size:var(--text-xs-alt)}.department-checks{display:grid;grid-template-columns:repeat(auto-fill,minmax(180px,1fr));gap:8px}.department-checks label{display:flex;align-items:center;gap:9px;padding:10px;border:1px solid var(--border-light);border-radius:var(--radius-md)}.department-checks input{width:17px;height:17px}.department-checks strong,.department-checks small{display:block}.department-checks small{color:var(--text-placeholder);margin-top:2px}.scope-foot{padding:10px 16px;border-top:1px solid var(--border-light);color:var(--text-placeholder);font-size:var(--text-xs-alt)}
@media(max-width:760px){.scope-grid{grid-template-columns:1fr}.scope-user-list{max-height:260px}.department-checks{grid-template-columns:1fr}}
</style>
