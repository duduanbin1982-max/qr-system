<template>
  <div class="trace-page">
    <div class="card trace-search-card">
      <div class="card-body trace-search-body">
        <div class="trace-modes">
          <button class="btn btn-sm" :class="{ 'btn-primary': traceMode === 'serial' }" @click="traceMode = 'serial'">🔢 序列号追溯</button>
          <button class="btn btn-sm" :class="{ 'btn-primary': traceMode === 'order' }" @click="traceMode = 'order'">📋 订单号追溯</button>
        </div>
        <div class="trace-search-row">
          <input
            v-model="traceCode"
            class="form-input trace-input"
            :placeholder="traceMode === 'serial' ? '输入产品序列号' : '输入订单号'"
            autofocus
            @keyup.enter="doTrace()"
          >
          <button class="btn btn-primary trace-submit" :disabled="searching" @click="doTrace()">
            {{ searching ? '查询中...' : '🔍 追溯' }}
          </button>
          <button v-if="result" class="btn trace-print" @click="printReport">🖨 打印报告</button>
        </div>
        <div v-if="traceHistory.length" class="trace-history">
          <span class="trace-history-label">历史:</span>
          <button
            v-for="history in traceHistory"
            :key="`${history.mode}-${history.code}`"
            class="trace-history-item"
            :title="history.mode === 'serial' ? '序列号' : '订单号'"
            @click="traceTarget(history.code, history.mode)"
          >
            {{ history.mode === 'serial' ? '🔢' : '📋' }} {{ history.code }}
          </button>
        </div>
      </div>
    </div>

    <template v-if="result">
      <TraceOverview
        :result="result"
        :searching="searching"
        @trace-serial="traceTarget($event, 'serial')"
        @trace-order="traceTarget($event, 'order')"
        @page="doTrace"
      />
      <TraceProductionHistory :result="result" />
      <TraceQualityRecords :result="result" />
      <TraceLogisticsRecords :result="result" />
    </template>

    <div v-else class="card trace-empty-card">
      <div class="card-body">
        <div class="trace-empty-icon">🔍</div>
        <div>暂无追溯结果</div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref } from 'vue'

import TraceLogisticsRecords from '@/components/TraceLogisticsRecords.vue'
import TraceOverview from '@/components/TraceOverview.vue'
import TraceProductionHistory from '@/components/TraceProductionHistory.vue'
import TraceQualityRecords from '@/components/TraceQualityRecords.vue'
import { useTraceSearch } from '@/composables/useTraceSearch.js'
import { api } from '@/lib/api.js'
import { showToast } from '@/lib/store.js'

const traceCode = ref('')
const traceMode = ref('serial')
const { searching, result, search } = useTraceSearch(api.domains.trace)
const HISTORY_KEY = 'qr_trace_history'
let storedHistory = []
try {
  storedHistory = JSON.parse(localStorage.getItem(HISTORY_KEY) || '[]')
} catch {
  storedHistory = []
}
const traceHistory = ref(storedHistory)

function saveHistory(code, mode) {
  const history = traceHistory.value.filter(item => item.code !== code || item.mode !== mode)
  history.unshift({ code, mode })
  traceHistory.value = history.slice(0, 10)
  localStorage.setItem(HISTORY_KEY, JSON.stringify(traceHistory.value))
}

async function doTrace(requestedPage = 1) {
  const code = traceCode.value.trim()
  if (!code) {
    showToast(traceMode.value === 'serial' ? '请输入产品序列号' : '请输入订单号', 'error')
    return
  }
  const mode = traceMode.value
  const outcome = await search({ code, mode, page: requestedPage, perPage: 100 })
  if (!outcome.applied) return
  if (outcome.error) {
    showToast(outcome.error.message || '查询失败', 'error')
    return
  }
  saveHistory(code, mode)
}

function traceTarget(code, mode) {
  traceCode.value = code
  traceMode.value = mode
  doTrace()
}

function printReport() {
  window.print()
}
</script>

<style scoped>
.trace-page { padding: var(--space-6); }
.trace-search-card { margin-bottom: var(--space-5); }
.trace-search-body { padding: var(--space-5); }
.trace-modes { display: flex; gap: var(--space-3); margin-bottom: var(--space-3); }
.trace-modes .btn:not(.btn-primary) { background: var(--bg-hover); color: var(--text-placeholder); }
.trace-search-row { display: flex; align-items: center; gap: var(--space-3); }
.trace-input { flex: 1; min-width: 0; padding: var(--space-3) 16px; border: 2px solid var(--primary); font-size: var(--text-lg); }
.trace-submit, .trace-print { flex: 0 0 auto; padding: var(--space-3) 24px; white-space: nowrap; }
.trace-print { border: 1px solid var(--border-light); background: #fff; }
.trace-history { display: flex; flex-wrap: wrap; align-items: center; gap: 6px; margin-top: 10px; }
.trace-history-label { color: var(--text-placeholder); font-size: 11px; }
.trace-history-item { padding: 2px 8px; border: 0; border-radius: 10px; background: var(--bg-hover); color: var(--primary); cursor: pointer; font-size: 11px; white-space: nowrap; }
.trace-empty-card .card-body { padding: 56px 24px; color: var(--text-placeholder); text-align: center; }
.trace-empty-icon { margin-bottom: var(--space-3); font-size: 40px; }
@media (max-width: 720px) {
  .trace-page { padding: var(--space-3); }
  .trace-search-row { align-items: stretch; flex-wrap: wrap; }
  .trace-input { flex-basis: 100%; }
  .trace-submit, .trace-print { flex: 1; }
}
@media print {
  .trace-search-card { display: none !important; }
  :deep(.card) { break-inside: avoid; margin-bottom: 12px !important; }
  :deep(.trace-pagination), :deep(.trace-order-link) { display: none !important; }
}
</style>
