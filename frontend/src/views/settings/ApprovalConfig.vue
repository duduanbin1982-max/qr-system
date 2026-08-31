<!-- ApprovalConfig.vue — ✅ 审批配置 -->
<template>
<!-- ========== 审批配置 ========== -->
<div>
      <div class="card" style="margin-bottom:var(--space-5)">
        <div class="card-header">
          <h3>✅ 审批工序配置</h3>
          <span style="font-size:var(--text-xs);color:var(--text-placeholder);margin-left:var(--space-3)">
            开启后，对应工序的报工需管理员审批通过才计入完成量
          </span>
        </div>
        <div v-if="!globalApprovalEnabled" class="alert alert-warning" style="margin:var(--space-4) var(--space-4) 0">
          全局报工审批开关当前关闭；下面的局部规则仅作为策略配置，不会使普通报工进入审批。
        </div>
        <div v-if="policyRevision" style="padding:var(--space-3) var(--space-4) 0;color:var(--text-placeholder);font-size:var(--text-xs)">
          当前版本化审批策略：V{{ policyRevision }}
        </div>
        <div v-if="dirtyProcessIds.size" style="display:flex;justify-content:flex-end;gap:var(--space-2);padding:var(--space-3) var(--space-4) 0">
          <button class="btn btn-default btn-sm" :disabled="approvalConfigSaving" @click="loadApprovalConfig">取消修改</button>
          <button class="btn btn-primary btn-sm" :disabled="approvalConfigSaving" @click="saveApprovalChanges">
            {{ approvalConfigSaving ? '保存中...' : `保存 ${dirtyProcessIds.size} 项修改` }}
          </button>
        </div>
        <div class="card-body">
          <div v-if="approvalConfigLoading" style="text-align:center;padding:40px;color:var(--text-placeholder)">⏳ 加载中...</div>
          <div v-else-if="!approvalProcesses.length" style="text-align:center;padding:40px;color:var(--text-placeholder)">暂无工序数据</div>
          <div v-else class="table-wrap">
            <table class="data-table">
              <thead>
                <tr>
                  <th style="width:60px;text-align:center">序号</th>
                  <th style="width:auto">工序名称</th>
                  <th style="width:100px;text-align:center">分类</th>
                  <th style="width:130px;text-align:center">审批状态</th>
                  <th style="width:90px;text-align:center">级数</th>
                  <th style="width:140px">一级角色</th>
                  <th style="width:140px">二级角色</th>
                  <th style="width:140px">三级角色</th>
                  <th style="width:110px;text-align:center;white-space:nowrap">操作</th>
                </tr>
              </thead>
              <tbody>
                <tr v-for="(proc, idx) in approvalProcesses" :key="proc.id">
                  <td>{{ idx + 1 }}</td>
                  <td>
                    <span style="font-weight:600">{{ proc.process_name || proc.name }}</span>
                  </td>
                  <td>
                    <span style="font-size:var(--text-xs);color:var(--text-placeholder)">
                      {{ proc.category || '通用' }}
                    </span>
                  </td>
                  <td>
                    <span v-if="isApprovalRequired(proc.id)" style="color:var(--success);font-weight:600">✅ 需审批</span>
                    <span v-else style="color:var(--text-placeholder)">— 直接通过</span>
                  </td>
                  <td>
                    <select v-model.number="configFor(proc.id).approval_level" :disabled="!isApprovalRequired(proc.id)" @change="markDirty(proc.id)" class="form-input">
                      <option :value="1">1 级</option><option :value="2">2 级</option><option :value="3">3 级</option>
                    </select>
                  </td>
                  <td>
                    <select v-model.number="configFor(proc.id).approver_role_id" :disabled="!isApprovalRequired(proc.id)" @change="markDirty(proc.id)" class="form-input">
                      <option v-for="role in roleOptions" :key="role.id" :value="role.id">{{ role.name }}</option>
                    </select>
                  </td>
                  <td>
                    <select v-model.number="configFor(proc.id).approver_role_2_id" :disabled="!isApprovalRequired(proc.id) || configFor(proc.id).approval_level < 2" @change="markDirty(proc.id)" class="form-input">
                      <option value="">请选择</option><option v-for="role in roleOptions" :key="role.id" :value="role.id">{{ role.name }}</option>
                    </select>
                  </td>
                  <td>
                    <select v-model.number="configFor(proc.id).approver_role_3_id" :disabled="!isApprovalRequired(proc.id) || configFor(proc.id).approval_level < 3" @change="markDirty(proc.id)" class="form-input">
                      <option value="">请选择</option><option v-for="role in roleOptions" :key="role.id" :value="role.id">{{ role.name }}</option>
                    </select>
                  </td>
                  <td>
                    <button class="btn btn-sm" @click="toggleApproval(proc.id)" :disabled="approvalConfigSaving" :style="{ background: isApprovalRequired(proc.id) ? 'var(--danger-light)' : 'var(--success-light)', color: isApprovalRequired(proc.id) ? 'var(--danger)' : 'var(--success)', border: 'none', borderRadius:'var(--radius-md)', padding:'4px 12px', cursor:'pointer', fontWeight:500 }">
                      <span style="white-space:nowrap">{{ isApprovalRequired(proc.id) ? '🔓 关闭审批' : '🔒 开启审批' }}</span>
                    </button>
                  </td>
                </tr>
              </tbody>
            </table>
          </div>
        </div>
      </div>
</div>
</template>

<script>
import { useApprovalConfig } from '@/composables/settings/useApprovalConfig.js'

export default {
  setup() {
    return useApprovalConfig()
  }
}
</script>
