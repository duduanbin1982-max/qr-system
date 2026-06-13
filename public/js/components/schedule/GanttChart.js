/* ===== GanttChart — 生产排程甘特图 (纯CSS/JS, 零依赖) ===== */
import { ref, onMounted, computed } from '../../vendor/vue.esm.js'
import { api } from '../../api.js?v=56'
import { showToast } from '../../store.js?v=56'
import { can } from '../../auth.js'

export default {
  template: '#gantt-template',
  setup() {
    const orders = ref([])
    const loading = ref(true)
    const dayWidth = ref(38)
    const statusFilter = ref('all')

    // RBAC — reserved for future edit/create features

    const stats = computed(() => {
      const all = orders.value
      return {
        total: all.length,
        producing: all.filter(o => o.status === 'producing').length,
        pending: all.filter(o => o.status === 'pending').length,
        completed: all.filter(o => o.status === 'completed').length,
      }
    })

    const filteredOrders = computed(() => {
      if (statusFilter.value === 'all') return orders.value
      return orders.value.filter(o => o.status === statusFilter.value)
    })

    const ganttData = computed(() => {
      const list = filteredOrders.value
      if (!list.length) return { minDate: '', maxDate: '', totalDays: 0, days: [] }

      const min = dateRange.value.minDate
      const max = dateRange.value.maxDate
      if (!min || !max) return { minDate: '', maxDate: '', totalDays: 0, days: [] }

      const d1 = new Date(min), d2 = new Date(max)
      const totalDays = Math.max(Math.ceil((d2 - d1) / 86400000) + 1, 1)
      const days = []
      for (let i = 0; i < totalDays; i++) {
        const d = new Date(d1); d.setDate(d.getDate() + i)
        days.push({ date: d.toISOString().slice(0,10), label: `${d.getMonth()+1}/${d.getDate()}`, isToday: d.toDateString() === new Date().toDateString() })
      }
      return { minDate: min, maxDate: max, totalDays, days }
    })

    function barLeft(order) {
      const min = ganttData.value.minDate
      if (!min || !order.plan_start) return 0
      return Math.max(0, (new Date(order.plan_start) - new Date(min)) / 86400000) * dayWidth.value
    }

    function barWidth(order) {
      if (!order.plan_start || !order.plan_end) return dayWidth.value
      const days = Math.max(1, (new Date(order.plan_end) - new Date(order.plan_start)) / 86400000 + 1)
      return days * dayWidth.value
    }

    function barColor(status) {
      if (status === 'producing') return 'linear-gradient(135deg,#2563eb,#3b82f6)'
      if (status === 'completed') return 'linear-gradient(135deg,#16a34a,#22c55e)'
      return 'linear-gradient(135deg,#9ca3af,#b0b7c3)'
    }

    function statusLabel(s) {
      return { producing:'生产中', pending:'待生产', completed:'已完成' }[s] || s
    }

    const dateRange = ref({ minDate: '', maxDate: '' })

    async function load() {
      loading.value = true
      try {
        const r = await api.get('/api/schedule/gantt')
        if (r.ok) {
          orders.value = r.orders
          dateRange.value = { minDate: r.min_date || '', maxDate: r.max_date || '' }
        }
      } catch (e) { showToast('加载排程失败', 'error') }
      finally { loading.value = false }
    }

    function zoomIn() { dayWidth.value = Math.min(dayWidth.value + 6, 80) }
    function zoomOut() { dayWidth.value = Math.max(dayWidth.value - 6, 20) }

    onMounted(load)

    return { orders, stats, loading, dayWidth, statusFilter, filteredOrders, ganttData, barLeft, barWidth, barColor, statusLabel, zoomIn, zoomOut }
  }
}
