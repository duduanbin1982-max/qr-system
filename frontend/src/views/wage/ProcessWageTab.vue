<template>
  <div v-if="activeTab === 'process'" class="process-wage-page">
    <section v-if="canViewCoverage" class="coverage-workbench">
      <div class="coverage-heading">
        <div><h3>路线版本工价覆盖</h3><p>当前已发布路线的精确版本绑定</p></div>
        <button type="button" class="btn btn-default btn-sm" :disabled="coverageLoading" @click="loadCoverage">刷新</button>
      </div>
      <div class="coverage-summary">
        <span>路线<strong>{{ coverageGroups.length }}</strong></span>
        <span>节点<strong>{{ coverageRows.length }}</strong></span>
        <span>已覆盖<strong class="text-success">{{ coveredCount }}</strong></span>
        <span>缺少工价<strong :class="{ 'text-danger': missingCount }">{{ missingCount }}</strong></span>
      </div>
      <div v-if="coverageLoading" class="coverage-empty">正在加载工价覆盖...</div>
      <div v-else-if="!coverageGroups.length" class="coverage-empty">暂无可核查的已发布路线</div>
      <div v-else class="coverage-table-wrap">
        <table class="data-table coverage-table">
          <thead><tr><th>路线版本</th><th>工序版本</th><th>当前覆盖</th><th>版本状态</th></tr></thead>
          <tbody>
            <template v-for="group in coverageGroups" :key="group.route_version_id">
              <tr v-for="(row, index) in group.rows" :key="`${row.route_version_id}-${row.process_version_id}`">
                <td><template v-if="index === 0"><strong>{{ row.route_name }}</strong><small>路线版本 {{ row.route_version_id }} · {{ row.route_category }}</small></template></td>
                <td><strong>{{ row.process_name }}</strong><small>工序版本 {{ row.process_version_id }}</small></td>
                <td><strong v-if="row.approvedPrice">{{ money(row.approvedPrice.normal_unit_price_micros) }}</strong><span v-else class="missing-price">未覆盖</span></td>
                <td><span v-if="row.approvedPrice" class="text-success">已批准</span><span v-else-if="row.draftPrices.length" class="text-warning">{{ row.draftPrices.length }} 个草稿</span><span v-else class="text-danger">缺少精确版本</span></td>
              </tr>
            </template>
          </tbody>
        </table>
      </div>
    </section>

    <div v-if="processLoading" class="analysis-empty">加载中...</div>
    <div v-else-if="!processData.summary.length" class="analysis-empty">暂无工序分析数据</div>
    <div v-else class="analysis-grid">
      <div class="card analysis-panel">
        <div class="analysis-heading">
          <h3>工序工资分布</h3>
          <input v-model="processMonth" type="month" class="form-input month-input" @change="loadProcess">
        </div>
        <div class="distribution-list">
          <div v-for="(process, index) in processData.summary" :key="process.process_id || index" class="distribution-row">
            <div class="rank-dot" :style="{ background: processColor(index) }">{{ index + 1 }}</div>
            <div class="distribution-name"><strong>{{ process.process_name }}</strong><span>{{ process.worker_count }} 人 · {{ process.total_quantity }} 件</span></div>
            <div class="distribution-value"><strong>¥{{ fmtMoney(process.total_wage) }}</strong><span>{{ processPercent(process.total_wage) }}%</span></div>
          </div>
        </div>
        <div class="analysis-total"><span>合计</span><strong>¥{{ fmtMoney(processData.grand_total_wage) }}</strong></div>
      </div>
      <div class="card analysis-panel">
        <h3>工序产量对比</h3>
        <div class="bar-chart">
          <div v-for="(process, index) in processData.summary" :key="process.process_id || index" class="bar-column">
            <span>{{ process.total_quantity }}</span>
            <div class="bar" :title="`${process.process_name} (${process.total_quantity}件)`" :style="{ height: `${barHeight(process.total_quantity)}%`, background: processColor(index) }"></div>
            <small :title="process.process_name">{{ process.process_name }}</small>
          </div>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { computed, onMounted, ref } from 'vue'

import { useWage } from '@/composables/useWage.js'
import { api } from '@/lib/api.js'
import { can } from '@/lib/auth.js'
import { showToast } from '@/lib/store.js'

const wage = useWage()
const { activeTab, processLoading, processData, processMonth, loadProcess, processColor, processPercent, barHeight, fmtMoney } = wage
const coverageLoading = ref(false)
const routeReferences = ref([])
const priceVersions = ref([])
const canViewCoverage = computed(() => can('wages:view_all') || can('wages:prepare') || can('wages:approve'))

const coverageRows = computed(() => routeReferences.value.map(reference => {
  const exact = priceVersions.value.filter(price => (
    Number(price.route_version_id) === Number(reference.route_version_id)
    && Number(price.process_version_id) === Number(reference.process_version_id)
  ))
  return {
    ...reference,
    approvedPrice: exact.find(price => price.status === 'approved') || null,
    draftPrices: exact.filter(price => price.status === 'draft'),
  }
}))
const coverageGroups = computed(() => {
  const groups = new Map()
  coverageRows.value.forEach(row => {
    if (!groups.has(row.route_version_id)) groups.set(row.route_version_id, { route_version_id: row.route_version_id, rows: [] })
    groups.get(row.route_version_id).rows.push(row)
  })
  return [...groups.values()]
})
const coveredCount = computed(() => coverageRows.value.filter(row => row.approvedPrice).length)
const missingCount = computed(() => coverageRows.value.length - coveredCount.value)

function money(micros) { return `¥${(Number(micros || 0) / 1000000).toFixed(4)}` }

async function loadCoverage() {
  if (!canViewCoverage.value) return
  coverageLoading.value = true
  try {
    const [references, prices] = await Promise.all([
      api.domains.wages.getRoutePriceVersionReference(),
      api.domains.wages.listRoutePriceVersions(),
    ])
    routeReferences.value = references.items || []
    priceVersions.value = prices.versions || []
  } catch (error) {
    showToast(error.message || '工价覆盖加载失败', 'error')
  } finally {
    coverageLoading.value = false
  }
}

onMounted(loadCoverage)
</script>

<style scoped>
.process-wage-page { min-width:0; }
.coverage-workbench { margin-bottom:20px; padding:18px 20px; border:1px solid var(--border-color); border-radius:6px; background:#fff; }
.coverage-heading { display:flex; align-items:flex-start; justify-content:space-between; gap:12px; }
.coverage-heading h3, .analysis-panel h3 { margin:0; font-size:16px; letter-spacing:0; }
.coverage-heading p { margin:4px 0 0; color:var(--text-placeholder); font-size:12px; }
.coverage-summary { display:flex; gap:28px; padding:14px 0; margin-top:12px; border-top:1px solid var(--border-color); border-bottom:1px solid var(--border-color); }
.coverage-summary span { display:flex; align-items:baseline; gap:7px; color:var(--text-secondary); font-size:12px; }
.coverage-summary strong { color:var(--text-primary); font-size:19px; }
.coverage-table-wrap { max-height:340px; overflow:auto; }
.coverage-table { min-width:760px; }
.coverage-table td small { display:block; margin-top:3px; color:var(--text-placeholder); }
.missing-price { color:var(--danger); }
.coverage-empty, .analysis-empty { padding:50px 12px; color:var(--text-placeholder); text-align:center; }
.analysis-grid { display:grid; grid-template-columns:1fr 1fr; gap:16px; }
.analysis-panel { min-width:0; padding:20px; border-radius:6px; }
.analysis-heading { display:flex; align-items:center; gap:12px; margin-bottom:16px; }
.month-input { width:150px; margin-left:auto; }
.distribution-list { max-height:560px; overflow:auto; }
.distribution-row { display:flex; align-items:center; gap:10px; padding:10px 0; border-bottom:1px solid var(--bg-hover); }
.rank-dot { display:flex; align-items:center; justify-content:center; flex:0 0 32px; width:32px; height:32px; border-radius:50%; color:#fff; font-size:12px; font-weight:700; }
.distribution-name { display:grid; flex:1; min-width:0; gap:3px; }
.distribution-name strong { overflow:hidden; text-overflow:ellipsis; white-space:nowrap; }
.distribution-name span, .distribution-value span { color:var(--text-placeholder); font-size:12px; }
.distribution-value { display:grid; gap:3px; flex-shrink:0; text-align:right; }
.distribution-value strong, .analysis-total strong { color:var(--warning-dark); }
.analysis-total { display:flex; justify-content:space-between; padding-top:12px; margin-top:12px; border-top:2px solid var(--border-light); font-weight:700; }
.bar-chart { display:flex; align-items:flex-end; gap:16px; height:600px; padding:0 12px 100px; }
.bar-column { display:flex; flex:1; flex-direction:column; align-items:center; justify-content:flex-end; min-width:0; height:100%; }
.bar-column > span { margin-bottom:4px; font-size:12px; font-weight:600; white-space:nowrap; }
.bar { width:100%; max-width:60px; min-height:4px; border-radius:5px 5px 0 0; transition:height .4s; }
.bar-column small { max-width:70px; margin-top:6px; overflow:hidden; color:var(--text-placeholder); text-overflow:ellipsis; white-space:nowrap; }
@media (max-width:900px) { .analysis-grid { grid-template-columns:1fr; } }
@media (max-width:640px) { .coverage-workbench, .analysis-panel { padding:14px; } .coverage-summary { gap:14px; flex-wrap:wrap; } }
</style>
