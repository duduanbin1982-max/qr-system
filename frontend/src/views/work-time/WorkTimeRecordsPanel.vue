<template>
  <div>
    <div class="record-filter-bar">
      <select class="form-input" v-model="recordFilters.review_status" @change="load">
        <option value="">全部审核</option>
        <option value="pending">待审核</option>
        <option value="approved">已通过</option>
        <option value="rejected">已驳回</option>
      </select>
      <select class="form-input" v-model="recordFilters.status" @change="load">
        <option value="">全部状态</option>
        <option value="completed">已完成</option>
        <option value="running">进行中</option>
        <option value="abnormal">异常</option>
      </select>
      <select class="form-input process-select" v-model="recordFilters.process_id" @change="load">
        <option value="">全部工序</option>
        <option v-for="p in processes" :key="p.id" :value="p.id">{{ p.name }}</option>
      </select>
      <select class="form-input" v-model="recordFilters.standard_missing" @change="load">
        <option value="">全部标准</option>
        <option value="0">已匹配标准</option>
        <option value="1">缺标准工时</option>
      </select>
      <input class="form-input" type="date" v-model="recordFilters.date_from" @change="load">
      <input class="form-input" type="date" v-model="recordFilters.date_to" @change="load">
      <button class="btn btn-default btn-sm" :disabled="!hasRecordFilters" @click="clearRecordFilters">清空筛选</button>
    </div>

    <div v-if="isLoading" class="empty"><div class="empty-icon">⏳</div><div class="empty-text">正在加载工时流水...</div></div>
    <template v-else-if="records.length">
      <div class="record-result-summary">当前显示 {{ records.length }} 条工时流水</div>
      <div class="table-wrap desktop-table-wrap">
        <table class="data-table" style="min-width:1320px">
          <thead><tr>
            <th>订单/序列号</th><th>产品</th><th>路线</th><th>工序</th><th>员工</th><th>数量</th><th>标准</th><th>实际</th><th>有效</th><th>效率</th><th>状态</th><th>审核</th><th>异常原因</th><th>时间</th><th class="operation-col">操作</th>
          </tr></thead>
          <tbody>
            <tr v-for="row in records" :key="row.id" :class="{ 'abnormal-row': row.status === 'abnormal', 'missing-standard-row': Number(row.standard_missing || 0) === 1 }">
              <td><b>{{ row.order_no_display || row.order_no || '-' }}</b><div class="muted-xs">{{ row.serial_no || '-' }}</div></td>
              <td><b>{{ row.product_code_display || row.product_code || '-' }}</b><div class="muted-xs">{{ row.product_name_display || row.product_name || '-' }}</div></td>
              <td>{{ row.route_name_display || row.route_name || '-' }}</td>
              <td>{{ row.process_name_display || row.process_name || '-' }}</td>
              <td>{{ row.user_name_display || row.user_name || '-' }}</td>
              <td>{{ row.quantity || 1 }}</td>
              <td><span :class="standardCellClass(row)">{{ standardCellText(row) }}</span></td>
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
        <div v-for="row in records" :key="row.id" class="mobile-record-card" :class="{ 'abnormal-card': row.status === 'abnormal', 'missing-standard-card': Number(row.standard_missing || 0) === 1 }">
          <div class="mobile-card-title"><b>{{ row.order_no_display || row.order_no || '-' }}</b><span :class="efficiencyClass(row)">{{ efficiency(row) }}</span></div>
          <div class="mobile-card-meta">{{ row.product_code_display || row.product_code || '-' }} · {{ row.product_name_display || row.product_name || '-' }}</div>
          <div class="mobile-card-meta">{{ row.route_name_display || row.route_name || '未关联路线' }} · {{ row.process_name_display || row.process_name || '-' }} · {{ row.user_name_display || row.user_name || '-' }}</div>
          <div class="mobile-card-grid"><span>{{ standardCellText(row) }}</span><span>有效 {{ row.effective_minutes || 0 }} 分</span><span>数量 {{ row.quantity || 1 }}</span><span>{{ row.start_time || '-' }}</span></div>
          <div class="mobile-card-actions"><span class="badge" :class="recordStatusClass(row.status)">{{ recordStatusLabel(row.status) }}</span><span class="badge" :class="reviewStatusClass(row.review_status)">{{ reviewStatusLabel(row.review_status) }}</span><button class="btn btn-default btn-sm" @click="emit('review', row)">审核</button></div>
        </div>
      </div>
    </template>
    <div v-else class="empty"><div class="empty-icon">🧾</div><div class="empty-text">{{ hasRecordFilters ? '当前筛选条件下暂无工时流水' : '暂无工时流水' }}</div></div>

    <teleport to="body">
      <div v-if="showRecordModal" class="modal-overlay record-modal-overlay" @click.self="showRecordModal=false">
        <div class="modal record-modal">
          <div class="modal-header"><h3>新增工时流水</h3></div>
          <div class="modal-body record-modal-body">
            <div class="form-row">
              <div class="form-group order-search-group">
                <label>订单号（搜索选择）</label>
                <div class="order-search-row">
                  <input class="form-input" v-model="orderKeyword" placeholder="输入订单号/产品/客户后回车搜索" @keyup.enter="searchOrders">
                  <button class="btn btn-default btn-sm" :disabled="isSearchingOrders" @click="searchOrders">{{ isSearchingOrders ? '搜索中...' : '搜索' }}</button>
                </div>
                <select class="form-input" v-model="recordForm.order_id" @change="selectOrderById">
                  <option value="">不关联订单，仅手工记录</option>
                  <option v-for="order in orderOptions" :key="order.id" :value="order.id">{{ order.order_no }} / {{ order.product_code || '-' }} / {{ order.product_name || '-' }}</option>
                </select>
                <input v-if="!recordForm.order_id" class="form-input" v-model="recordForm.order_no" placeholder="未关联订单时可手填订单号">
              </div>
              <div class="form-group"><label>序列号</label><input class="form-input" v-model="recordForm.serial_no" placeholder="可选"></div>
            </div>

            <div v-if="recordForm.order_id" class="record-snapshot-panel">
              <span><b>产品编码：</b>{{ recordForm.product_code || '-' }}</span>
              <span><b>产品名称：</b>{{ recordForm.product_name || '-' }}</span>
              <span><b>工序路线：</b>{{ recordForm.route_name || '-' }}</span>
              <span :class="standardStatus.class"><b>标准匹配：</b>{{ standardStatus.text }}</span>
            </div>
            <div v-else class="record-snapshot-panel warning-panel">
              未选择订单时无法按订单路线精确匹配标准工时，建议优先搜索并选择订单。
            </div>

            <div class="form-row">
              <div class="form-group">
                <label>工序</label>
                <select class="form-input" v-model="recordForm.process_id" @change="handleProcessChange">
                  <option value="">请选择</option>
                  <option v-for="p in availableProcesses" :key="processValue(p)" :value="processValue(p)">{{ processName(p) }}</option>
                </select>
              </div>
              <div class="form-group"><label>员工</label><select class="form-input" v-model="recordForm.user_id"><option value="">请选择</option><option v-for="u in users" :key="u.id" :value="u.id">{{ u.name }} / {{ u.employee_no || u.username }}</option></select></div>
              <div class="form-group"><label>数量</label><input class="form-input" type="number" min="1" v-model.number="recordForm.quantity"></div>
            </div>
            <div class="form-row">
              <div class="form-group"><label>开始时间</label><input class="form-input" type="datetime-local" v-model="recordForm.start_time"></div>
              <div class="form-group"><label>结束时间</label><input class="form-input" type="datetime-local" v-model="recordForm.end_time"></div>
              <div class="form-group"><label>暂停分钟</label><input class="form-input" type="number" min="0" step="0.1" v-model.number="recordForm.pause_minutes"></div>
            </div>
            <div class="form-row">
              <div class="form-group"><label>有效工时（分钟，可审核修正）</label><input class="form-input" type="number" min="0" step="0.1" v-model.number="recordForm.effective_minutes"></div>
              <div class="form-group"><label>状态</label><select class="form-input" v-model="recordForm.status"><option value="completed">已完成</option><option value="running">进行中</option><option value="abnormal">异常</option></select></div>
            </div>
            <div class="form-group"><label>异常原因</label><textarea class="form-input" rows="2" v-model="recordForm.abnormal_reason" placeholder="忘记完工、待料、设备故障等"></textarea></div>
          </div>
          <div class="modal-footer"><button class="btn btn-default" :disabled="isSaving" @click="showRecordModal=false">取消</button><button class="btn btn-primary" :disabled="isSaving" @click="saveRecord">{{ isSaving ? '保存中...' : '保存' }}</button></div>
        </div>
      </div>
    </teleport>
  </div>
</template>

<script setup>
import { useWorkTimeRecords } from '@/composables/workTime/useWorkTimeRecords.js'

const props = defineProps({
  keyword: { type: String, default: '' },
  processes: { type: Array, default: () => [] },
  users: { type: Array, default: () => [] },
})
const emit = defineEmits(['changed', 'review'])

const {
  records,
  isLoading,
  isSaving,
  isSearchingOrders,
  recordFilters,
  recordForm,
  orderKeyword,
  orderOptions,
  standardMatch,
  standardChecked,
  standardChecking,
  showRecordModal,
  hasRecordFilters,
  selectedOrder,
  availableProcesses,
  standardStatus,
  nowLocalInput,
  processValue,
  processName,
  formatMinute,
  resetStandardCheck,
  checkStandardMatch,
  load,
  clearRecordFilters,
  searchOrders,
  selectOrderById,
  handleProcessChange,
  openRecord,
  saveRecord,
  efficiencyValue,
  efficiency,
  efficiencyClass,
  standardCellText,
  standardCellClass,
  recordStatusLabel,
  recordStatusClass,
  reviewStatusLabel,
  reviewStatusClass
} = useWorkTimeRecords(props, emit)

defineExpose({ load, openRecord })
</script>

<style scoped>
.record-filter-bar {
  display: flex;
  gap: var(--space-2);
  margin-bottom: var(--space-3);
  flex-wrap: wrap;
}
.record-filter-bar .form-input { width: 150px; }
.record-filter-bar .process-select { width: 190px; }
.record-result-summary {
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
.abnormal-row { background: rgba(220, 38, 38, .06); }
.missing-standard-row { background: rgba(245, 158, 11, .06); }
.efficiency-danger { color: var(--danger); font-weight: 700; }
.efficiency-normal { color: var(--success); font-weight: 700; }
.efficiency-muted,
.standard-muted { color: var(--text-placeholder); }
.standard-ok { color: var(--success); font-weight: 700; }
.standard-warning { color: var(--warning); font-weight: 700; }
.record-snapshot-panel {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: var(--space-2);
  margin-bottom: var(--space-3);
  padding: var(--space-3);
  border: 1px solid var(--border-color);
  border-radius: var(--radius-md);
  background: var(--bg-secondary);
  font-size: var(--text-sm);
}
.warning-panel {
  color: var(--warning);
  background: rgba(245, 158, 11, .08);
  border-color: rgba(245, 158, 11, .28);
}
.order-search-group { flex: 2; }
.order-search-row {
  display: flex;
  gap: var(--space-2);
  margin-bottom: var(--space-2);
}
.order-search-row .form-input { flex: 1; }
.record-modal-overlay {
  position: fixed;
  inset: 0;
  align-items: flex-start;
  box-sizing: border-box;
  padding: 24px;
  overflow: hidden;
  overscroll-behavior: contain;
  animation: none;
}
.record-modal {
  width: min(860px, calc(100vw - 48px));
  max-width: calc(100vw - 48px);
  max-height: calc(100vh - 48px);
  display: flex;
  flex-direction: column;
  overflow: hidden;
  animation: none;
  transform: none;
}
.record-modal-body {
  flex: 1;
  min-height: 0;
  overflow: auto;
}
.record-modal .modal-footer {
  flex-shrink: 0;
}
.mobile-record-list { display: none; }
@media (max-width: 768px) {
  .record-filter-bar .form-input,
  .record-filter-bar .btn {
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
  .abnormal-card { border-color: var(--danger); }
  .missing-standard-card { border-color: var(--warning); }
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
  .record-snapshot-panel {
    grid-template-columns: 1fr;
  }
  .order-search-row {
    flex-direction: column;
  }
  .record-modal-overlay {
    padding: 12px;
  }
  .record-modal {
    width: calc(100vw - 24px);
    max-width: calc(100vw - 24px);
    max-height: calc(100vh - 24px);
  }
  .record-modal-body {
    padding: var(--space-4);
  }
}
</style>
