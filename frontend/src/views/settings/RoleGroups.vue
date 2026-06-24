<!-- RoleGroups.vue -->
<template>
<div>
    <div>
      <div class="card">
        <div class="card-header">
          <h3>👔 角色组管理</h3>
          <button class="btn btn-primary btn-sm" @click="openAddGroup">+ 新增角色组</button>
        </div>
        <div class="card-body">
          <div v-if="groupLoading" style="text-align:center;padding:40px;color:var(--text-placeholder)">⏳ 加载中...</div>
          <div v-else>
            <div v-if="groups.length" class="table-wrap">
              <table class="data-table">
                <thead><tr><th style="width:40px;text-align:center">#</th><th>名称</th><th>描述</th><th style="width:80px">状态</th><th style="width:120px;text-align:center">操作</th></tr></thead>
                <tbody>
                  <template v-for="(g, idx) in groups" :key="g.id">
                    <tr @click="toggleGroup(g.id)" style="cursor:pointer">
                      <td style="text-align:center"><span class="badge" style="background:var(--primary-light);color:var(--primary-dark);min-width:28px;text-align:center">{{ idx+1 }}</span></td>
                      <td style="font-weight:500">{{ g.name }} <span style="font-size:var(--text-xs-alt);color:var(--text-placeholder)">({{ roleCountByGroup[g.id] || 0 }} 个角色)</span></td>
                      <td style="color:var(--text-placeholder)">{{ g.description || '-' }}</td>
                      <td><span class="badge" :class="g.status==='active'?'completed':'pending'">{{ g.status==='active'?'启用':'停用' }}</span></td>
                      <td style="text-align:center" @click.stop>
                        <button class="o-abtn edit" @click="openEditGroup(g)">✏️</button>
                        <button v-if="canDeleteGroup(g.id)" class="o-abtn del" @click="deleteGroup(g.id)" title="删除">🗑️</button>
                      </td>
                    </tr>
                    <tr v-if="expandedGroup===g.id">
                      <td :colspan="5" style="padding:0;background:var(--bg-input)">
                        <div style="padding:var(--space-3) 20px">
                          <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:var(--space-2)">
                            <span style="font-weight:600;font-size:var(--text-sm)">角色列表（只读）</span>
                            <span style="font-size:var(--text-xs);color:var(--text-placeholder)">编辑角色请切换到"角色管理"标签页</span>
                          </div>
                          <table v-if="groupRoles.length" class="data-table" style="background:white">
                            <thead><tr><th style="width:40px;text-align:center">#</th><th>名称</th><th>编码</th><th style="width:80px">级别</th><th style="width:80px">状态</th></tr></thead>
                            <tbody>
                              <tr v-for="(r, ri) in groupRoles" :key="r.id">
                                <td style="text-align:center"><span class="badge" style="background:var(--primary-light);color:var(--primary-dark);min-width:28px;text-align:center">{{ ri+1 }}</span></td>
                                <td style="font-weight:500">{{ r.name }}</td>
                                <td><code style="font-size:var(--text-xs)">{{ r.code }}</code></td>
                                <td>{{ r.level }}</td>
                                <td><span class="badge" :class="r.status==='active'?'completed':'pending'">{{ r.status==='active'?'启用':'停用' }}</span></td>
                              </tr>
                            </tbody>
                          </table>
                          <p v-if="!groupRoles.length" style="text-align:center;color:var(--text-placeholder);padding:var(--space-4);font-size:var(--text-sm)">该组暂无角色</p>
                        </div>
                      </td>
                    </tr>
                  </template>
                </tbody>
              </table>
            </div>
            <div v-else class="empty"><div class="empty-text">暂无角色组，点击"新增角色组"创建</div></div>
          </div>
        </div>
      </div>
    </div>

    <!-- Group Modal -->
    <div v-if="showGroupModal" class="modal-overlay" >
      <div class="modal" style="max-width:640px">
        <div class="modal-header"><span>{{ groupModalEdit ? '编辑角色组' : '新增角色组' }}</span><span class="modal-close" @click="showGroupModal=false">&times;</span></div>
        <div class="modal-body">
          <div class="form-group"><label>名称 *</label><input class="form-input" v-model="groupForm.name"></div>
          <div class="form-group"><label>父级角色组</label>
            <select class="form-input" v-model.number="groupForm.parent_id">
              <option :value="null">无（顶级）</option>
              <option v-for="g in groups" :key="g.id" :value="g.id" :disabled="groupModalEdit && g.id===groupForm._id">{{ g.name }}</option>
            </select>
          </div>
          <div class="form-group"><label>描述</label><textarea class="form-input" v-model="groupForm.description" rows="2"></textarea></div>
          <div class="form-group"><label>状态</label><select class="form-input" v-model="groupForm.status"><option value="active">启用</option><option value="inactive">停用</option></select></div>
          <div class="form-group">
            <label>权限配置</label>
            <div style="padding:12px;background:var(--info-light);border-radius:var(--radius-md);margin-top:6px;font-size:var(--text-sm);color:var(--text-muted);line-height:1.6">
              ⚠️ 权限配置已统一迁移至<strong>角色管理</strong>模块。<br>
              角色组仅作为组织分类，不再参与权限计算。<br>
              请前往 <strong>基础设置 → 角色管理</strong> 为各角色独立配置权限。
            </div>
          </div>
        </div>
        <div class="modal-footer">
          <button class="btn btn-default" @click="showGroupModal=false">取消</button>
          <button class="btn btn-primary" @click="saveGroup">💾 保存</button>
        </div>
      </div>
    </div>
</div>
</template>

<script>
import { useRoleGroups } from '@/composables/settings/useRoleGroups.js'

export default {
  setup() {
    return useRoleGroups()
  }
}
</script>