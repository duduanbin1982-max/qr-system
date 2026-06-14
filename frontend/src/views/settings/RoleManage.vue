<!-- RoleManage.vue -->
<template>
<div>
    <div>
      <div class="card">
        <div class="card-header">
          <h3>👥 角色管理</h3>
          <div style="display:flex;gap:var(--space-2);align-items:center">
            <input class="form-input" v-model="roleSearch" placeholder="🔍 搜索名称/编码..." style="width:160px;padding:6px 10px;font-size:var(--text-sm)">
            <select class="form-input" v-model.number="roleAddGroup" style="border:1px solid var(--border);border-radius:var(--radius-md);padding:var(--space-2) 12px;font-size:var(--text-base);background:white;width:150px">
              <option :value="null">全部角色</option>
              <option v-for="g in groups" :key="g.id" :value="g.id">{{ g.name }}</option>
            </select>
            <button class="btn btn-primary btn-sm" @click="openAddRole()">+ 添加角色</button>
          </div>
        </div>
        <div class="card-body">
          <div v-if="roleLoading" style="text-align:center;padding:40px;color:var(--text-placeholder)">⏳ 加载中...</div>
          <div v-else-if="!filteredRoles.length" style="text-align:center;padding:40px;color:var(--text-placeholder)">{{ roleSearch ? '无匹配角色' : '暂无角色，点击"+ 添加角色"创建' }}</div>
          <div v-else class="table-wrap">
            <table class="data-table" style="min-width:1000px">
              <thead>
                <tr>
                  <th style="width:40px;text-align:center">#</th>
                  <th style="min-width:100px">名称</th>
                  <th style="min-width:120px">编码</th>
                  <th style="min-width:90px">所属组</th>
                  <th style="width:50px">级别</th>
                  <th style="width:85px;white-space:nowrap">状态</th>
                  <th>权限</th>
                  <th style="width:100px;text-align:center;white-space:nowrap">操作</th>
                </tr>
              </thead>
              <tbody>
                <tr v-for="(r, idx) in filteredRoles" :key="r.id">
                  <td style="text-align:center">{{ idx+1 }}</td>
                  <td style="font-weight:500">{{ r.name }}</td>
                  <td><code style="font-size:var(--text-xs)">{{ r.code }}</code></td>
                  <td style="color:var(--text-placeholder);font-size:var(--text-sm)">{{ getGroupName(r.group_id) }}</td>
                  <td>{{ r.level }}</td>
                  <td style="white-space:nowrap"><span class="badge" :class="r.status==='active'?'completed':'pending'">{{ r.status==='active'?'启用':'停用' }}</span></td>
                  <td>
                    <span style="display:flex;flex-wrap:wrap;gap:var(--space-1)">
                      <span v-for="p in formatPerms(r.permissions).slice(0,4)" :key="p" class="badge" style="background:var(--primary-light);color:var(--primary-dark);font-size:var(--text-2xs);border:1px solid var(--primary-light)">{{ p }}</span>
                      <span v-if="formatPerms(r.permissions).length>4" class="badge" style="background:var(--bg-hover);color:var(--text-placeholder);font-size:var(--text-2xs)">+{{ formatPerms(r.permissions).length-4 }}</span>
                    </span>
                  </td>
                  <td style="text-align:center;white-space:nowrap">
                    <button class="o-abtn edit" @click="openEditRole(r)">✏️</button>
                    <button v-if="!r.is_builtin" class="o-abtn del" @click="deleteRole(r.id)" title="删除">🗑️</button>
                  </td>
                </tr>
              </tbody>
            </table>
          </div>
        </div>
      </div>
    </div>

    <!-- Role Modal -->
    <div v-if="showRoleModal" class="modal-overlay" >
      <div class="modal" style="max-width:560px">
        <div class="modal-header"><span>{{ roleModalEdit ? '编辑角色' : '新增角色' }}</span><span class="modal-close" @click="showRoleModal=false">&times;</span></div>
        <div class="modal-body">
          <div class="form-group"><label>名称 *</label><input class="form-input" v-model="roleForm.name"></div>
          <div class="form-group"><label>编码 *</label><input class="form-input" v-model="roleForm.code"></div>
          <div class="form-group"><label>描述</label><input class="form-input" v-model="roleForm.description"></div>
          <div class="form-group"><label>所属角色组</label>
            <select class="form-input" v-model.number="roleForm.group_id">
              <option :value="null">无</option>
              <option v-for="g in groups" :key="g.id" :value="g.id">{{ g.name }}</option>
            </select>
          </div>
          <div class="form-group"><label>级别</label><input class="form-input" v-model.number="roleForm.level" type="number"></div>
          <div class="form-group">
            <label>权限配置</label>
            <div style="max-height:320px;overflow-y:auto;border:1px solid var(--border-light);border-radius:var(--radius-md)">
              <table style="width:100%;font-size:var(--text-xs);border-collapse:collapse">
                <thead><tr style="background:var(--bg-table-header);position:sticky;top:0;z-index:1">
                  <th style="text-align:left;padding:6px 10px;font-size:var(--text-xs-alt);color:var(--text-placeholder)">资源</th>
                  <th v-for="act in permActionLabels" :key="act.key" style="width:44px;text-align:center;padding:var(--space-1) 2px;font-size:var(--text-2xs);color:var(--text-placeholder)">{{ act.label }}</th>
                </tr></thead>
                <tbody>
                  <tr v-for="p in allPermissions" :key="p.code" style="border-bottom:1px solid var(--bg-hover)">
                    <td style="padding:var(--space-1) 10px;font-weight:500">{{ p.label }}</td>
                    <td v-for="act in (p.actions||[])" :key="act" style="text-align:center;padding:var(--space-1)">
                      <label style="display:block;cursor:pointer;padding:var(--space-1) 0">
                        <input type="checkbox" :value="p.code+':'+act" v-model="selectedPerms" style="accent-color:var(--primary)">
                      </label>
                    </td>
                    <td v-for="n in (6 - (p.actions||[]).length)" :key="'empty'+n" style="text-align:center;color:var(--border-light)">·</td>
                  </tr>
                </tbody>
              </table>
            </div>
            <div style="margin-top:4px;font-size:var(--text-xs-alt);color:var(--text-placeholder)">
              已选 {{ selectedPerms.length }} 项
              <span v-if="selectedPerms.length > 0" style="color:var(--primary);cursor:pointer;margin-left:8px" @click="selectedPerms=[]">清空</span>
            </div>
          </div>
          <div class="form-group"><label>状态</label><select class="form-input" v-model="roleForm.status"><option value="active">启用</option><option value="inactive">停用</option></select></div>
        </div>
        <div class="modal-footer">
          <button class="btn btn-default" @click="showRoleModal=false">取消</button>
          <button class="btn btn-primary" @click="saveRole">💾 保存</button>
        </div>
      </div>
    </div>
</div>
</template>

<script>
import { useRoleManage } from '@/composables/settings/useRoleManage.js'

export default {
  setup() {
    return useRoleManage()
  }
}
</script>