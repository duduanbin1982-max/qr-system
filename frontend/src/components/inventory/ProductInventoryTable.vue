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
        <button v-if="canExport" class="btn btn-default btn-sm" type="button" @click="$emit('export')">导出当前筛选</button>
      </template>
    </InventoryFilterWorkbench>
    <div v-if="loading" class="product-empty">加载中…</div>
    <div v-else-if="error" class="product-error">{{ error }}</div>
    <div v-else-if="!groups.length" class="product-empty">暂无可聚合的产品库存</div>
    <div v-else class="table-wrap inventory-table-scroll inventory-product-scroll" role="region" aria-label="产品库存表格，可横向和纵向滚动" tabindex="0">
      <table class="data-table product-table inventory-product-table" aria-label="按产品编码汇总的库存">
        <colgroup>
          <col class="inventory-col-product-code">
          <col class="inventory-col-product-name">
          <col class="inventory-col-specification">
          <col class="inventory-col-total">
          <col class="inventory-col-reserved">
          <col class="inventory-col-frozen">
          <col class="inventory-col-available">
          <col class="inventory-col-orders">
          <col class="inventory-col-lots">
          <col class="inventory-col-locations">
          <col class="inventory-col-alert">
          <col class="inventory-col-actions">
        </colgroup>
        <thead>
          <tr>
            <th class="inventory-frozen-cell inventory-frozen--code" scope="col">产品编码</th>
            <th class="inventory-frozen-cell inventory-frozen--name" scope="col">产品名称</th>
            <th class="inventory-frozen-cell inventory-frozen--spec" scope="col">规格</th>
            <th scope="col">总库存</th>
            <th scope="col">预留</th>
            <th scope="col">冻结</th>
            <th scope="col">可用</th>
            <th scope="col">订单数</th>
            <th scope="col">批次数</th>
            <th scope="col">库位数</th>
            <th scope="col">预警</th>
            <th scope="col">操作</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="item in groups" :key="item.product_id">
            <td class="inventory-frozen-cell inventory-frozen--code" :title="item.product_code || '-'"><code>{{ item.product_code || '-' }}</code></td>
            <td class="inventory-frozen-cell inventory-frozen--name" :title="item.product_name || '-'">{{ item.product_name || '-' }}</td>
            <td class="inventory-frozen-cell inventory-frozen--spec" :title="item.specification || '-'">{{ item.specification || '-' }}</td>
            <td>{{ item.quantity ?? 0 }}</td><td>{{ item.reserved_quantity ?? 0 }}</td><td>{{ item.frozen_quantity ?? 0 }}</td>
            <td class="available">{{ item.available_quantity ?? 0 }}</td><td>{{ item.order_count ?? 0 }}</td><td>{{ item.lot_count ?? 0 }}</td><td>{{ item.location_count ?? 0 }}</td>
            <td><span class="status-text" :class="alertClass(item)">{{ alertText(item) }}</span></td>
            <td><button class="btn btn-default btn-sm" type="button" @click="$emit('open-product', item)">查看详情</button></td>
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
})
defineEmits(['search', 'reset', 'change-page', 'change-limit', 'open-product', 'update-filter', 'clear-filter', 'save-filter', 'apply-filter', 'remove-filter', 'export'])
const totalPages = computed(() => Math.max(1, Math.ceil(props.total / props.limit)))
const rangeStart = computed(() => props.total ? (props.page - 1) * props.limit + 1 : 0)
const rangeEnd = computed(() => Math.min(props.page * props.limit, props.total))
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
