<template>
<div style="padding:var(--space-6)">
  <div class="summary-bar">
    <div class="summary-item"><span class="s-icon">⏱️</span><div><div class="s-val">{{ stats.standards_active || 0 }}</div><div class="s-label">启用标准</div></div></div>
    <div class="summary-item"><span class="s-icon">🧾</span><div><div class="s-val">{{ stats.records_total || 0 }}</div><div class="s-label">工时流水</div></div></div>
    <div class="summary-item"><span class="s-icon">⚠️</span><div><div class="s-val text-warning">{{ stats.pending_review || 0 }}</div><div class="s-label">待审核</div></div></div>
    <div class="summary-item"><span class="s-icon">📈</span><div><div class="s-val text-primary">{{ stats.avg_efficiency || 0 }}%</div><div class="s-label">平均效率</div></div></div>
    <div class="summary-item"><span class="s-icon">🕒</span><div><div class="s-val">{{ stats.effective_hours || 0 }}</div><div class="s-label">有效工时(h)</div></div></div>
  </div>

  <div class="card">
    <div class="card-header" style="display:flex;align-items:center;gap:var(--space-3);flex-wrap:wrap">
      <h3 style="margin:0">⏱️ 工时管理</h3>
      <div style="display:flex;gap:var(--space-1);flex-wrap:wrap">
        <button v-for="tab in tabs" :key="tab.key" class="tab-btn" :class="{active: activeTab===tab.key}" @click="switchTab(tab.key)">
          {{ tab.label }}
        </button>
      </div>
      <div style="margin-left:auto;display:flex;gap:var(--space-2);flex-wrap:wrap">
        <input class="form-input" v-model="keyword" placeholder="搜索路线/工序/订单/员工" @keyup.enter="loadActive" style="width:220px">
        <button class="btn btn-default btn-sm" @click="loadActive">搜索</button>
        <button v-if="activeTab==='standards'" class="btn btn-primary btn-sm" @click="openPrimaryAction">批量维护标准工时</button>
        <button v-if="activeTab==='records'" class="btn btn-primary btn-sm" @click="openPrimaryAction">新增工时流水</button>
      </div>
    </div>

    <div class="card-body">
      <WorkTimeStandardsPanel
        v-show="activeTab==='standards'"
        ref="standardsPanel"
        :keyword="keyword"
        :process-routes="processRoutes"
        :processes="processes"
        @changed="handlePanelChanged"
      />
      <WorkTimeRecordsPanel
        v-show="activeTab==='records'"
        ref="recordsPanel"
        :keyword="keyword"
        :processes="processes"
        :users="users"
        @changed="handlePanelChanged"
        @review="openReview"
      />
      <WorkTimeAuditPanel
        v-show="activeTab==='audit'"
        ref="auditPanel"
        :keyword="keyword"
        :processes="processes"
        @review="openReview"
      />
    </div>
  </div>

  <WorkTimeReviewModal v-model="showReviewModal" :record="reviewRecord" @saved="handleReviewSaved" />
</div>
</template>

<script setup>
import { nextTick, onMounted, ref } from 'vue'
import { api } from '@/lib/api.js'
import WorkTimeAuditPanel from './work-time/WorkTimeAuditPanel.vue'
import WorkTimeRecordsPanel from './work-time/WorkTimeRecordsPanel.vue'
import WorkTimeReviewModal from './work-time/WorkTimeReviewModal.vue'
import WorkTimeStandardsPanel from './work-time/WorkTimeStandardsPanel.vue'

const tabs = [
  { key: 'standards', label: '标准工时' },
  { key: 'records', label: '工时流水' },
  { key: 'audit', label: '工时审核' },
]

const activeTab = ref(localStorage.getItem('workTimeTab') || 'standards')
const keyword = ref('')
const stats = ref({})
const processRoutes = ref([])
const processes = ref([])
const users = ref([])
const standardsPanel = ref(null)
const recordsPanel = ref(null)
const auditPanel = ref(null)
const showReviewModal = ref(false)
const reviewRecord = ref(null)

async function loadStats() {
  try { stats.value = await api.workTimeStats() } catch (error) { stats.value = {} }
}

async function loadRefs() {
  try {
    const result = await api.listProcessRoutes({ limit: 500 })
    processRoutes.value = result.routes || result.items || []
  } catch (error) { processRoutes.value = [] }
  try {
    const result = await api.listProcesses({ limit: 500 })
    processes.value = result.processes || result.items || []
  } catch (error) { processes.value = [] }
  try {
    const result = await api.listUsers({ limit: 200, status: 'active' })
    users.value = result.users || result.items || []
  } catch (error) { users.value = [] }
}

function currentPanel() {
  if (activeTab.value === 'standards') return standardsPanel.value
  if (activeTab.value === 'records') return recordsPanel.value
  if (activeTab.value === 'audit') return auditPanel.value
  return null
}

async function loadActive() {
  await nextTick()
  const panel = currentPanel()
  if (panel?.load) await panel.load()
  await loadStats()
}

async function switchTab(key) {
  activeTab.value = key
  localStorage.setItem('workTimeTab', key)
  await loadActive()
}

function openPrimaryAction() {
  if (activeTab.value === 'standards') standardsPanel.value?.openStandardGroup()
  if (activeTab.value === 'records') recordsPanel.value?.openRecord()
}

async function handlePanelChanged() {
  await loadStats()
}

function openReview(row) {
  reviewRecord.value = row
  showReviewModal.value = true
}

async function handleReviewSaved() {
  await loadActive()
}

onMounted(async () => {
  await loadRefs()
  await loadActive()
})
</script>
