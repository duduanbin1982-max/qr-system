<template>
  <div class="price-version-page">
    <div class="price-toolbar">
      <div>
        <h3>工价版本</h3>
        <p>路线工序工价</p>
      </div>
      <div class="price-actions">
        <label class="search-field">
          <span class="sr-only">搜索路线或工序</span>
          <input v-model.trim="query" class="form-input" placeholder="搜索路线或工序">
        </label>
        <select v-if="viewMode !== 'current'" v-model="category" class="form-input category-select" aria-label="路线分类">
          <option value="">全部分类</option>
          <option v-for="item in categoryOptions" :key="item" :value="item">{{ item }}</option>
        </select>
        <button class="icon-button" type="button" title="刷新" aria-label="刷新" :disabled="loading" @click="load">&#8635;</button>
        <button v-if="canPrepare" class="btn btn-primary btn-sm" type="button" @click="openCreate()">新增工价</button>
      </div>
    </div>

    <div class="price-summary" aria-label="工价概况">
      <div><span>当前有效</span><strong>{{ currentCount }}</strong></div>
      <div><span>待审批</span><strong :class="{ 'text-warning': pendingCount }">{{ pendingCount }}</strong></div>
      <div><span>待生效</span><strong>{{ upcomingCount }}</strong></div>
      <div><span>未设置</span><strong :class="{ 'text-danger': missingCount }">{{ missingCount }}</strong></div>
    </div>

    <div class="view-row">
      <div class="view-switch" role="tablist" aria-label="工价视图">
        <button
          v-for="item in viewOptions"
          :key="item.value"
          type="button"
          role="tab"
          :data-testid="`view-${item.value}`"
          :class="{ active: viewMode === item.value }"
          :aria-selected="viewMode === item.value"
          @click="viewMode = item.value"
        >
          {{ item.label }}<span v-if="item.value === 'pending' && pendingCount" class="view-count">{{ pendingCount }}</span>
        </button>
      </div>
      <select v-if="viewMode === 'history'" v-model="historyStatus" class="form-input history-filter" aria-label="版本状态">
        <option value="">全部状态</option>
        <option value="draft">草稿</option>
        <option value="approved">已批准</option>
        <option value="retired">已结束</option>
      </select>
    </div>

    <div v-if="viewMode === 'current'" class="route-category-tabs" role="tablist" aria-label="路线分类">
      <button
        v-for="item in categoryTabOptions"
        :key="item.value"
        type="button"
        role="tab"
        :class="{ active: category === item.value }"
        :aria-selected="category === item.value"
        @click="category = item.value"
      >
        <span>{{ item.icon }}</span>{{ item.label }}<strong>{{ item.count }}</strong>
      </button>
    </div>

    <div class="price-table-wrap">
      <div v-if="loading" class="price-empty">正在加载工价...</div>

      <template v-else-if="viewMode === 'current'">
        <div v-if="!currentRouteGroups.length" class="price-empty">没有符合条件的路线工序</div>
        <div v-else class="route-price-list">
          <section
            v-for="(group, index) in currentRouteGroups"
            :key="group.route_id"
            class="route-price-card"
            :class="{ expanded: expandedRoute === group.route_id }"
            :data-testid="`route-price-card-${group.route_id}`"
          >
            <button type="button" class="route-price-card-header" :aria-expanded="expandedRoute === group.route_id" @click="toggleRoute(group.route_id)">
              <span class="route-index">{{ index + 1 }}</span>
              <span class="route-chevron" aria-hidden="true">{{ expandedRoute === group.route_id ? '▼' : '▶' }}</span>
              <span class="route-card-title">
                <strong>{{ group.route_name }}</strong>
                <small>{{ group.route_category || '未分类' }} · {{ group.rows.length }} 道工序</small>
              </span>
              <span class="route-card-stats">
                <span><b>{{ group.currentCount }}</b> 已定价</span>
                <span v-if="group.missingCount" class="text-danger"><b>{{ group.missingCount }}</b> 未设置</span>
                <span v-if="group.pendingCount" class="text-warning"><b>{{ group.pendingCount }}</b> 待处理</span>
              </span>
              <span class="route-card-action">{{ expandedRoute === group.route_id ? '收起' : '查看工序' }} <span aria-hidden="true">→</span></span>
            </button>

            <div v-if="expandedRoute === group.route_id" class="route-price-card-body">
              <div class="route-price-hint">历史版本不可直接修改。新增或调整工价请从具体工序发起，并由另一名用户审批。</div>
              <div class="price-table-wrap route-table-wrap">
                <table class="data-table price-table current-table">
                  <thead>
                    <tr><th class="col-num">#</th><th>工序</th><th class="text-right">当前工价</th><th>返工倍率</th><th>生效时间</th><th>后续安排</th><th>操作</th></tr>
                  </thead>
                  <tbody>
                    <tr v-for="(row, rowIndex) in group.rows" :key="row.key">
                      <td class="text-center"><span class="process-index">{{ rowIndex + 1 }}</span></td>
                      <td><strong>{{ row.process_name }}</strong></td>
                      <td class="text-right price-value">
                        <strong v-if="row.currentVersion">{{ unitPrice(row.currentVersion.normal_unit_price_micros) }}</strong>
                        <span v-else class="missing-price">未设置</span>
                      </td>
                      <td>
                        <span v-if="row.currentVersion?.rework_rate_configured">{{ reworkRate(row.currentVersion.rework_rate_basis_points) }}</span>
                        <span v-else-if="row.currentVersion" class="text-warning">未配置</span>
                        <span v-else>-</span>
                      </td>
                      <td>{{ row.currentVersion ? formatDateTime(row.currentVersion.valid_from) : '-' }}</td>
                      <td>
                        <button v-if="row.drafts.length" type="button" class="inline-action pending-action" @click="showDrafts(row)">
                          {{ row.drafts.length }} 个草稿待处理
                        </button>
                        <span v-else-if="row.upcomingVersion" class="upcoming-note">
                          {{ formatDateTime(row.upcomingVersion.valid_from) }} 起 {{ unitPrice(row.upcomingVersion.normal_unit_price_micros) }}
                        </span>
                        <span v-else class="text-placeholder">无</span>
                      </td>
                      <td>
                        <button
                          v-if="canPrepare && !row.drafts.length"
                          type="button"
                          class="btn btn-default btn-sm"
                          :data-testid="`change-price-${row.route_id}-${row.process_id}`"
                          @click="openCreate(row)"
                        >{{ row.currentVersion ? '调价' : '设置工价' }}</button>
                        <span v-else-if="!canPrepare" class="text-placeholder">-</span>
                      </td>
                    </tr>
                  </tbody>
                </table>
              </div>
            </div>
          </section>
        </div>
      </template>

      <template v-else-if="viewMode === 'pending'">
        <div v-if="!pendingVersions.length" class="price-empty">当前没有待审批工价</div>
        <table v-else class="data-table price-table pending-table">
          <thead>
            <tr><th>路线 / 工序</th><th>工价变化</th><th>返工倍率</th><th>生效时间</th><th>制单信息</th><th>操作</th></tr>
          </thead>
          <tbody>
            <tr v-for="item in pendingVersions" :key="item.id">
              <td><strong>{{ item.route_name || item.route_id }}</strong><small>{{ item.process_name || item.process_id }}</small></td>
              <td>
                <span class="old-price">{{ previousVersion(item) ? unitPrice(previousVersion(item).normal_unit_price_micros) : '未设置' }}</span>
                <span class="price-arrow">&#8594;</span>
                <strong>{{ unitPrice(item.normal_unit_price_micros) }}</strong>
                <small :class="changeClass(item)">{{ changeText(item) }}</small>
              </td>
              <td><span v-if="item.rework_rate_configured">{{ reworkRate(item.rework_rate_basis_points) }}</span><span v-else class="text-warning">未配置</span></td>
              <td>{{ formatDateTime(item.valid_from) }}</td>
              <td>{{ item.created_by_name || '-' }}<small>{{ item.created_at ? formatDateTime(item.created_at) : '' }}</small><small v-if="item.remark">{{ item.remark }}</small></td>
              <td><button v-if="canApprove" type="button" class="btn btn-primary btn-sm" :data-testid="`approve-price-${item.id}`" @click="openApproval(item)">审核</button><span v-else class="text-placeholder">等待审批</span></td>
            </tr>
          </tbody>
        </table>
      </template>

      <template v-else>
        <div v-if="!historyVersions.length" class="price-empty">没有符合条件的版本记录</div>
        <table v-else class="data-table price-table history-table">
          <thead>
            <tr><th>路线 / 工序</th><th>版本</th><th class="text-right">正常工价</th><th>返工倍率</th><th>有效区间</th><th>状态</th><th>制单 / 审批</th><th>备注</th></tr>
          </thead>
          <tbody>
            <tr v-for="item in historyVersions" :key="item.id">
              <td><strong>{{ item.route_name || item.route_id }}</strong><small>{{ item.process_name || item.process_id }}</small></td>
              <td>V{{ versionNumber(item) }}</td>
              <td class="text-right"><strong>{{ unitPrice(item.normal_unit_price_micros) }}</strong></td>
              <td><span v-if="item.rework_rate_configured">{{ reworkRate(item.rework_rate_basis_points) }}</span><span v-else class="text-placeholder">未配置</span></td>
              <td>{{ formatDateTime(item.valid_from) }}<small>至 {{ item.valid_to ? formatDateTime(item.valid_to) : '长期' }}</small></td>
              <td><span class="price-status" :class="displayStatusClass(item)">{{ displayStatus(item) }}</span></td>
              <td>{{ item.created_by_name || '-' }}<small>{{ item.approved_by_name ? `审批：${item.approved_by_name}` : '尚未审批' }}</small></td>
              <td class="remark-cell">{{ item.remark || '-' }}</td>
            </tr>
          </tbody>
        </table>
      </template>
    </div>

    <div v-if="showForm" class="modal-overlay" @click.self="closeForm">
      <div class="modal price-modal" role="dialog" aria-modal="true" aria-labelledby="price-form-title">
        <div class="modal-header">
          <div><span id="price-form-title">{{ lockedReference ? '发起调价' : '新增工价' }}</span><small v-if="formReference">{{ formReference.route_name }} / {{ formReference.process_name }}</small></div>
          <button type="button" class="modal-close" aria-label="关闭" title="关闭" @click="closeForm">&times;</button>
        </div>
        <div class="modal-body">
          <div class="form-grid">
            <label>路线
              <select v-model="form.routeId" class="form-input" :disabled="lockedReference" @change="routeChanged">
                <option value="">请选择路线</option>
                <option v-for="route in routeOptions" :key="route.route_id" :value="route.route_id">{{ route.route_name }}</option>
              </select>
            </label>
            <label>工序
              <select v-model="form.processId" class="form-input" :disabled="lockedReference || !form.routeId">
                <option value="">请选择工序</option>
                <option v-for="process in processOptions" :key="process.process_id" :value="process.process_id">{{ process.process_name }}</option>
              </select>
            </label>
          </div>

          <div v-if="formCurrentVersion" class="current-price-strip">
            <span>当前正常工价<strong>{{ unitPrice(formCurrentVersion.normal_unit_price_micros) }}</strong></span>
            <span>返工倍率<strong>{{ formCurrentVersion.rework_rate_configured ? reworkRate(formCurrentVersion.rework_rate_basis_points) : '未配置' }}</strong></span>
            <span>生效时间<strong>{{ formatDateTime(formCurrentVersion.valid_from) }}</strong></span>
          </div>

          <div class="form-grid price-input-grid">
            <label>新正常工价（元）
              <input v-model="form.unitPrice" type="number" min="0.0001" step="0.0001" class="form-input" inputmode="decimal">
            </label>
            <label>生效时间
              <input v-model="form.validFrom" type="datetime-local" class="form-input">
            </label>
          </div>

          <label class="rework-toggle">
            <input v-model="form.reworkConfigured" type="checkbox">
            <span>设置返工倍率</span>
          </label>
          <label v-if="form.reworkConfigured" class="field-label">返工倍率（%）
            <input v-model="form.reworkPercent" type="number" min="0" max="100" step="0.01" class="form-input" inputmode="decimal">
          </label>
          <label class="field-label">调价依据
            <textarea v-model="form.remark" class="form-input remark-input" rows="3" placeholder="填写调价单号、通知或原因"></textarea>
          </label>

          <div v-if="formCurrentVersion && form.unitPrice !== ''" class="change-preview">
            <span>正常工价</span>
            <strong>{{ unitPrice(formCurrentVersion.normal_unit_price_micros) }} &#8594; {{ inputUnitPrice }}</strong>
            <span :class="inputChangeClass">{{ inputChangeText }}</span>
          </div>
        </div>
        <div class="modal-footer">
          <button type="button" class="btn btn-default" @click="closeForm">取消</button>
          <button type="button" class="btn btn-primary" data-testid="save-price-draft" :disabled="working" @click="createVersion">保存草稿</button>
        </div>
      </div>
    </div>

    <div v-if="approvalTarget" class="modal-overlay" @click.self="approvalTarget = null">
      <div class="modal approval-modal" role="dialog" aria-modal="true" aria-labelledby="approval-title">
        <div class="modal-header">
          <div><span id="approval-title">审核工价</span><small>{{ approvalTarget.route_name }} / {{ approvalTarget.process_name }}</small></div>
          <button type="button" class="modal-close" aria-label="关闭" title="关闭" @click="approvalTarget = null">&times;</button>
        </div>
        <div class="modal-body">
          <dl class="approval-details">
            <div><dt>当前工价</dt><dd>{{ previousVersion(approvalTarget) ? unitPrice(previousVersion(approvalTarget).normal_unit_price_micros) : '未设置' }}</dd></div>
            <div><dt>新工价</dt><dd><strong>{{ unitPrice(approvalTarget.normal_unit_price_micros) }}</strong><small :class="changeClass(approvalTarget)">{{ changeText(approvalTarget) }}</small></dd></div>
            <div><dt>返工倍率</dt><dd>{{ approvalTarget.rework_rate_configured ? reworkRate(approvalTarget.rework_rate_basis_points) : '未配置' }}</dd></div>
            <div><dt>生效时间</dt><dd>{{ formatDateTime(approvalTarget.valid_from) }}</dd></div>
            <div><dt>制单人</dt><dd>{{ approvalTarget.created_by_name || '-' }}</dd></div>
            <div class="full"><dt>调价依据</dt><dd>{{ approvalTarget.remark || '未填写' }}</dd></div>
          </dl>
          <div class="approval-warning">批准后工价不可修改，并将在生效时间按版本结算。</div>
        </div>
        <div class="modal-footer">
          <button type="button" class="btn btn-default" @click="approvalTarget = null">取消</button>
          <button type="button" class="btn btn-primary" data-testid="confirm-price-approval" :disabled="working" @click="confirmApproval">确认批准</button>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import { api } from '@/lib/api.js'
import { can } from '@/lib/auth.js'
import { showToast } from '@/lib/store.js'

const versions = ref([])
const references = ref([])
const loading = ref(false)
const working = ref(false)
const query = ref('')
const category = ref('')
const viewMode = ref('current')
const historyStatus = ref('')
const showForm = ref(false)
const lockedReference = ref(false)
const approvalTarget = ref(null)
const nowTimestamp = ref(timestampNow())
const form = ref(emptyForm())
const expandedRoute = ref(null)

const canPrepare = computed(() => can('wages:prepare'))
const canApprove = computed(() => can('wages:approve'))
const viewOptions = [
  { value: 'current', label: '当前工价' },
  { value: 'pending', label: '待审批' },
  { value: 'history', label: '版本记录' },
]

function localNow() {
  const date = new Date()
  date.setMinutes(date.getMinutes() - date.getTimezoneOffset())
  return date.toISOString().slice(0, 16)
}

function timestampNow() {
  return `${localNow().replace('T', ' ')}:00`
}

function emptyForm() {
  return { routeId: '', processId: '', unitPrice: '', validFrom: localNow(), reworkConfigured: false, reworkPercent: '', remark: '' }
}

function keyOf(routeId, processId) {
  return `${routeId}:${processId}`
}

const referenceMap = computed(() => new Map(references.value.map(item => [keyOf(item.route_id, item.process_id), item])))
const categoryOptions = computed(() => [...new Set(references.value.map(item => item.route_category).filter(Boolean))].sort())
const categoryTabOptions = computed(() => {
  const countRoutes = rows => new Set(rows.map(row => row.route_id)).size
  return [
    { value: '', label: '全部工价路线', icon: '📋', count: countRoutes(referenceRows.value) },
    ...categoryOptions.value.map(item => ({
      value: item,
      label: `${item}工价`,
      icon: item === '机加工' ? '⚙️' : '🔩',
      count: countRoutes(referenceRows.value.filter(row => row.route_category === item)),
    })),
  ]
})
const routeOptions = computed(() => {
  const routes = new Map()
  references.value.forEach(item => {
    if (!routes.has(item.route_id)) routes.set(item.route_id, item)
  })
  return [...routes.values()].sort((a, b) => `${a.route_category || ''}:${a.route_name}`.localeCompare(`${b.route_category || ''}:${b.route_name}`, 'zh-CN'))
})
const processOptions = computed(() => references.value.filter(item => Number(item.route_id) === Number(form.value.routeId)))
const versionsByReference = computed(() => {
  const grouped = new Map()
  versions.value.forEach(item => {
    const key = keyOf(item.route_id, item.process_id)
    if (!grouped.has(key)) grouped.set(key, [])
    grouped.get(key).push(item)
  })
  grouped.forEach(items => items.sort((a, b) => `${b.valid_from}:${b.id}`.localeCompare(`${a.valid_from}:${a.id}`)))
  return grouped
})

function activeVersion(items) {
  return items.find(item => item.status === 'approved' && item.valid_from <= nowTimestamp.value && (!item.valid_to || item.valid_to > nowTimestamp.value)) || null
}

function upcomingVersion(items) {
  return items
    .filter(item => item.status === 'approved' && item.valid_from > nowTimestamp.value)
    .sort((a, b) => `${a.valid_from}:${a.id}`.localeCompare(`${b.valid_from}:${b.id}`))[0] || null
}

const referenceRows = computed(() => references.value.map(item => {
  const items = versionsByReference.value.get(keyOf(item.route_id, item.process_id)) || []
  return {
    ...item,
    key: keyOf(item.route_id, item.process_id),
    currentVersion: activeVersion(items),
    upcomingVersion: upcomingVersion(items),
    drafts: items.filter(version => version.status === 'draft'),
  }
}))

function matchesFilters(item) {
  const reference = referenceMap.value.get(keyOf(item.route_id, item.process_id)) || item
  if (category.value && reference.route_category !== category.value) return false
  if (!query.value) return true
  const text = [item.route_name, item.process_name, reference.route_name, reference.process_name, reference.route_category]
    .filter(Boolean).join(' ').toLocaleLowerCase('zh-CN')
  return text.includes(query.value.toLocaleLowerCase('zh-CN'))
}

const currentRows = computed(() => referenceRows.value.filter(matchesFilters))
const currentRouteGroups = computed(() => {
  const groups = new Map()
  currentRows.value.forEach(row => {
    if (!groups.has(row.route_id)) {
      groups.set(row.route_id, {
        route_id: row.route_id,
        route_name: row.route_name,
        route_category: row.route_category,
        rows: [],
      })
    }
    groups.get(row.route_id).rows.push(row)
  })
  return [...groups.values()].map(group => ({
    ...group,
    currentCount: group.rows.filter(row => row.currentVersion).length,
    missingCount: group.rows.filter(row => !row.currentVersion && !row.upcomingVersion).length,
    pendingCount: group.rows.reduce((count, row) => count + row.drafts.length, 0),
  }))
})
const pendingVersions = computed(() => versions.value.filter(item => item.status === 'draft' && matchesFilters(item)))
const historyVersions = computed(() => versions.value.filter(item => (!historyStatus.value || item.status === historyStatus.value) && matchesFilters(item)))
const currentCount = computed(() => referenceRows.value.filter(item => item.currentVersion).length)
const pendingCount = computed(() => versions.value.filter(item => item.status === 'draft').length)
const upcomingCount = computed(() => versions.value.filter(item => item.status === 'approved' && item.valid_from > nowTimestamp.value).length)
const missingCount = computed(() => referenceRows.value.filter(item => !item.currentVersion && !item.upcomingVersion).length)

const formReference = computed(() => referenceMap.value.get(keyOf(form.value.routeId, form.value.processId)) || null)
const formCurrentVersion = computed(() => activeVersion(versionsByReference.value.get(keyOf(form.value.routeId, form.value.processId)) || []))
const inputMicros = computed(() => form.value.unitPrice === '' ? null : Math.round(Number(form.value.unitPrice) * 10000))
const inputUnitPrice = computed(() => unitPrice(inputMicros.value || 0))
const inputDifference = computed(() => inputMicros.value === null || !formCurrentVersion.value ? null : inputMicros.value - Number(formCurrentVersion.value.normal_unit_price_micros || 0))
const inputChangeText = computed(() => differenceText(inputDifference.value))
const inputChangeClass = computed(() => differenceClass(inputDifference.value))

const versionNumbers = computed(() => {
  const result = new Map()
  versionsByReference.value.forEach(items => {
    [...items]
      .sort((a, b) => `${a.valid_from}:${a.id}`.localeCompare(`${b.valid_from}:${b.id}`))
      .forEach((item, index) => result.set(item.id, index + 1))
  })
  return result
})

function unitPrice(value) {
  return `¥${(Number(value || 0) / 10000).toFixed(4)}`
}

function reworkRate(value) {
  return `${(Number(value || 0) / 100).toFixed(2)}%`
}

function formatDateTime(value) {
  return value ? String(value).replace('T', ' ').slice(0, 16) : '-'
}

function previousVersion(item) {
  return (versionsByReference.value.get(keyOf(item.route_id, item.process_id)) || [])
    .filter(version => version.status === 'approved' && version.id !== item.id && version.valid_from < item.valid_from)
    .sort((a, b) => `${b.valid_from}:${b.id}`.localeCompare(`${a.valid_from}:${a.id}`))[0] || null
}

function difference(item) {
  const previous = previousVersion(item)
  return previous ? Number(item.normal_unit_price_micros) - Number(previous.normal_unit_price_micros) : null
}

function differenceText(value) {
  if (value === null) return '首次设置'
  if (value === 0) return '价格不变'
  const sign = value > 0 ? '+' : '-'
  return `${sign}${unitPrice(Math.abs(value))}`
}

function differenceClass(value) {
  if (value === null || value === 0) return 'text-placeholder'
  return value > 0 ? 'text-danger' : 'text-success'
}

function changeText(item) {
  return differenceText(difference(item))
}

function changeClass(item) {
  return differenceClass(difference(item))
}

function versionNumber(item) {
  return versionNumbers.value.get(item.id) || 1
}

function displayStatus(item) {
  if (item.status === 'draft') return '草稿'
  if (item.status === 'retired') return '已结束'
  const current = activeVersion(versionsByReference.value.get(keyOf(item.route_id, item.process_id)) || [])
  if (current?.id === item.id) return '当前生效'
  if (item.valid_from > nowTimestamp.value) return '待生效'
  if (item.valid_to && item.valid_to <= nowTimestamp.value) return '已结束'
  return '已批准'
}

function displayStatusClass(item) {
  const label = displayStatus(item)
  return { '当前生效': 'status-current', '待生效': 'status-upcoming', '草稿': 'status-draft', '已结束': 'status-retired' }[label] || 'status-approved'
}

function routeChanged() {
  if (!processOptions.value.some(item => Number(item.process_id) === Number(form.value.processId))) form.value.processId = ''
}

function openCreate(row) {
  form.value = emptyForm()
  lockedReference.value = Boolean(row)
  if (row) {
    form.value.routeId = row.route_id
    form.value.processId = row.process_id
    if (row.currentVersion) {
      form.value.unitPrice = (Number(row.currentVersion.normal_unit_price_micros) / 10000).toFixed(4)
      form.value.reworkConfigured = Boolean(row.currentVersion.rework_rate_configured)
      form.value.reworkPercent = row.currentVersion.rework_rate_configured
        ? (Number(row.currentVersion.rework_rate_basis_points) / 100).toFixed(2)
        : ''
    }
  }
  showForm.value = true
}

function closeForm() {
  if (working.value) return
  showForm.value = false
}

function showDrafts(row) {
  query.value = `${row.route_name} ${row.process_name}`
  viewMode.value = 'pending'
}

function toggleRoute(routeId) {
  expandedRoute.value = expandedRoute.value === routeId ? null : routeId
}

function openApproval(item) {
  approvalTarget.value = item
}

async function load() {
  loading.value = true
  nowTimestamp.value = timestampNow()
  try {
    const [versionData, referenceData] = await Promise.all([
      api.domains.wages.listRoutePriceVersions({}),
      api.domains.wages.getRoutePriceVersionReference(),
    ])
    versions.value = versionData.versions || []
    references.value = referenceData.items || []
    if (expandedRoute.value && !currentRouteGroups.value.some(group => Number(group.route_id) === Number(expandedRoute.value))) {
      expandedRoute.value = null
    }
  } catch (error) {
    showToast(error.message || '工价版本加载失败', 'error')
  } finally {
    loading.value = false
  }
}

async function createVersion() {
  const routeId = Number(form.value.routeId)
  const processId = Number(form.value.processId)
  if (!routeId || !processId || form.value.unitPrice === '' || !form.value.validFrom) {
    showToast('请完整填写路线、工序、工价和生效时间', 'error')
    return
  }
  if (!Number.isFinite(Number(form.value.unitPrice)) || Number(form.value.unitPrice) <= 0) {
    showToast('工价必须大于 0', 'error')
    return
  }
  if (form.value.reworkConfigured && (!Number.isFinite(Number(form.value.reworkPercent)) || Number(form.value.reworkPercent) < 0 || Number(form.value.reworkPercent) > 100)) {
    showToast('返工倍率必须在 0% 到 100% 之间', 'error')
    return
  }
  const data = {
    route_id: routeId,
    process_id: processId,
    normal_unit_price: form.value.unitPrice,
    valid_from: `${form.value.validFrom.replace('T', ' ')}:00`,
    remark: form.value.remark.trim(),
  }
  if (form.value.reworkConfigured) data.rework_rate_basis_points = Math.round(Number(form.value.reworkPercent) * 100)
  working.value = true
  try {
    await api.domains.wages.createRoutePriceVersion(data)
    showToast('工价草稿已创建')
    showForm.value = false
    viewMode.value = 'pending'
    query.value = ''
    await load()
  } catch (error) {
    showToast(error.message || '创建失败', 'error')
  } finally {
    working.value = false
  }
}

async function confirmApproval() {
  if (!approvalTarget.value || working.value) return
  const item = approvalTarget.value
  working.value = true
  try {
    await api.domains.wages.approveRoutePriceVersion(item.id, item.row_version)
    showToast('工价版本已批准')
    approvalTarget.value = null
    await load()
  } catch (error) {
    showToast(error.message || '批准失败', 'error')
  } finally {
    working.value = false
  }
}

function handleEscape(event) {
  if (event.key !== 'Escape' || working.value) return
  if (approvalTarget.value) approvalTarget.value = null
  else if (showForm.value) showForm.value = false
}

onMounted(() => {
  document.addEventListener('keydown', handleEscape)
  load()
})
onBeforeUnmount(() => document.removeEventListener('keydown', handleEscape))
</script>

<style scoped>
.price-version-page{min-width:0}.price-toolbar{display:flex;align-items:flex-start;justify-content:space-between;gap:16px;margin-bottom:14px}.price-toolbar h3{margin:0;font-size:18px}.price-toolbar p{margin:4px 0 0;color:var(--text-placeholder);font-size:12px}.price-actions{display:flex;align-items:center;justify-content:flex-end;gap:8px;flex-wrap:wrap}.search-field .form-input{width:220px}.category-select{width:130px}.icon-button{display:inline-flex;align-items:center;justify-content:center;width:34px;height:34px;padding:0;border:1px solid var(--border);border-radius:6px;background:var(--bg-surface);color:var(--text-secondary);font-size:20px;line-height:1;cursor:pointer}.icon-button:hover{border-color:var(--primary);color:var(--primary);background:var(--primary-light)}.icon-button:disabled{cursor:not-allowed;opacity:.55}.sr-only{position:absolute;width:1px;height:1px;padding:0;margin:-1px;overflow:hidden;clip:rect(0,0,0,0);white-space:nowrap;border:0}.price-summary{display:grid;grid-template-columns:repeat(4,minmax(120px,1fr));margin-bottom:14px;border-top:1px solid var(--border-light);border-bottom:1px solid var(--border-light)}.price-summary div{padding:11px 16px;border-right:1px solid var(--border-light)}.price-summary div:last-child{border-right:0}.price-summary span{display:block;color:var(--text-placeholder);font-size:12px}.price-summary strong{display:block;margin-top:2px;color:var(--text-primary);font-size:20px}.view-row{display:flex;align-items:center;justify-content:space-between;gap:12px;margin-bottom:10px}.view-switch{display:inline-flex;padding:3px;border:1px solid var(--border-light);border-radius:7px;background:var(--bg-secondary)}.view-switch button{min-height:30px;padding:5px 13px;border:0;border-radius:5px;background:transparent;color:var(--text-secondary);font-size:13px;cursor:pointer}.view-switch button.active{background:var(--bg-surface);color:var(--primary);box-shadow:var(--shadow-sm);font-weight:600}.view-count{display:inline-flex;align-items:center;justify-content:center;min-width:18px;height:18px;margin-left:6px;padding:0 5px;border-radius:9px;background:var(--warning);color:white;font-size:11px}.history-filter{width:130px}.price-table-wrap{overflow-x:auto;border:1px solid var(--border-light);border-radius:8px;background:var(--bg-surface)}.price-table{width:100%;min-width:940px}.price-table th{white-space:nowrap}.price-table td{vertical-align:middle}.price-table small{display:block;margin-top:3px;color:var(--text-placeholder);font-size:11px}.current-table{min-width:980px}.pending-table{min-width:900px}.history-table{min-width:1080px}.price-value strong{font-size:15px}.missing-price{color:var(--danger);font-weight:600}.inline-action{padding:0;border:0;background:transparent;cursor:pointer;font-size:12px}.pending-action{color:var(--warning-dark);text-decoration:underline}.upcoming-note{display:block;max-width:220px;color:var(--primary);font-size:12px}.text-placeholder{color:var(--text-placeholder);font-size:12px}.old-price{color:var(--text-placeholder);text-decoration:line-through}.price-arrow{margin:0 7px;color:var(--text-placeholder)}.price-empty{padding:56px 20px;text-align:center;color:var(--text-placeholder)}.price-status{display:inline-block;padding:3px 7px;border-radius:4px;font-size:12px;white-space:nowrap}.status-current{color:var(--success-dark);background:var(--success-light)}.status-upcoming,.status-approved{color:var(--primary);background:var(--primary-light)}.status-draft{color:var(--warning-dark);background:var(--warning-lighter)}.status-retired{color:var(--text-placeholder);background:var(--bg-secondary)}.remark-cell{max-width:220px;white-space:normal;overflow-wrap:anywhere}.text-right{text-align:right}.price-modal{width:680px;border-radius:8px}.modal-header>div{min-width:0}.modal-header small{display:block;margin-top:3px;color:var(--text-placeholder);font-size:12px;font-weight:400}.form-grid{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:14px}.form-grid label,.field-label{display:flex;flex-direction:column;gap:5px;color:var(--text-secondary);font-size:12px}.current-price-strip{display:grid;grid-template-columns:repeat(3,1fr);gap:10px;margin:16px 0;padding:11px 0;border-top:1px solid var(--border-light);border-bottom:1px solid var(--border-light)}.current-price-strip span{color:var(--text-placeholder);font-size:11px}.current-price-strip strong{display:block;margin-top:3px;color:var(--text-primary);font-size:13px}.price-input-grid{margin-top:16px}.rework-toggle{display:flex;align-items:center;gap:8px;margin:16px 0 10px;color:var(--text-secondary);font-size:13px}.field-label{margin-top:12px}.remark-input{resize:vertical;min-height:74px}.change-preview{display:grid;grid-template-columns:auto 1fr auto;align-items:center;gap:12px;margin-top:16px;padding:11px 12px;border-left:3px solid var(--primary);background:var(--bg-secondary);font-size:12px}.change-preview strong{text-align:center;font-size:14px}.approval-modal{width:560px;border-radius:8px}.approval-details{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:0;margin:0;border-top:1px solid var(--border-light);border-left:1px solid var(--border-light)}.approval-details div{padding:12px;border-right:1px solid var(--border-light);border-bottom:1px solid var(--border-light)}.approval-details div.full{grid-column:1/-1}.approval-details dt{color:var(--text-placeholder);font-size:11px}.approval-details dd{margin:4px 0 0;color:var(--text-primary);font-size:13px}.approval-details dd small{display:block;margin-top:3px}.approval-warning{margin-top:14px;padding:10px 12px;border-left:3px solid var(--warning);background:var(--warning-light);color:var(--warning-dark);font-size:12px}.text-danger{color:var(--danger)!important}.text-success{color:var(--success)!important}.text-warning{color:var(--warning-dark)!important}@media(max-width:800px){.price-toolbar{flex-direction:column}.price-actions{width:100%;justify-content:flex-start}.search-field{flex:1;min-width:180px}.search-field .form-input{width:100%}.price-summary{grid-template-columns:repeat(2,1fr)}.price-summary div:nth-child(2){border-right:0}.view-row{align-items:flex-start;flex-direction:column}.view-switch{width:100%}.view-switch button{flex:1;padding-inline:8px}.form-grid,.current-price-strip,.approval-details{grid-template-columns:1fr}.approval-details div.full{grid-column:auto}.change-preview{grid-template-columns:1fr;text-align:left}.change-preview strong{text-align:left}.price-modal,.approval-modal{width:95vw}.modal-body{padding:16px}.modal-footer{padding:12px 16px}}
.route-category-tabs{display:flex;gap:8px;margin-bottom:12px;overflow-x:auto;padding-bottom:2px}.route-category-tabs button{display:inline-flex;align-items:center;gap:6px;flex:0 0 auto;padding:8px 13px;border:1px solid var(--border-light);border-radius:7px;background:var(--bg-surface);color:var(--text-secondary);font-size:13px;cursor:pointer;white-space:nowrap}.route-category-tabs button:hover{border-color:var(--primary);color:var(--primary)}.route-category-tabs button.active{border-color:var(--primary);background:var(--primary-light);color:var(--primary);font-weight:600}.route-category-tabs button strong{padding-left:2px;font-size:12px}.route-price-list{display:flex;flex-direction:column;gap:10px}.route-price-card{overflow:hidden;border:1px solid var(--border-light);border-left:4px solid transparent;border-radius:8px;background:var(--bg-surface);transition:border-color .15s,box-shadow .15s}.route-price-card.expanded{border-left-color:var(--primary);box-shadow:var(--shadow-sm)}.route-price-card-header{display:flex;align-items:center;width:100%;gap:10px;padding:14px 16px;border:0;background:transparent;color:inherit;text-align:left;cursor:pointer}.route-price-card-header:hover{background:var(--bg-hover)}.route-index,.process-index{display:inline-flex;align-items:center;justify-content:center;flex:0 0 auto;width:27px;height:27px;border-radius:50%;background:var(--primary-light);color:var(--primary);font-size:12px;font-weight:700}.route-chevron{width:16px;color:var(--text-placeholder);font-size:13px}.route-card-title{display:flex;min-width:180px;flex-direction:column;gap:3px}.route-card-title strong{font-size:15px}.route-card-title small{color:var(--text-placeholder);font-size:11px}.route-card-stats{display:flex;align-items:center;gap:12px;margin-left:auto;color:var(--text-placeholder);font-size:12px;white-space:nowrap}.route-card-stats b{color:var(--text-primary);font-size:14px}.route-card-action{min-width:78px;color:var(--primary);font-size:12px;text-align:right;white-space:nowrap}.route-price-card-body{padding:0 16px 16px;border-top:1px solid var(--bg-hover)}.route-price-hint{padding:12px 0;color:var(--text-placeholder);font-size:12px}.route-table-wrap{border-radius:6px}.process-index{width:23px;height:23px;font-size:11px}.text-center{text-align:center}@media(max-width:800px){.route-price-card-header{align-items:flex-start;flex-wrap:wrap;padding:12px}.route-card-title{min-width:calc(100% - 70px)}.route-card-stats{order:4;width:100%;margin-left:53px;gap:10px;overflow-x:auto}.route-card-action{margin-left:auto}.route-price-card-body{padding:0 10px 10px}.route-price-hint{padding:10px 0}}
</style>
