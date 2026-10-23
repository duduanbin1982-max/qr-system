import { ref, onMounted, onUnmounted } from 'vue'
import { api } from '@/lib/api.js'
import { navigate } from '@/lib/router.js'
import { auth, getBoardToken } from '@/lib/auth.js'

export function useDashboardOverview() {
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
  // 快捷操作（从后端API动态获取）
  const quickActions = ref([])

  // 立即显示时间（不等60s定时器触发）
  updateTime()

  async function load() {
    loading.value = true
    error.value = ''
    try {
      const d = await api.domains.dashboard.dashboard()
      stats.value = d.stats
      security.value = d.security || null
      records.value = d.recent_records || []
      companyName.value = d.company_name || ''
      deliveryWarnings.value = d.delivery_warnings || null
      quickActions.value = (d.quick_actions || []).filter(q => q && typeof q.page === 'string' && q.page.trim().length > 0).map(q => ({ page: q.page.trim(), icon: q.icon || '📋', text: q.label || q.page, desc: q.desc || '', external: q.external || null }))
    } catch(e) {
      error.value = e.message || '加载失败'
    } finally {
      loading.value = false
    }
  }

  let _timer = null
  let _clock = null
  // Visibility change handler - defined inline to avoid minifier scope issues
  function _onVisible() { if (!document.hidden) { load(); updateTime(); } }

  onMounted(() => {
    load()
    updateTime()
    _timer = setInterval(load, 30000)
    _clock = setInterval(updateTime, 60000)
    document.addEventListener('visibilitychange', _onVisible)
  })

  onUnmounted(() => {
    if (_timer) clearInterval(_timer)
    if (_clock) clearInterval(_clock)
    document.removeEventListener('visibilitychange', _onVisible)
  })

  async function goAction(q) { if (q.external) { await getBoardToken(); window.open(q.external, '_blank'); } else { navigate(q.page); } }
  return { stats, security, records, loading, error, load, now, companyName, deliveryWarnings, quickActions, navigate, auth, goAction }
}
