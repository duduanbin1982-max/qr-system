<template>
  <section class="inventory-filter-workbench" :aria-label="`${viewLabel}筛选工作台`">
    <div class="inventory-workbench-heading">
      <div>
        <div class="inventory-workbench-title">筛选工作台</div>
        <div class="inventory-workbench-hint">按条件组合筛选，结果和统计会同步更新</div>
      </div>
      <div v-if="resultCount !== null" class="inventory-workbench-result">
        当前结果 <strong>{{ resultCount }}</strong> 条
      </div>
    </div>

    <div class="inventory-filter-grid">
      <label class="inventory-filter-field inventory-filter-keyword">
        <span>关键字</span>
        <input
          :value="filters.keyword || ''"
          class="form-input"
          :placeholder="viewMode === 'product' ? '搜索产品编码或名称' : '搜索型号、名称或订单号'"
          @input="update('keyword', $event.target.value)"
          @keyup.enter="$emit('search')"
        >
      </label>

      <label class="inventory-filter-field">
        <span>库位</span>
        <select :value="filters.location || ''" class="form-input" @change="update('location', $event.target.value)">
          <option value="">全部库位</option>
          <option v-for="option in filterOptions.locations || []" :key="optionValue(option)" :value="optionValue(option)">
            {{ optionLabel(option) }}（{{ option.inventory_count ?? 0 }}）
          </option>
        </select>
      </label>

      <label class="inventory-filter-field">
        <span>质量状态</span>
        <select :value="filters.quality_status || ''" class="form-input" @change="update('quality_status', $event.target.value)">
          <option value="">全部质量状态</option>
          <option v-for="option in filterOptions.quality_statuses || []" :key="optionValue(option)" :value="optionValue(option)">
            {{ qualityLabel(option) }}（{{ option.inventory_count ?? 0 }}）
          </option>
        </select>
      </label>

      <details class="inventory-filter-field inventory-spec-dropdown">
        <summary>规格 <span v-if="selectedSpecifications.length" class="inventory-filter-count">{{ selectedSpecifications.length }}</span></summary>
        <div class="inventory-spec-options">
          <label v-for="option in filterOptions.specifications || []" :key="optionValue(option)" class="inventory-spec-option">
            <input
              type="checkbox"
              :checked="selectedSpecifications.includes(optionValue(option))"
              @change="toggleSpecification(optionValue(option))"
            >
            <span>{{ optionLabel(option) }}</span>
            <small>{{ option.inventory_count ?? 0 }}</small>
          </label>
          <span v-if="!(filterOptions.specifications || []).length" class="inventory-filter-empty">暂无规格选项</span>
        </div>
      </details>

      <label class="inventory-filter-check">
        <input :checked="Boolean(filters.low_stock)" type="checkbox" @change="update('low_stock', $event.target.checked)">
        <span>仅低库存</span>
      </label>

      <div class="inventory-filter-actions">
        <button class="btn btn-primary btn-sm" type="button" :disabled="loading" @click="$emit('search')">查询</button>
        <button class="btn btn-default btn-sm" type="button" :disabled="loading" @click="$emit('reset')">清除</button>
        <slot name="actions" />
      </div>
    </div>

    <div v-if="chips.length" class="inventory-selected-filters" aria-label="已选筛选条件">
      <span class="inventory-selected-label">已选条件</span>
      <button v-for="(chip, index) in chips" :key="`${chip.key}-${index}`" class="inventory-filter-chip" type="button" @click="$emit('clear-filter', { key: chip.key, value: chip.rawValue })">
        {{ chip.label }}：{{ chip.value }} <span aria-hidden="true">×</span>
      </button>
      <button class="inventory-clear-all" type="button" @click="$emit('reset')">全部清除</button>
    </div>

    <div class="inventory-saved-filters">
      <span class="inventory-saved-label">保存筛选</span>
      <input v-model="saveName" class="form-input" placeholder="例如：待出库-东库" @keyup.enter="savePreset">
      <button class="btn btn-default btn-sm" type="button" :disabled="!saveName.trim()" @click="savePreset">保存当前条件</button>
      <select v-if="savedFilters.length" v-model="selectedPresetId" class="form-input inventory-saved-select" aria-label="已保存筛选">
        <option value="">选择已保存筛选</option>
        <option v-for="preset in savedFilters" :key="preset.id" :value="preset.id">{{ preset.name }}</option>
      </select>
      <button v-if="selectedPresetId" class="btn btn-default btn-sm" type="button" @click="applyPreset">恢复</button>
      <button v-if="selectedPresetId" class="btn btn-link btn-sm inventory-delete-preset" type="button" @click="removePreset">删除</button>
    </div>
  </section>
</template>

<script setup>
import { computed, ref } from 'vue'

const props = defineProps({
  viewMode: { type: String, default: 'order' },
  filters: { type: Object, required: true },
  filterOptions: { type: Object, default: () => ({}) },
  savedFilters: { type: Array, default: () => [] },
  resultCount: { type: [Number, String], default: null },
  loading: Boolean,
})

const emit = defineEmits(['search', 'reset', 'update-filter', 'clear-filter', 'save-filter', 'apply-filter', 'remove-filter'])
const saveName = ref('')
const selectedPresetId = ref('')
const viewLabel = computed(() => props.viewMode === 'product' ? '产品编码' : '订单')
const selectedSpecifications = computed(() => Array.isArray(props.filters.specifications) ? props.filters.specifications : [])

function optionValue(option) { return typeof option === 'string' ? option : (option?.value || '__empty__') }
function optionLabel(option) { return optionValue(option) === '__empty__' ? '未填写规格' : optionValue(option) }
function qualityLabel(option) {
  const value = optionValue(option)
  return ({ qualified: '合格', hold: '冻结/待检' })[value] || value
}
function update(key, value) { emit('update-filter', { key, value }) }
function toggleSpecification(value) {
  const next = selectedSpecifications.value.includes(value)
    ? selectedSpecifications.value.filter(item => item !== value)
    : [...selectedSpecifications.value, value]
  update('specifications', next)
}
function savePreset() {
  const name = saveName.value.trim()
  if (!name) return
  emit('save-filter', name)
  saveName.value = ''
}
function applyPreset() {
  const preset = props.savedFilters.find(item => item.id === selectedPresetId.value)
  if (preset) emit('apply-filter', preset)
}
function removePreset() {
  if (!selectedPresetId.value) return
  emit('remove-filter', selectedPresetId.value)
  selectedPresetId.value = ''
}

const chips = computed(() => {
  const result = []
  if (props.filters.keyword) result.push({ key: 'keyword', label: '关键字', value: props.filters.keyword, rawValue: props.filters.keyword })
  if (props.filters.location) result.push({ key: 'location', label: '库位', value: props.filters.location, rawValue: props.filters.location })
  if (props.filters.quality_status) result.push({ key: 'quality_status', label: '质量状态', value: qualityLabel({ value: props.filters.quality_status }), rawValue: props.filters.quality_status })
  if (props.filters.low_stock) result.push({ key: 'low_stock', label: '库存', value: '仅低库存', rawValue: true })
  selectedSpecifications.value.forEach(value => {
    result.push({ key: 'specifications', label: '规格', value: optionLabel({ value }), rawValue: value })
  })
  return result
})
</script>

<style scoped>
.inventory-filter-workbench { padding: 16px; background: var(--bg-table-stripe); border-bottom: 1px solid var(--border-light); }
.inventory-workbench-heading { display:flex; align-items:center; justify-content:space-between; gap:16px; margin-bottom:12px; }
.inventory-workbench-title { color:var(--text-primary); font-weight:700; font-size:15px; }
.inventory-workbench-hint { margin-top:3px; color:var(--text-muted); font-size:12px; }
.inventory-workbench-result { color:var(--text-secondary); font-size:13px; white-space:nowrap; }
.inventory-workbench-result strong { color:var(--primary); }
.inventory-filter-grid { display:flex; flex-wrap:wrap; align-items:flex-end; gap:10px; }
.inventory-filter-field { display:flex; flex-direction:column; gap:5px; min-width:150px; }
.inventory-filter-field > span, .inventory-filter-check, .inventory-saved-label, .inventory-selected-label { color:var(--text-secondary); font-size:12px; }
.inventory-filter-keyword { min-width:230px; flex:1 1 230px; }
.inventory-filter-field .form-input { min-height:34px; padding:6px 9px; font-size:13px; }
.inventory-filter-check { display:flex; align-items:center; gap:6px; min-height:34px; padding:0 8px; white-space:nowrap; }
.inventory-filter-check input { accent-color:var(--danger); }
.inventory-filter-actions { display:flex; align-items:center; flex-wrap:wrap; gap:7px; min-height:34px; }
.inventory-spec-dropdown { position:relative; min-width:180px; }
.inventory-spec-dropdown summary { display:flex; align-items:center; justify-content:space-between; min-height:34px; padding:8px 10px; border:1px solid var(--border-light); border-radius:var(--radius-md); background:#fff; color:var(--text-secondary); font-size:13px; cursor:pointer; list-style:none; }
.inventory-spec-dropdown summary::-webkit-details-marker { display:none; }
.inventory-filter-count { display:inline-flex; align-items:center; justify-content:center; min-width:20px; height:20px; padding:0 5px; border-radius:10px; background:var(--primary-light); color:var(--primary); font-size:11px; font-weight:700; }
.inventory-spec-options { position:absolute; z-index:30; top:calc(100% + 5px); left:0; width:260px; max-height:260px; overflow:auto; padding:8px; border:1px solid var(--border-light); border-radius:var(--radius-md); background:#fff; box-shadow:0 8px 24px rgba(15,23,42,.14); }
.inventory-spec-option { display:flex; align-items:center; gap:8px; padding:7px 6px; border-radius:5px; color:var(--text-secondary); font-size:13px; cursor:pointer; }
.inventory-spec-option:hover { background:var(--bg-hover); }
.inventory-spec-option small { margin-left:auto; color:var(--text-muted); }
.inventory-filter-empty { display:block; padding:8px; color:var(--text-muted); font-size:12px; }
.inventory-selected-filters, .inventory-saved-filters { display:flex; align-items:center; flex-wrap:wrap; gap:7px; margin-top:12px; }
.inventory-selected-label, .inventory-saved-label { font-weight:600; }
.inventory-filter-chip { border:1px solid var(--primary-light); border-radius:999px; padding:5px 9px; background:var(--primary-light); color:var(--primary); font-size:12px; cursor:pointer; }
.inventory-clear-all { border:0; background:transparent; color:var(--danger); font-size:12px; cursor:pointer; }
.inventory-saved-filters { padding-top:10px; border-top:1px dashed var(--border-light); }
.inventory-saved-filters .form-input { min-height:31px; width:180px; padding:5px 8px; font-size:12px; }
.inventory-saved-select { min-width:190px; }
.inventory-delete-preset { color:var(--danger); }
@media (max-width: 700px) {
  .inventory-workbench-heading { align-items:flex-start; flex-direction:column; gap:5px; }
  .inventory-filter-field, .inventory-filter-keyword { min-width:100%; flex-basis:100%; }
  .inventory-filter-actions { width:100%; }
  .inventory-spec-options { position:fixed; left:16px; right:16px; width:auto; }
}
</style>
