<template>
  <div class="product-inventory-panel">
    <InventoryFilterWorkbench
      view-mode="product"
      :filters="filters"
      :filter-options="filterOptions"
      :saved-filters="savedFilters"
      :result-count="total"
      :loading="loading"
      @search="$emit('search')"
      @reset="$emit('reset')"
      @update-filter="$emit('update-filter', $event)"
      @clear-filter="$emit('clear-filter', $event)"
      @save-filter="$emit('save-filter', $event)"
      @apply-filter="$emit('apply-filter', $event)"
      @remove-filter="$emit('remove-filter', $event)"
    >
      <template #actions>
        <InventoryColumnConfigurator
          :columns="columns"
          :visible-keys="visibleColumns"
          @update="$emit('update-columns', $event)"
          @reset="$emit('reset-columns')"
        />
        <label class="inventory-page-select" title="选择当前页">
          <input type="checkbox" :checked="allPageSelected" :disabled="!groups.length" @change="$emit('toggle-select-all')">
          选择当前页
        </label>
        <span v-if="selectedCount" class="inventory-selection-count">已选 {{ selectedCount }} 项</span>
        <button v-if="canExport && selectedCount" class="btn btn-default btn-sm" type="button" @click="$emit('batch-export')">批量导出</button>
        <button v-if="canExport" class="btn btn-default btn-sm" type="button" @click="$emit('export')">导出当前筛选</button>
      </template>
    </InventoryFilterWorkbench>
    <div v-if="loading" class="product-empty">加载中…</div>
    <div v-else-if="error" class="product-error">{{ error }}</div>
    <div v-else-if="!groups.length" class="product-empty">暂无可聚合的产品库存</div>
    <div v-else class="table-wrap inventory-table-scroll inventory-product-scroll" role="region" aria-label="产品库存表格，可横向和纵向滚动" tabindex="0">
      <table class="data-table product-table inventory-product-table" aria-label="按产品编码汇总的库存">
        <colgroup>
          <col v-for="column in visibleColumnDefs" :key="column.key" :class="columnClass(column.key)">
        </colgroup>
        <thead>
          <tr>
            <th v-for="(column, index) in visibleColumnDefs" :key="column.key" :class="cellClass(column.key, index)" scope="col" :aria-sort="ariaSort(column.key)">
              <button v-if="column.key !== 'actions'" class="inventory-sort-button" type="button" @click="$emit('sort', column.key)">
                {{ column.label }}<span class="inventory-sort-indicator" aria-hidden="true">{{ sortIndicator(column.key) }}</span>
              </button>
              <span v-else>{{ column.label }}</span>
            </th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="item in groups" :key="item.product_id">
            <td v-for="(column, index) in visibleColumnDefs" :key="column.key" :class="cellClass(column.key, index)" :title="cellTitle(item, column.key)">
              <template v-if="column.key === 'product_code'"><input class="inventory-row-select" type="checkbox" :checked="selectedIds.includes(item.product_id)" :aria-label="`选择 ${item.product_code || item.product_id}`" @click.stop @change="$emit('toggle-select', item.product_id)"><code>{{ item.product_code || '-' }}</code></template>
              <template v-else-if="column.key === 'product_name'">{{ item.product_name || '-' }}</template>
              <template v-else-if="column.key === 'specification'">{{ item.specification || '-' }}</template>
              <template v-else-if="column.key === 'available_quantity'"><span class="available">{{ item.available_quantity ?? 0 }}</span></template>
              <template v-else-if="column.key === 'alert'"><span class="status-text" :class="alertClass(item)">{{ alertText(item) }}</span></template>
              <template v-else-if="column.key === 'actions'"><button class="btn btn-default btn-sm" type="button" @click="$emit('open-product', item)">查看详情</button></template>
              <template v-else>{{ item[column.key] ?? 0 }}</template>
            </td>
          </tr>
        </tbody>
      </table>
    </div>
    <div v-if="!loading && !error && total > 0" class="product-pagination" aria-label="产品库存分页">
      <span class="product-total">共 {{ total }} 个产品，当前显示 {{ rangeStart }}–{{ rangeEnd }}</span>
      <label class="product-page-size">
        每页
        <select :value="limit" class="form-input" @change="$emit('change-limit', Number($event.target.value))">
          <option :value="50">50</option>
          <option :value="100">100</option>
          <option :value="200">200</option>
        </select>
      </label>
      <button class="btn btn-default btn-sm" :disabled="page <= 1" @click="$emit('change-page', page - 1)">上一页</button>
      <span class="product-page-current">第 {{ page }} / {{ totalPages }} 页</span>
      <button class="btn btn-default btn-sm" :disabled="page >= totalPages" @click="$emit('change-page', page + 1)">下一页</button>
    </div>
  </div>
</template>

<script setup>
import { computed } from 'vue'
import InventoryFilterWorkbench from './InventoryFilterWorkbench.vue'
import InventoryColumnConfigurator from './InventoryColumnConfigurator.vue'

const props = defineProps({
  groups: { type: Array, default: () => [] },
  filters: { type: Object, required: true },
  filterOptions: { type: Object, default: () => ({ specifications: [] }) },
  savedFilters: { type: Array, default: () => [] },
  canExport: Boolean,
  loading: Boolean,
  error: { type: String, default: '' },
  total: { type: Number, default: 0 },
  page: { type: Number, default: 1 },
  limit: { type: Number, default: 200 },
  columns: { type: Array, default: () => [] },
  visibleColumns: { type: Array, default: () => [] },
  selectedIds: { type: Array, default: () => [] },
  selectedCount: { type: Number, default: 0 },
  sortBy: { type: String, default: 'alert' },
  sortDir: { type: String, default: 'desc' },
})
defineEmits(['search', 'reset', 'change-page', 'change-limit', 'open-product', 'update-filter', 'clear-filter', 'save-filter', 'apply-filter', 'remove-filter', 'export', 'batch-export', 'update-columns', 'reset-columns', 'toggle-select-all', 'toggle-select', 'sort'])
const totalPages = computed(() => Math.max(1, Math.ceil(props.total / props.limit)))
const rangeStart = computed(() => props.total ? (props.page - 1) * props.limit + 1 : 0)
const rangeEnd = computed(() => Math.min(props.page * props.limit, props.total))
const columns = computed(() => props.columns.length ? props.columns : [
  { key: 'product_code', label: '产品编码', required: true }, { key: 'product_name', label: '产品名称', required: true }, { key: 'specification', label: '规格', required: true }, { key: 'quantity', label: '总库存' }, { key: 'reserved_quantity', label: '预留' }, { key: 'frozen_quantity', label: '冻结' }, { key: 'available_quantity', label: '可用' }, { key: 'order_count', label: '订单数' }, { key: 'lot_count', label: '批次数' }, { key: 'location_count', label: '库位数' }, { key: 'alert', label: '预警' }, { key: 'actions', label: '操作', required: true },
])
const visibleColumnDefs = computed(() => columns.value.filter(column => props.visibleColumns.length ? props.visibleColumns.includes(column.key) : true))
const allPageSelected = computed(() => props.groups.length > 0 && props.groups.every(item => props.selectedIds.includes(item.product_id)))
function columnClass(key) {
  return {
    product_code: 'inventory-col-product-code',
    product_name: 'inventory-col-product-name',
    specification: 'inventory-col-specification',
    quantity: 'inventory-col-total',
    reserved_quantity: 'inventory-col-reserved',
    frozen_quantity: 'inventory-col-frozen',
    available_quantity: 'inventory-col-available',
    order_count: 'inventory-col-orders',
    lot_count: 'inventory-col-lots',
    location_count: 'inventory-col-locations',
    alert: 'inventory-col-alert',
    actions: 'inventory-col-actions',
  }[key] || ''
}
function cellClass(key) {
  return key === 'product_code' ? 'inventory-frozen-cell inventory-frozen--code'
    : key === 'product_name' ? 'inventory-frozen-cell inventory-frozen--name'
      : key === 'specification' ? 'inventory-frozen-cell inventory-frozen--spec' : ''
}
function cellTitle(item, key) { return ['product_code', 'product_name', 'specification'].includes(key) ? (item[key] || '-') : undefined }
function sortIndicator(key) { return props.sortBy === key ? (props.sortDir === 'asc' ? ' ↑' : ' ↓') : '' }
function ariaSort(key) { return props.sortBy === key ? (props.sortDir === 'asc' ? 'ascending' : 'descending') : 'none' }
function alertText(item) { return item.product_alert_level === 'out_of_stock' ? '缺货' : item.product_alert_level === 'low' ? '低库存' : item.product_alert_level === 'attention' ? '关注' : '正常' }
function alertClass(item) { return `status-${item.product_alert_level || 'normal'}` }
</script>

<style scoped>
.product-toolbar { display:flex; flex-wrap:wrap; gap:8px; align-items:center; padding:12px; background:var(--bg-table-stripe); border-bottom:1px solid var(--border-light); }
.product-toolbar input.form-input { min-width:220px; }.specification-filter { min-width:150px; min-height:58px; }
.product-toolbar label { font-size:13px; color:var(--text-secondary); }
.product-empty,.product-error { padding:48px 16px; text-align:center; color:var(--text-muted); }
.product-error { color:var(--danger); }
.product-table th,.product-table td { white-space:nowrap; }
.inventory-sort-button { border:0; background:transparent; color:inherit; font:inherit; font-weight:600; cursor:pointer; padding:0; white-space:nowrap; }
.inventory-sort-button:hover { color:var(--primary); }.inventory-sort-indicator { color:var(--primary); font-weight:700; }
.inventory-page-select { display:inline-flex; align-items:center; gap:5px; color:var(--text-secondary); font-size:12px; white-space:nowrap; }.inventory-selection-count { color:var(--primary); font-size:12px; font-weight:600; white-space:nowrap; }
.available { font-weight:700; color:var(--success); }.status-text { font-size:12px; font-weight:600; }
.status-normal { color:var(--success); }.status-attention { color:var(--warning); }.status-low,.status-out_of_stock { color:var(--danger); }
.product-pagination { display:flex; align-items:center; justify-content:flex-end; flex-wrap:wrap; gap:10px; padding:12px 16px; border-top:1px solid var(--border-light); background:var(--bg-table-stripe); }
.product-total { margin-right:auto; color:var(--text-secondary); font-size:13px; }
.product-page-size { display:flex; align-items:center; gap:6px; color:var(--text-secondary); font-size:13px; }
.product-page-size .form-input { width:76px; padding:5px 8px; }
.product-page-current { min-width:76px; text-align:center; color:var(--text-secondary); font-size:13px; }
@media (max-width: 700px) {
  .product-toolbar input.form-input { min-width:100%; }
  .product-pagination { justify-content:center; }
  .product-total { width:100%; margin-right:0; text-align:center; }
}
</style>
