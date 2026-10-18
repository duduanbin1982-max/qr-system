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
import WorkTimeAuditPanel from './work-time/WorkTimeAuditPanel.vue'
import WorkTimeRecordsPanel from './work-time/WorkTimeRecordsPanel.vue'
import WorkTimeReviewModal from './work-time/WorkTimeReviewModal.vue'
import WorkTimeStandardsPanel from './work-time/WorkTimeStandardsPanel.vue'
import { useWorkTimeWorkspace } from '@/composables/workTime/useWorkTimeWorkspace.js'

const {
  tabs,
  activeTab,
  keyword,
  stats,
  processRoutes,
  processes,
  users,
  standardsPanel,
  recordsPanel,
  auditPanel,
  showReviewModal,
  reviewRecord,
  loadStats,
  loadRefs,
  currentPanel,
  loadActive,
  switchTab,
  openPrimaryAction,
  handlePanelChanged,
  openReview,
  handleReviewSaved
} = useWorkTimeWorkspace()
</script>
