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
      <div class="modal" style="max-width:860px">
        <div class="modal-header"><span>{{ roleModalEdit ? '编辑角色' : '新增角色' }}</span><span class="modal-close" @click="showRoleModal=false">&times;</span></div>
        <div class="modal-body">
          <div class="form-group"><label>名称 *</label><input class="form-input" v-model="roleForm.name"></div>
          <div class="form-group"><label>编码</label><span style="color:var(--text-muted);font-size:var(--text-xs)">（留空自动生成）</span><input class="form-input" v-model="roleForm.code"></div>
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
            <div style="display:flex;gap:var(--space-2);align-items:center;margin-bottom:var(--space-2);flex-wrap:wrap">
              <input class="form-input" v-model="permissionSearch" placeholder="🔍 搜索页面、操作、权限编码..." style="flex:1;min-width:220px">
              <button type="button" class="btn btn-sm" @click="expandPermissionTree">展开</button>
              <button type="button" class="btn btn-sm" @click="collapsePermissionTree">折叠</button>
              <button type="button" class="btn btn-sm" @click="selectAllPermissions">全选</button>
              <button type="button" class="btn btn-sm" @click="clearPermissions">清空</button>
            </div>
            <label style="display:flex;align-items:center;gap:8px;margin-bottom:var(--space-2);padding:8px 10px;border:1px solid var(--warning);border-radius:var(--radius-md);background:var(--warning-light);cursor:pointer">
              <input type="checkbox" v-model="wildcardSelected" @change="toggleWildcardPermission" style="accent-color:var(--warning)">
              <span style="font-weight:600;color:var(--warning-dark)">全部权限（*，超级管理员专用）</span>
              <span style="font-size:var(--text-xs);color:var(--text-secondary)">勾选后保存为通配权限，未来新增权限也自动拥有。</span>
            </label>
            <div style="max-height:460px;overflow-y:auto;border:1px solid var(--border-light);border-radius:var(--radius-md);padding:var(--space-2);background:white">
              <div v-if="!filteredPermissionTree.length" style="padding:24px;text-align:center;color:var(--text-placeholder)">无匹配权限</div>
              <div v-for="module in filteredPermissionTree" :key="module.key" style="margin-bottom:var(--space-3);border:1px solid var(--border-light);border-radius:var(--radius-md);overflow:hidden">
                <div style="display:flex;align-items:center;gap:8px;padding:8px 10px;font-weight:700;background:var(--bg-table-header);flex-wrap:wrap">
                  <button type="button" class="btn btn-sm" style="padding:2px 6px" @click="togglePermissionExpand(module)">{{ isPermissionExpanded(module) ? '▾' : '▸' }}</button>
                  <input type="checkbox" :checked="isNodeChecked(module)" :disabled="wildcardSelected" @change="togglePermissionNode(module, $event)" style="accent-color:var(--primary)">
                  <span>{{ module.label }}</span>
                  <code style="font-size:var(--text-2xs);color:var(--text-placeholder)">{{ module.code }}</code>
                  <label style="display:flex;align-items:center;gap:4px;margin-left:auto;font-weight:500;font-size:var(--text-xs);cursor:pointer">
                    <input type="checkbox" :checked="isPageDisplayChecked(module)" :disabled="wildcardSelected" @change="togglePageDisplay(module, $event)" style="accent-color:var(--success)">
                    显示模块
                  </label>
                  <span v-if="isNodePartial(module)" class="badge" style="background:var(--warning-light);color:var(--warning)">部分</span>
                  <button type="button" class="btn btn-sm" @click="selectNodePermissions(module)">本模块全选</button>
                  <button type="button" class="btn btn-sm" @click="clearNodePermissions(module)">清空模块</button>
                </div>
                <div v-show="isPermissionExpanded(module)" style="padding:var(--space-2);display:flex;flex-direction:column;gap:var(--space-2)">
                  <div v-if="(module.operations||[]).length || !(module.children||[]).length" style="border:1px solid var(--bg-hover);border-radius:var(--radius-md);padding:var(--space-2);background:var(--bg-card)">
                    <div style="display:flex;align-items:center;gap:8px;flex-wrap:wrap;margin-bottom:var(--space-2)">
                      <input type="checkbox" :checked="isPageDisplayChecked(module)" :disabled="wildcardSelected" @change="togglePageDisplay(module, $event)" style="accent-color:var(--success)">
                      <strong>{{ module.label }}</strong>
                      <span class="badge" style="background:var(--success-light);color:var(--success)">显示页面</span>
                      <code style="font-size:var(--text-2xs);color:var(--text-placeholder)">{{ module.code }}</code>
                      <button type="button" class="btn btn-sm" style="margin-left:auto" @click="selectPagePreset(module, 'display')">只显示</button>
                      <button type="button" class="btn btn-sm" @click="selectPagePreset(module, 'view')">查看</button>
                      <button type="button" class="btn btn-sm" @click="selectPagePreset(module, 'maintain')">维护</button>
                      <button type="button" class="btn btn-sm" @click="selectPagePreset(module, 'all')">全选</button>
                      <button type="button" class="btn btn-sm" @click="selectPagePreset(module, 'clear')">清空</button>
                    </div>
                    <div v-if="(module.operations||[]).length" style="display:grid;grid-template-columns:repeat(auto-fill,minmax(150px,1fr));gap:6px">
                      <label v-for="op in module.operations" :key="op.key || op.code" style="display:flex;align-items:center;gap:6px;padding:6px 8px;border:1px solid var(--border-light);border-radius:var(--radius-sm);cursor:pointer;background:white">
                        <input type="checkbox" :checked="isActionChecked(op)" :disabled="wildcardSelected" @change="toggleAction(module, op, $event)" style="accent-color:var(--primary)">
                        <span>{{ op.label }}</span>
                        <code style="font-size:var(--text-2xs);color:var(--text-placeholder)">{{ op.code }}</code>
                      </label>
                    </div>
                    <div v-else style="font-size:var(--text-xs);color:var(--text-placeholder)">该页面暂无独立业务操作权限，仅控制页面显示。</div>
                  </div>

                  <div v-for="page in (module.children || [])" :key="page.key || page.code" style="border:1px solid var(--bg-hover);border-radius:var(--radius-md);padding:var(--space-2);background:var(--bg-card)">
                    <div style="display:flex;align-items:center;gap:8px;flex-wrap:wrap;margin-bottom:var(--space-2)">
                      <input type="checkbox" :checked="isPageDisplayChecked(page)" :disabled="wildcardSelected" @change="togglePageDisplay(page, $event)" style="accent-color:var(--success)">
                      <strong>{{ page.label }}</strong>
                      <span class="badge" style="background:var(--success-light);color:var(--success)">显示页面</span>
                      <code style="font-size:var(--text-2xs);color:var(--text-placeholder)">{{ page.code }}</code>
                      <span v-if="isNodePartial(page)" class="badge" style="background:var(--warning-light);color:var(--warning)">部分</span>
                      <button type="button" class="btn btn-sm" style="margin-left:auto" @click="selectPagePreset(page, 'display')">只显示</button>
                      <button type="button" class="btn btn-sm" @click="selectPagePreset(page, 'view')">查看</button>
                      <button type="button" class="btn btn-sm" @click="selectPagePreset(page, 'maintain')">维护</button>
                      <button type="button" class="btn btn-sm" @click="selectPagePreset(page, 'all')">全选</button>
                      <button type="button" class="btn btn-sm" @click="selectPagePreset(page, 'clear')">清空</button>
                    </div>
                    <div v-if="(page.operations||[]).length" style="display:grid;grid-template-columns:repeat(auto-fill,minmax(150px,1fr));gap:6px">
                      <label v-for="op in page.operations" :key="op.key || op.code" style="display:flex;align-items:center;gap:6px;padding:6px 8px;border:1px solid var(--border-light);border-radius:var(--radius-sm);cursor:pointer;background:white">
                        <input type="checkbox" :checked="isActionChecked(op)" :disabled="wildcardSelected" @change="toggleAction(page, op, $event)" style="accent-color:var(--primary)">
                        <span>{{ op.label }}</span>
                        <code style="font-size:var(--text-2xs);color:var(--text-placeholder)">{{ op.code }}</code>
                      </label>
                    </div>
                    <div v-else style="font-size:var(--text-xs);color:var(--text-placeholder)">该页面暂无独立业务操作权限，仅控制页面显示。</div>
                  </div>
                </div>
              </div>
            </div>
            <div style="margin-top:4px;font-size:var(--text-xs-alt);color:var(--text-placeholder)">
              已选 {{ selectedPermCount }} 项
              <span v-if="selectedPermCount > 0" style="color:var(--primary);cursor:pointer;margin-left:8px" @click="clearPermissions">清空</span>
              <span style="margin-left:8px">勾选业务操作会自动勾选对应页面；取消页面显示会清空该页面下方操作。</span>
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
