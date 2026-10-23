<template>
  <div>
    <div class="audit-quick-bar">
      <button
        v-for="option in auditQuickOptions"
        :key="option.key"
        class="audit-quick-card"
        :class="[{ active: auditMode === option.key }, option.className]"
        @click="setAuditMode(option.key)"
      >
        <span>{{ option.icon }}</span>
        <b>{{ option.label }}</b>
        <small>{{ option.hint }}</small>
      </button>
    </div>

    <div class="audit-filter-bar">
      <select class="form-input" v-model="auditFilters.review_status" @change="markCustomAndLoad">
        <option value="pending">待审核</option>
        <option value="approved">已通过</option>
        <option value="rejected">已驳回</option>
        <option value="">全部审核</option>
      </select>
      <select class="form-input" v-model="auditFilters.status" @change="markCustomAndLoad">
        <option value="">全部状态</option>
        <option value="completed">已完成</option>
        <option value="running">进行中</option>
        <option value="abnormal">异常</option>
      </select>
      <select class="form-input" v-model="auditFilters.process_id" @change="markCustomAndLoad">
        <option value="">全部工序</option>
        <option v-for="p in processes" :key="p.id" :value="p.id">{{ p.name }}</option>
      </select>
      <input class="form-input" type="date" v-model="auditFilters.date_from" @change="markCustomAndLoad">
      <input class="form-input" type="date" v-model="auditFilters.date_to" @change="markCustomAndLoad">
      <button class="btn btn-default btn-sm" @click="resetAuditFilters">重置</button>
    </div>

    <div v-if="isLoading" class="empty"><div class="empty-icon">⏳</div><div class="empty-text">正在加载审核工时...</div></div>
    <template v-else-if="visibleRecords.length">
      <div class="audit-result-summary">当前显示 {{ visibleRecords.length }} 条，低于 80% 效率的记录会标红。</div>
      <div class="table-wrap desktop-table-wrap">
        <table class="data-table" style="min-width:1120px">
          <thead><tr>
            <th>订单/序列号</th><th>工序</th><th>员工</th><th>数量</th><th>标准</th><th>实际</th><th>有效</th><th>效率</th><th>状态</th><th>审核</th><th>异常原因</th><th>时间</th><th class="operation-col">操作</th>
          </tr></thead>
          <tbody>
            <tr v-for="row in visibleRecords" :key="row.id" :class="{ 'low-efficiency-row': isLowEfficiency(row) }">
              <td><b>{{ row.order_no_display || row.order_no || '-' }}</b><div class="muted-xs">{{ row.serial_no || '-' }}</div></td>
              <td>{{ row.process_name_display || row.process_name || '-' }}</td>
              <td>{{ row.user_name_display || row.user_name || '-' }}</td>
              <td>{{ row.quantity || 1 }}</td>
              <td>{{ row.standard_minutes || 0 }} 分</td>
              <td>{{ row.actual_minutes || 0 }} 分</td>
              <td><b>{{ row.effective_minutes || 0 }} 分</b></td>
              <td><span :class="efficiencyClass(row)">{{ efficiency(row) }}</span></td>
              <td><span class="badge" :class="recordStatusClass(row.status)">{{ recordStatusLabel(row.status) }}</span></td>
              <td><span class="badge" :class="reviewStatusClass(row.review_status)">{{ reviewStatusLabel(row.review_status) }}</span></td>
              <td class="reason-cell" :title="row.abnormal_reason || ''">{{ row.abnormal_reason || '-' }}</td>
              <td class="time-cell">{{ row.start_time || '-' }}</td>
              <td class="operation-cell"><button class="btn btn-default btn-sm" @click="emit('review', row)">审核</button></td>
            </tr>
          </tbody>
        </table>
      </div>
      <div class="mobile-record-list">
        <div v-for="row in visibleRecords" :key="row.id" class="mobile-record-card" :class="{ 'low-efficiency-card': isLowEfficiency(row) }">
          <div class="mobile-card-title"><b>{{ row.order_no_display || row.order_no || '-' }}</b><span :class="efficiencyClass(row)">{{ efficiency(row) }}</span></div>
          <div class="mobile-card-meta">{{ row.process_name_display || row.process_name || '-' }} · {{ row.user_name_display || row.user_name || '-' }}</div>
          <div class="mobile-card-grid"><span>标准 {{ row.standard_minutes || 0 }} 分</span><span>有效 {{ row.effective_minutes || 0 }} 分</span><span>数量 {{ row.quantity || 1 }}</span><span>{{ row.start_time || '-' }}</span></div>
          <div class="mobile-card-actions"><span class="badge" :class="recordStatusClass(row.status)">{{ recordStatusLabel(row.status) }}</span><span class="badge" :class="reviewStatusClass(row.review_status)">{{ reviewStatusLabel(row.review_status) }}</span><button class="btn btn-default btn-sm" @click="emit('review', row)">审核</button></div>
        </div>
      </div>
    </template>
    <div v-else class="empty"><div class="empty-icon">✅</div><div class="empty-text">{{ emptyText }}</div></div>
  </div>
</template>

<script setup>
import { useWorkTimeAudit } from '@/composables/workTime/useWorkTimeAudit.js'

const props = defineProps({
  keyword: { type: String, default: '' },
  processes: { type: Array, default: () => [] },
})
const emit = defineEmits(['review'])

const {
  records,
  isLoading,
  auditMode,
  auditFilters,
  auditQuickOptions,
  visibleRecords,
  emptyText,
  load,
  setAuditMode,
  markCustomAndLoad,
  resetAuditFilters,
  efficiencyValue,
  efficiency,
  isLowEfficiency,
  efficiencyClass,
  recordStatusLabel,
  recordStatusClass,
  reviewStatusLabel,
  reviewStatusClass
} = useWorkTimeAudit(props, emit)

defineExpose({ load })
</script>

<style scoped>
.audit-quick-bar,
.audit-filter-bar {
  display: flex;
  gap: var(--space-2);
  margin-bottom: var(--space-3);
  flex-wrap: wrap;
}
.audit-quick-card {
  display: flex;
  flex-direction: column;
  align-items: flex-start;
  min-width: 160px;
  border: 1px solid var(--border-color);
  border-radius: var(--radius-lg);
  background: var(--bg-primary);
  color: var(--text-primary);
  cursor: pointer;
  padding: var(--space-3);
  text-align: left;
}
.audit-quick-card small {
  color: var(--text-secondary);
  margin-top: 2px;
}
.audit-quick-card.active {
  border-color: var(--primary);
  box-shadow: 0 0 0 2px var(--primary-light);
}
.audit-quick-card.warning.active { border-color: var(--warning); box-shadow: 0 0 0 2px var(--warning-lighter); }
.audit-quick-card.danger.active { border-color: var(--danger); box-shadow: 0 0 0 2px var(--danger-light); }
.audit-filter-bar .form-input { width: 150px; }
.audit-filter-bar select:nth-child(3) { width: 190px; }
.audit-result-summary {
  margin-bottom: var(--space-2);
  color: var(--text-secondary);
  font-size: var(--text-sm);
}
.muted-xs,
.time-cell {
  font-size: var(--text-xs);
  color: var(--text-placeholder);
  white-space: nowrap;
}
.reason-cell {
  max-width: 180px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.operation-col { width: 90px; min-width: 90px; white-space: nowrap; }
.operation-cell { white-space: nowrap; }
.low-efficiency-row { background: rgba(220, 38, 38, .06); }
.efficiency-danger { color: var(--danger); font-weight: 700; }
.efficiency-normal { color: var(--success); font-weight: 700; }
.mobile-record-list { display: none; }
@media (max-width: 768px) {
  .audit-quick-card,
  .audit-filter-bar .form-input,
  .audit-filter-bar .btn {
    width: 100%;
  }
  .desktop-table-wrap { display: none; }
  .mobile-record-list {
    display: flex;
    flex-direction: column;
    gap: var(--space-3);
  }
  .mobile-record-card {
    border: 1px solid var(--border-color);
    border-radius: var(--radius-lg);
    background: var(--bg-primary);
    padding: var(--space-3);
  }
  .low-efficiency-card { border-color: var(--danger); }
  .mobile-card-title,
  .mobile-card-actions {
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: var(--space-2);
    flex-wrap: wrap;
  }
  .mobile-card-meta {
    margin-top: 4px;
    color: var(--text-secondary);
  }
  .mobile-card-grid {
    display: grid;
    grid-template-columns: 1fr 1fr;
    gap: var(--space-1) var(--space-2);
    margin: var(--space-2) 0;
    color: var(--text-secondary);
    font-size: var(--text-sm);
  }
}
</style>
