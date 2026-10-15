import { ref, onMounted } from 'vue'
import { api } from '@/lib/api.js'
import { showToast } from '@/lib/store.js'

export function useInspectionList() {
  const items = ref([])
  const stats = ref({ total:0, pass:0, rework:0, scrap:0, avg_score:0 })
  const keyword = ref('')
  const filterResult = ref('')

  async function load() {
    try {
      const params = {}
      if (keyword.value) params.keyword = keyword.value
      if (filterResult.value) params.result = filterResult.value
      const d = await api.domains.quality.listInspections(params)
      items.value = d.items || []
    } catch(e) { console.warn('Inspections load failed:', e); items.value = [] }
  }

  async function loadStats() {
    try { stats.value = await api.domains.quality.inspectionStats() } catch(e) { /* silent: stats are non-critical */ }
  }

  function exportExcel() {
    const qs = []
    if (keyword.value) qs.push('search=' + encodeURIComponent(keyword.value))
    if (filterResult.value) qs.push('result=' + filterResult.value)
    window.open('/api/quality/inspections/export?' + qs.join('&'), '_blank')
  }

  function resultLabel(result) {
    return result === 'pass' ? '合格' : result === 'rework' ? '返修' : result === 'scrap' ? '报废' : (result || '-')
  }

  function resultClass(result) {
    return result === 'pass' ? 'badge-success' : result === 'rework' ? 'badge-warning' : 'badge-danger'
  }

  function defectLevelLabel(level) {
    const map = { minor:'轻微', general:'一般', severe:'严重', critical:'致命' }
    return map[level] || '-'
  }

      async function del(r) {
    if (!confirm('确定删除抽检记录吗？')) return
    try { await api.domains.quality.deleteInspection(r.id); showToast('删除成功'); await load(); await loadStats() }
    catch(e) { showToast(e.message || '删除失败','error') }
  }

  onMounted(() => { load(); loadStats() })
  return { items, stats, keyword, filterResult, load, exportExcel, del, resultLabel, resultClass, defectLevelLabel }
}
