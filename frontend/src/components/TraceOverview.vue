<template>
  <div>
    <div v-if="result.item" class="trace-mode-label">🔢 序列号追溯结果</div>
    <div v-else class="trace-mode-label">📋 订单号追溯结果</div>

    <div v-if="historyEvidence.hasLegacyFallback || historyEvidence.hasMissing" class="trace-evidence-banner">
      <strong>历史证据提示：</strong>
      <span v-if="historyEvidence.hasLegacyFallback">部分工序名称来自兼容回退，未使用历史快照/版本。</span>
      <span v-if="historyEvidence.hasMissing">部分历史记录缺少可验证的工序快照或版本证据。</span>
    </div>
    <div v-if="collectionPagination.length" class="trace-evidence-banner trace-pagination-banner">
      <strong>历史集合分页：</strong>
      <div
        v-for="collection in collectionPagination"
        :key="collection.name"
        class="trace-collection-pagination"
      >
        <span>{{ collection.label }}：第 {{ collection.page }} / {{ collection.totalPages }} 页（共 {{ collection.total }} 条）</span>
        <button
          class="btn btn-sm"
          :disabled="collection.page <= 1 || searching"
          title="上一页"
          @click="emit('collection-page', { name: collection.name, page: collection.page - 1, perPage: collection.perPage })"
        >←</button>
        <button
          class="btn btn-sm"
          :disabled="collection.page >= collection.totalPages || searching"
          title="下一页"
          @click="emit('collection-page', { name: collection.name, page: collection.page + 1, perPage: collection.perPage })"
        >→</button>
      </div>
    </div>

    <div v-if="result.item" class="card trace-card">
      <div class="card-header"><h3>🏷️ 产品信息</h3></div>
      <div class="card-body trace-summary">
        <div><span>序列号：</span><code>{{ result.item.serial_no }}</code></div>
        <div><span>状态：</span><span class="badge" :class="itemStatus.cls">{{ itemStatus.label }}</span></div>
        <div><span>订单号：</span><code>{{ result.order?.order_no || '-' }}</code></div>
        <div><span>产品：</span>{{ result.order?.product_name || '-' }}</div>
        <div><span>位置序号：</span>{{ result.item.position_no || '-' }}</div>
        <div><span>当前工序：</span>{{ result.item.current_process_name || '-' }}</div>
      </div>
    </div>

    <div v-if="result.items?.length" class="card trace-card">
      <div class="card-header"><h3>📦 产品列表 ({{ result.meta?.totals?.items ?? result.items.length }})</h3></div>
      <div class="card-body trace-table-wrap">
        <table class="data-table">
          <thead><tr><th>序列号</th><th>位置</th><th>状态</th><th>当前工序</th><th>创建时间</th></tr></thead>
          <tbody>
            <tr v-for="item in result.items" :key="item.serial_no" class="trace-link-row" title="点击追溯该产品" @click="emit('trace-serial', item.serial_no)">
              <td><code>{{ item.serial_no }}</code></td>
              <td>{{ item.position_no || '-' }}</td>
              <td><span class="badge" :class="getOrderStatus(item.status).cls">{{ getOrderStatus(item.status).label }}</span></td>
              <td>{{ item.current_process_name || '-' }}</td>
              <td>{{ item.created_at }}</td>
            </tr>
          </tbody>
        </table>
      </div>
    </div>

    <div v-if="result.items && pagination.total_pages > 1" class="trace-pagination">
      <button class="btn btn-sm" :disabled="pagination.page <= 1 || searching" title="上一页" @click="emit('page', pagination.page - 1)">←</button>
      <span>第 {{ pagination.page }} / {{ pagination.total_pages }} 页</span>
      <button class="btn btn-sm" :disabled="pagination.page >= pagination.total_pages || searching" title="下一页" @click="emit('page', pagination.page + 1)">→</button>
    </div>

    <button v-if="result.item && result.order" class="trace-order-link" @click="emit('trace-order', result.order.order_no)">
      ← 查看订单 {{ result.order.order_no }} 全部产品
    </button>

    <div v-if="result.order" class="card trace-card">
      <div class="card-header"><h3>📋 关联订单</h3></div>
      <div class="card-body trace-summary">
        <div><span>订单号：</span><code>{{ result.order.order_no }}</code></div>
        <div><span>客户：</span>{{ result.order.customer || '-' }}</div>
        <div><span>产品编码：</span><code>{{ result.order.product_code || '-' }}</code></div>
        <div><span>产品名：</span>{{ result.order.product_name || '-' }}</div>
        <div><span>数量：</span><strong>{{ result.order.quantity }}</strong></div>
        <div><span>已完成：</span><strong class="text-success">{{ result.order.completed || 0 }}</strong></div>
        <div><span>状态：</span><span class="badge" :class="orderStatus.cls">{{ orderStatus.label }}</span></div>
        <div><span>创建时间：</span>{{ result.order.created_at }}</div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { computed } from 'vue'

import { getOrderStatus } from '@/lib/orderStatus.js'

const props = defineProps({
  result: { type: Object, required: true },
  searching: { type: Boolean, default: false },
})
const emit = defineEmits(['trace-serial', 'trace-order', 'page', 'collection-page'])

const pagination = computed(() => (
  props.result.meta?.pagination?.items
  || props.result.meta
  || { page: 1, total_pages: 1 }
))
const historyEvidence = computed(() => {
  const evidence = props.result.meta?.history_evidence || {}
  return {
    hasLegacyFallback: evidence.hasLegacyFallback ?? evidence.has_legacy_fallback ?? false,
    hasMissing: evidence.hasMissing ?? evidence.has_missing ?? false,
  }
})
const collectionLabels = {
  work_records: '报工',
  rework_records: '返工',
  quality_inspections: '质检',
  quality_tasks: '质量任务',
  quality_nonconformances: '不合格品',
  quality_capa: 'CAPA',
  material_consumptions: '物料',
  inventory_logs: '库存',
  shipments: '发货',
}
const collectionPagination = computed(() => {
  const all = props.result.meta?.pagination || {}
  return Object.entries(all)
    .filter(([name, item]) => name !== 'items' && item && item.total_pages > 1)
    .map(([name, item]) => ({
      name,
      label: collectionLabels[name] || name,
      page: item.page,
      perPage: item.per_page,
      total: item.total,
      totalPages: item.total_pages,
    }))
})
const itemStatus = computed(() => getOrderStatus(props.result.item?.status))
const orderStatus = computed(() => getOrderStatus(props.result.order?.status))
</script>

<style scoped>
.trace-mode-label { margin-bottom: var(--space-3); color: var(--primary); font-size: var(--text-sm); font-weight: 600; }
.trace-evidence-banner { display: flex; flex-wrap: wrap; gap: 4px; padding: 10px 12px; margin-bottom: var(--space-4); border-left: 3px solid var(--warning); background: var(--warning-light); color: var(--text-secondary); font-size: var(--text-sm); }
.trace-pagination-banner { border-left-color: var(--primary); background: var(--primary-light); }
.trace-collection-pagination { display: flex; align-items: center; gap: var(--space-2); width: 100%; }
.trace-card { margin-bottom: var(--space-5); }
.trace-summary { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: var(--space-3); font-size: var(--text-base); }
.trace-summary span:first-child { color: var(--text-placeholder); }
.trace-summary code { font-weight: 600; }
.trace-table-wrap { overflow-x: auto; }
.data-table { min-width: 720px; font-size: var(--text-xs); }
.trace-link-row { cursor: pointer; }
.trace-link-row code { color: var(--primary); font-weight: 600; }
.trace-pagination { display: flex; align-items: center; justify-content: flex-end; gap: var(--space-3); margin-bottom: var(--space-5); color: var(--text-placeholder); font-size: var(--text-sm); }
.trace-order-link { margin-bottom: var(--space-3); padding: 0; border: 0; background: transparent; color: var(--primary); cursor: pointer; text-decoration: underline; }
@media (max-width: 720px) { .trace-summary { grid-template-columns: 1fr; } }
</style>
