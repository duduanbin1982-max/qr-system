<template>
  <div class="price-version-page">
    <header class="page-toolbar">
      <div>
        <h3>工价版本</h3>
        <p>按路线修订版和工序修订版建立精确工价</p>
      </div>
      <div class="toolbar-actions">
        <label class="search-field">
          <span class="sr-only">搜索路线或工序</span>
          <input v-model.trim="query" class="form-input" placeholder="搜索路线或工序">
        </label>
        <button
          type="button"
          class="icon-button"
          title="刷新"
          aria-label="刷新"
          :disabled="loading"
          @click="refresh"
        >↻</button>
      </div>
    </header>

    <div class="summary-band" aria-label="工价版本概况">
      <div><span>已发布节点</span><strong>{{ publishedRows.length }}</strong></div>
      <div><span>待发布节点</span><strong>{{ pendingRows.length }}</strong></div>
      <div><span>待处理草稿</span><strong>{{ draftCount }}</strong></div>
      <div><span>已作废记录</span><strong>{{ voidedPrices.length }}</strong></div>
    </div>

    <nav class="view-switch" role="tablist" aria-label="工价版本视图">
      <button
        v-for="option in viewOptions"
        :key="option.value"
        type="button"
        role="tab"
        :data-testid="`view-${option.value}`"
        :class="{ active: viewMode === option.value }"
        :aria-selected="viewMode === option.value"
        @click="viewMode = option.value"
      >{{ option.label }}</button>
    </nav>

    <div v-if="viewMode === 'pending-route'" class="pending-notice">
      本工价绑定待发布路线，不能单独批准，只能随路线成组发布。
    </div>

    <div v-if="loading" class="empty-state">正在加载工价版本...</div>

    <template v-else-if="viewMode !== 'voided'">
      <div v-if="!groupedRows.length" class="empty-state">没有符合条件的精确路线工序</div>
      <section
        v-for="group in groupedRows"
        v-else
        :key="group.route_version_id"
        class="route-version-group"
      >
        <div class="group-heading">
          <div>
            <strong>{{ routeLabel(group.rows[0]) }}</strong>
            <span>{{ group.rows[0].route_category || '未分类' }} · {{ group.rows.length }} 道工序</span>
          </div>
          <span class="version-state">{{ group.rows[0].route_version_status === 'published' ? '已发布' : '待审批' }}</span>
        </div>
        <div class="table-wrap">
          <table class="data-table price-table">
            <thead>
              <tr>
                <th class="sequence-column">序号</th>
                <th>工序及版本</th>
                <th>精确绑定</th>
                <th class="price-column">正常工价</th>
                <th>审批方式</th>
                <th class="action-column">操作</th>
              </tr>
            </thead>
            <tbody>
              <tr
                v-for="row in group.rows"
                :key="row.key"
                :data-testid="`reference-row-${row.key}`"
              >
                <td>{{ row.seq_order }}</td>
                <td>
                  <strong>{{ row.process_name }}</strong>
                  <small>工序 V{{ row.process_version }} · {{ row.process_version_status === 'published' ? '已发布' : '待审批' }}</small>
                </td>
                <td class="binding-cell">
                  <code>{{ row.route_version_id }}:{{ row.process_version_id }}</code>
                </td>
                <td>
                  <strong v-if="row.draft" class="price-value">{{ unitPrice(row.draft.normal_unit_price_micros) }}</strong>
                  <strong v-else-if="row.current" class="price-value">{{ unitPrice(row.current.normal_unit_price_micros) }}</strong>
                  <span v-else class="missing-value">缺少工价</span>
                  <small v-if="row.draft">草稿 · {{ row.draft.created_by_name || '-' }}</small>
                  <small v-else-if="row.current">{{ formatDateTime(row.current.valid_from) }} 起</small>
                </td>
                <td>
                  <span class="approval-mode" :class="{ grouped: row.pricing_mode === 'pending_group_release' }">
                    {{ approvalMode(row) }}
                  </span>
                </td>
                <td>
                  <div class="row-actions">
                    <button
                      v-if="canPrepare && row.draft"
                      type="button"
                      class="btn btn-default btn-sm"
                      :data-testid="`edit-price-${row.draft.id}`"
                      @click="openEditor(row)"
                    >查看草稿</button>
                    <button
                      v-else-if="canPrepare"
                      type="button"
                      class="btn btn-primary btn-sm"
                      :data-testid="`create-price-${row.key}`"
                      @click="openEditor(row)"
                    >{{ row.current ? '调价' : '建立工价' }}</button>
                    <button
                      v-if="canApprove && row.draft && row.route_version_status === 'published'"
                      type="button"
                      class="btn btn-primary btn-sm"
                      :data-testid="`approve-price-${row.draft.id}`"
                      :disabled="approving"
                      @click="approveDraft(row.draft)"
                    >批准</button>
                  </div>
                </td>
              </tr>
            </tbody>
          </table>
        </div>
      </section>
    </template>

    <div v-else class="table-wrap voided-table-wrap">
      <div v-if="!filteredVoidedPrices.length" class="empty-state">没有已作废工价记录</div>
      <table v-else class="data-table price-table voided-table">
        <thead>
          <tr><th>路线 / 工序版本</th><th>原工价</th><th>作废原因</th><th>作废时间</th><th>操作人</th></tr>
        </thead>
        <tbody>
          <tr v-for="price in filteredVoidedPrices" :key="price.id">
            <td>
              <strong>{{ price.route_name || `路线 ${price.route_id}` }}</strong>
              <small>{{ price.process_name || `工序 ${price.process_id}` }} · {{ price.route_version_id }}:{{ price.process_version_id }}</small>
            </td>
            <td><strong>{{ unitPrice(price.normal_unit_price_micros) }}</strong></td>
            <td>{{ price.void_reason || '-' }}</td>
            <td>{{ formatDateTime(price.voided_at) }}</td>
            <td>{{ price.voided_by_name || '-' }}</td>
          </tr>
        </tbody>
      </table>
    </div>

    <PriceVersionEditor
      :open="editorOpen"
      :reference="selectedRow"
      :current-price="selectedRow?.current || null"
      :draft-price="selectedRow?.draft || null"
      @created="handleEditorResult"
      @voided="handleEditorResult"
      @close="closeEditor"
    />
  </div>
</template>

<script setup>
import { computed, onMounted, ref } from 'vue'

import PriceVersionEditor from '@/components/wage/PriceVersionEditor.vue'
import {
  priceReferenceKey,
  useRoutePriceVersions,
} from '@/composables/useRoutePriceVersions.js'
import { api } from '@/lib/api.js'
import { can } from '@/lib/auth.js'
import { showToast } from '@/lib/store.js'


const {
  references,
  versions,
  loading,
  load,
  selectReference,
} = useRoutePriceVersions()

const query = ref('')
const viewMode = ref('published')
const editorOpen = ref(false)
const selectedRow = ref(null)
const approving = ref(false)

const canPrepare = computed(() => can('wages:prepare'))
const canApprove = computed(() => can('wages:approve'))
const viewOptions = [
  { value: 'published', label: '当前已发布' },
  { value: 'pending-route', label: '待发布路线' },
  { value: 'voided', label: '已作废记录' },
]

const versionsByReference = computed(() => {
  const grouped = new Map()
  for (const price of versions.value) {
    const key = priceReferenceKey(price)
    if (!grouped.has(key)) grouped.set(key, [])
    grouped.get(key).push(price)
  }
  for (const prices of grouped.values()) {
    prices.sort((a, b) => `${b.valid_from || ''}:${b.id}`.localeCompare(`${a.valid_from || ''}:${a.id}`))
  }
  return grouped
})

const referenceRows = computed(() => references.value.map(reference => {
  const key = priceReferenceKey(reference)
  const prices = versionsByReference.value.get(key) || []
  return {
    ...reference,
    key,
    current: prices.find(price => price.status === 'approved') || null,
    draft: prices.find(price => price.status === 'draft') || null,
  }
}))

const publishedRows = computed(() => referenceRows.value.filter(
  row => row.route_version_status === 'published'
))
const pendingRows = computed(() => referenceRows.value.filter(
  row => row.route_version_status === 'pending_approval'
))
const voidedPrices = computed(() => versions.value.filter(price => price.status === 'voided'))
const draftCount = computed(() => referenceRows.value.filter(row => row.draft).length)

function matchesSearch(item) {
  if (!query.value) return true
  const text = [
    item.route_name,
    item.process_name,
    item.route_version_id,
    item.process_version_id,
  ].filter(Boolean).join(' ').toLocaleLowerCase('zh-CN')
  return text.includes(query.value.toLocaleLowerCase('zh-CN'))
}

const displayedRows = computed(() => (
  viewMode.value === 'pending-route' ? pendingRows.value : publishedRows.value
).filter(matchesSearch))

const groupedRows = computed(() => {
  const groups = new Map()
  for (const row of displayedRows.value) {
    if (!groups.has(row.route_version_id)) {
      groups.set(row.route_version_id, {
        route_version_id: row.route_version_id,
        rows: [],
      })
    }
    groups.get(row.route_version_id).rows.push(row)
  }
  return [...groups.values()]
})

const filteredVoidedPrices = computed(() => voidedPrices.value.filter(matchesSearch))

function routeLabel(row) {
  const state = row.route_version_status === 'published' ? '当前' : '待发布'
  return `${row.route_name} · ${state} V${row.route_version}`
}

function approvalMode(row) {
  return row.pricing_mode === 'pending_group_release' ? '成组发布批准' : '独立审批'
}

function unitPrice(value) {
  return `¥${(Number(value || 0) / 10000).toFixed(4)}`
}

function formatDateTime(value) {
  return value ? String(value).replace('T', ' ').slice(0, 16) : '-'
}

function openEditor(row) {
  selectReference(row)
  selectedRow.value = row
  editorOpen.value = true
}

function closeEditor() {
  editorOpen.value = false
  selectedRow.value = null
}

async function refresh() {
  try {
    await load()
  } catch (error) {
    showToast(error.message || '工价版本加载失败', 'error')
  }
}

async function handleEditorResult() {
  closeEditor()
  await refresh()
}

async function approveDraft(price) {
  if (approving.value) return
  approving.value = true
  try {
    await api.domains.wages.approveRoutePriceVersion(price.id, price.row_version)
    showToast('工价版本已批准')
    await refresh()
  } catch (error) {
    showToast(error.message || '批准工价失败', 'error')
  } finally {
    approving.value = false
  }
}

onMounted(refresh)
</script>

<style scoped>
.price-version-page{min-width:0}.page-toolbar{display:flex;align-items:flex-start;justify-content:space-between;gap:16px;margin-bottom:14px}.page-toolbar h3{margin:0;font-size:18px}.page-toolbar p{margin:4px 0 0;color:var(--text-placeholder);font-size:12px}.toolbar-actions{display:flex;align-items:center;gap:8px}.search-field .form-input{width:240px}.icon-button{display:inline-flex;align-items:center;justify-content:center;width:34px;height:34px;border:1px solid var(--border);border-radius:6px;background:var(--bg-surface);color:var(--text-secondary);font-size:20px;cursor:pointer}.icon-button:disabled{opacity:.55;cursor:not-allowed}.sr-only{position:absolute;width:1px;height:1px;padding:0;margin:-1px;overflow:hidden;clip:rect(0,0,0,0);white-space:nowrap;border:0}.summary-band{display:grid;grid-template-columns:repeat(4,minmax(110px,1fr));margin-bottom:14px;border-block:1px solid var(--border-light)}.summary-band div{padding:10px 14px;border-right:1px solid var(--border-light)}.summary-band div:last-child{border-right:0}.summary-band span{display:block;color:var(--text-placeholder);font-size:12px}.summary-band strong{display:block;margin-top:2px;font-size:19px}.view-switch{display:inline-flex;margin-bottom:12px;padding:3px;border:1px solid var(--border-light);border-radius:7px;background:var(--bg-secondary)}.view-switch button{min-height:30px;padding:5px 13px;border:0;border-radius:5px;background:transparent;color:var(--text-secondary);cursor:pointer}.view-switch button.active{background:var(--bg-surface);color:var(--primary);box-shadow:var(--shadow-sm);font-weight:600}.pending-notice{margin-bottom:12px;padding:9px 12px;border-left:3px solid #d59b00;background:#fff8df;color:#755500;font-size:13px}.route-version-group{margin-bottom:18px}.group-heading{display:flex;align-items:center;justify-content:space-between;gap:12px;padding:8px 2px;border-bottom:1px solid var(--border)}.group-heading div{display:flex;align-items:baseline;gap:10px}.group-heading span{color:var(--text-placeholder);font-size:12px}.version-state{padding:2px 7px;border:1px solid var(--border);border-radius:4px;color:var(--text-secondary)!important}.table-wrap{overflow-x:auto;border-bottom:1px solid var(--border-light)}.price-table{width:100%;min-width:860px}.price-table th{white-space:nowrap}.price-table td{vertical-align:middle}.price-table small{display:block;margin-top:3px;color:var(--text-placeholder);font-size:11px}.sequence-column{width:64px}.price-column{width:160px}.action-column{width:190px}.binding-cell code{font-size:12px}.price-value{font-size:15px}.missing-value{color:var(--danger);font-weight:600}.approval-mode{display:inline-block;padding:3px 7px;border-radius:4px;background:var(--primary-light);color:var(--primary);font-size:12px}.approval-mode.grouped{background:#fff3cf;color:#7a5600}.row-actions{display:flex;align-items:center;gap:6px;min-height:32px}.empty-state{padding:36px 16px;color:var(--text-placeholder);text-align:center}.voided-table-wrap{border-top:1px solid var(--border-light)}.voided-table{min-width:780px}
@media(max-width:760px){.page-toolbar{align-items:stretch;flex-direction:column}.toolbar-actions{width:100%}.search-field{flex:1}.search-field .form-input{width:100%}.summary-band{grid-template-columns:repeat(2,1fr)}.summary-band div:nth-child(2){border-right:0}.group-heading{align-items:flex-start}.group-heading div{align-items:flex-start;flex-direction:column;gap:2px}.view-switch{display:flex;width:100%;overflow-x:auto}.view-switch button{flex:1;white-space:nowrap}}
</style>
