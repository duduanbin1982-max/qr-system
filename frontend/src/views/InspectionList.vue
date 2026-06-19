<!-- InspectionList.vue -->
<template>
<div style="padding:var(--space-6)">
    <div class="summary-bar">
      <div class="summary-item"><span class="s-icon">🔍</span><div><div class="s-val">{{ stats.total }}</div><div class="s-label">抽检总数</div></div></div>
      <div class="summary-item"><span class="s-icon">✅</span><div><div class="s-val text-success">{{ stats.pass }}</div><div class="s-label">合格</div></div></div>
      <div class="summary-item"><span class="s-icon">🔄</span><div><div class="s-val text-warning">{{ stats.rework }}</div><div class="s-label">返修</div></div></div>
      <div class="summary-item"><span class="s-icon">❌</span><div><div class="s-val text-danger">{{ stats.scrap }}</div><div class="s-label">报废</div></div></div>
    </div>

    <div class="card">
      <div class="card-header">
        <h3>🔍 抽检记录</h3>
        <div style="display:flex;gap:var(--space-2);align-items:center">
          <select class="form-input" v-model="filterResult" @change="load" style="width:100px">
            <option value="">全部</option>
            <option value="pass">合格</option>
            <option value="rework">返修</option>
            <option value="scrap">报废</option>
          </select>
          <input class="form-input" v-model="keyword" placeholder="搜索订单/产品..." @keyup.enter="load" style="width:160px">
          <button class="btn btn-default btn-sm" @click="load">搜索</button>
          <button class="btn btn-default btn-sm" @click="exportExcel">📥导出</button>
        </div>
      </div>
      <div class="card-body">
        <div class="table-wrap">
          <table v-if="items.length" class="data-table" style="min-width:800px">
            <thead><tr>
              <th>订单号</th><th>产品编码</th><th>工序</th><th>判定</th><th>返修工序</th><th>质检员</th><th>备注</th><th>时间</th>
            </tr></thead>
            <tbody>
              <tr v-for="r in items" :key="r.id">
                <td><code>{{ r.order_no || '-' }}</code></td>
                <td><code style="font-size:var(--text-xs-alt)">{{ r.product_code || '-' }}</code></td>
                <td>{{ r.process_name }}</td>
                <td><span class="badge" :class="r.result==='pass'?'badge-success':r.result==='rework'?'badge-warning':'badge-danger'">{{ r.result==='pass'?'合格':r.result==='rework'?'返修':'报废' }}</span></td>
                <td>{{ r.rework_process || '-' }}</td>
                <td>{{ r.inspector_name || '-' }}</td>
                <td style="font-size:var(--text-xs);max-width:120px;overflow:hidden;text-overflow:ellipsis">{{ r.remark || '-' }}</td>
                <td style="font-size:var(--text-xs);white-space:nowrap">{{ r.created_at }}</td>
              </tr>
            </tbody>
          </table>
          <div v-else class="empty"><div class="empty-icon">🔍</div><div class="empty-text">暂无抽检记录</div></div>
        </div>
      </div>
    </div>
  </div>
</template>

<script>
import { ref, onMounted } from 'vue'
import { api } from '@/lib/api.js'
import { showToast } from '@/lib/store.js'

export default {
  setup() {
    const items = ref([])
    const stats = ref({ total:0, pass:0, rework:0, scrap:0 })
    const keyword = ref('')
    const filterResult = ref('')

    async function load() {
      try {
        const params = {}
        if (keyword.value) params.keyword = keyword.value
        if (filterResult.value) params.result = filterResult.value
        const d = await api.listInspections(params)
        items.value = d.items || []
      } catch(e) {}
    }

    async function loadStats() {
      try { stats.value = await api.inspectionStats() } catch(e) { /* silent: stats are non-critical */ }
    }

    function exportExcel() {
      const qs = []
      if (keyword.value) qs.push('search=' + encodeURIComponent(keyword.value))
      if (filterResult.value) qs.push('result=' + filterResult.value)
      window.open('/api/quality/inspections/export?' + qs.join('&'), '_blank')
    }

    onMounted(() => { load(); loadStats() })
    return { items, stats, keyword, filterResult, load, exportExcel }
  }
}
</script>
