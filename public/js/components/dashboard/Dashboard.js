// Dashboard Component — 工作台
import { ref, onMounted, computed } from '../../vendor/vue.esm.js'
import { api } from '../../api.js?v=56'
import { navigate, router } from '../../router.js'
import { auth } from '../../auth.js?v=56'

export default {
  template: '#dashboard-template',
  setup() {
    const stats = ref(null)
    const security = ref(null)
    const records = ref([])
    const companyName = ref('')
    const deliveryWarnings = ref(null)
    const loading = ref(true)
    const error = ref('')
    
    // 当前时间
    const now = ref('')
    function updateTime() {
      const d = new Date()
      const h = d.getHours()
      const g = h < 6 ? '凌晨好' : h < 9 ? '早上好' : h < 12 ? '上午好' : h < 14 ? '中午好' : h < 18 ? '下午好' : '晚上好'
      now.value = g + '，' + d.toLocaleString('zh-CN', { month:'long', day:'numeric', weekday:'long' })
    }
    setInterval(updateTime, 60000)
    updateTime()
    
    // 快捷操作（从后端API动态获取）
    const quickActions = ref([])
    
    async function load() {
      loading.value = true
      error.value = ''
      try {
        const d = await api.dashboard()
        stats.value = d.stats
        security.value = d.security || null
        records.value = d.recent_records || []
        companyName.value = d.company_name || ''
        deliveryWarnings.value = d.delivery_warnings || null
        quickActions.value = (d.quick_actions || []).map(q => ({ page: q.page, icon: q.icon, text: q.label || q.page, desc: q.perm || "" }))
      } catch(e) {
        error.value = e.message || '加载失败'
      } finally {
        loading.value = false
      }
    }
    
    onMounted(() => load())
    
    return { stats, security, records, loading, error, load, now, companyName, deliveryWarnings, quickActions, navigate, auth }
  }
}
