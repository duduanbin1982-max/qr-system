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
                  <th style="width:130px;text-align:center;white-space:nowrap">操作</th>
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
                    <button
                      class="btn btn-sm"
                      @click="toggleApproval(proc.id)"
                      :disabled="approvalConfigSaving"
                      :style="{
                        background: isApprovalRequired(proc.id) ? 'var(--danger-light)' : 'var(--success-light)',
                        color: isApprovalRequired(proc.id) ? 'var(--danger)' : 'var(--success)',
                        border: 'none', borderRadius:'var(--radius-md)', padding:'4px 12px',
                        cursor:'pointer', fontWeight:500
                      }"
                    >
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
