import { ref, onMounted, onBeforeUnmount, computed } from 'vue'
import { api } from '@/lib/api.js'
import { showToast } from '@/lib/store.js'
import { can } from '@/lib/auth.js'
let _html2canvas = null
async function getHtml2canvas() {
  if (!_html2canvas) {
    const m = await import('html2canvas')
    _html2canvas = m.default
  }
  return _html2canvas
}

export function useGantt() {
  const orders = ref([])
  const loading = ref(true)
  const dayWidth = ref(38)
  const scheduleScope = ref('active')
  const wsFilter = ref('')
  const serverStats = ref({ total: 0, producing: 0, pending: 0, completed: 0 })

  const canEdit = computed(() => can('schedule:edit'))
  const canManageLines = computed(() => can('settings:edit'))

  function isCompleted(order) {
    if (!order) return false
    const quantity = order.quantity || 0
    const completed = order.completed_qty || order.completed || 0
    return order.is_completed || order.status === 'completed' || (quantity > 0 && completed >= quantity)
  }

  function canAdjustOrder(order) {
    return canEdit.value && !isCompleted(order)
  }

  const stats = computed(() => {
    return serverStats.value
  })

  const filteredOrders = computed(() => {
    let arr = orders.value
    if (wsFilter.value) {
      arr = arr.filter(o => String(o.production_line_id || '') === String(wsFilter.value))
    }
    return arr
  })

  const dateRange = ref({ minDate: '', maxDate: '' })

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
      days.push({ date: d.toISOString().slice(0,10), label: (d.getMonth()+1)+'/'+d.getDate(), isToday: d.toDateString() === new Date().toDateString(), isWeekend: d.getDay() === 0 || d.getDay() === 6 })
    }
    return { minDate: min, maxDate: max, totalDays, days }
  })

  function barLeft(order) {
    const min = ganttData.value.minDate
    if (!min || !order.plan_start) return 0
    return Math.max(0, (new Date(order.plan_start) - new Date(min)) / 86400000) * dayWidth.value
  }

  // Capacity: daily load per production line
  const dailyLoad = computed(() => {
    const map = {}
    filteredOrders.value.forEach(o => {
      if (!o.plan_start || !o.plan_end || !o.production_line_id) return
      const start = new Date(o.plan_start), end = new Date(o.plan_end)
      for (let d = new Date(start); d <= end; d.setDate(d.getDate() + 1)) {
        const date = d.toISOString().slice(0,10)
        const key = date + '|' + o.production_line_id
        if (!map[key]) {
          map[key] = {
            date,
            lineId: o.production_line_id,
            line: o.production_line,
            count: 0,
            capacity: Number(o.line_capacity) > 0 ? Number(o.line_capacity) : 999,
          }
        }
        map[key].count++
      }
    })
    productionLines.value.forEach(pl => {
      Object.values(map).forEach(v => {
        if (String(v.lineId) === String(pl.id) && Number(pl.capacity_per_day) > 0) {
          v.capacity = Number(pl.capacity_per_day)
        }
      })
    })
    return Object.values(map).filter(v => v.count > v.capacity)
  })

  function isOverloaded(date, lineId) {
    if (!lineId || !date) return false
    return dailyLoad.value.some(v => v.date === date && String(v.lineId) === String(lineId))
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

  function zoomIn() { dayWidth.value = Math.min(dayWidth.value + 6, 80) }
  function zoomOut() { dayWidth.value = Math.max(dayWidth.value - 6, 20) }

  // ── Drag Resize ──
  const dragTarget = ref(null)
  const dragPreviewLeft = ref(0)
  const dragPreviewWidth = ref(0)
  let _dragStartX = 0, _dragStartWidth = 0, _dragResizeEdge = null

  function onBarMouseDown(e, order) {
    if (!canAdjustOrder(order)) return
    const bar = e.currentTarget
    const rect = bar.getBoundingClientRect()
    const offsetX = e.clientX - rect.left
    const edgeZone = 10 // px from edge = resize, middle = ignore (for double-click edit)

    if (offsetX < edgeZone) {
      _dragResizeEdge = 'left'
    } else if (offsetX > rect.width - edgeZone) {
      _dragResizeEdge = 'right'
    } else {
      return // middle click = handled by dblclick
    }

    e.preventDefault()
    _dragStartX = e.clientX
    _dragStartWidth = rect.width
    dragTarget.value = order

    const dayW = dayWidth.value
    const minDate = ganttData.value.minDate
    const orderStart = new Date(order.plan_start)

    if (_dragResizeEdge === 'right') {
      dragPreviewLeft.value = (orderStart - new Date(minDate)) / 86400000 * dayW
      dragPreviewWidth.value = rect.width
    } else {
      dragPreviewLeft.value = barLeft(order)
      dragPreviewWidth.value = rect.width
    }

    document.addEventListener('mousemove', onDragMove)
    document.addEventListener('mouseup', onDragEnd)
  }

  function onDragMove(e) {
    if (!dragTarget.value) return
    const dayW = dayWidth.value
    const dx = e.clientX - _dragStartX

    if (_dragResizeEdge === 'right') {
      const newWidth = Math.max(dayW, _dragStartWidth + dx)
      dragPreviewWidth.value = newWidth
    } else if (_dragResizeEdge === 'left') {
      const startPx = barLeft(dragTarget.value)
      const newLeft = startPx + dx
      dragPreviewLeft.value = Math.max(0, Math.round(newLeft / dayW) * dayW)
    }
  }

  async function onDragEnd() {
    document.removeEventListener('mousemove', onDragMove)
    document.removeEventListener('mouseup', onDragEnd)
    if (!dragTarget.value) return

    const order = dragTarget.value
    const dayW = dayWidth.value
    const minDate = ganttData.value.minDate

    try {
      if (_dragResizeEdge === 'right') {
        const days = Math.max(1, Math.round(dragPreviewWidth.value / dayW))
        const newEnd = new Date(order.plan_start)
        newEnd.setDate(newEnd.getDate() + days - 1)
        const endStr = newEnd.toISOString().slice(0, 10)
        await api.domains.production.updateScheduleOrder(order.id, { plan_start: order.plan_start, plan_end: endStr })
        order.plan_end = endStr
        showToast('工期已调整为 ' + days + ' 天')
      } else if (_dragResizeEdge === 'left') {
        const daysOffset = Math.round(dragPreviewLeft.value / dayW)
        const newStart = new Date(minDate)
        newStart.setDate(newStart.getDate() + daysOffset)
        const startStr = newStart.toISOString().slice(0, 10)
        await api.domains.production.updateScheduleOrder(order.id, { plan_start: startStr, plan_end: order.plan_end })
        order.plan_start = startStr
        showToast('开始日期已调整')
      }
    } catch (e) { showToast(e.message || '调整失败', 'error') }

    dragTarget.value = null
    _dragResizeEdge = null
  }

  // ── Double-click Edit ──
  const showEditModal = ref(false)
  const editForm = ref({ plan_start: '', plan_end: '', production_line_id: '' })

  function editOrderDates(order) {
    if (!canAdjustOrder(order)) return
    dragTarget.value = order
    editForm.value = { plan_start: order.plan_start || '', plan_end: order.plan_end || '', production_line_id: order.production_line_id || '' }
    showEditModal.value = true
  }

  async function saveEditDates() {
    if (!dragTarget.value) return
    try {
      await api.domains.production.updateScheduleOrder(dragTarget.value.id, {
        plan_start: editForm.value.plan_start,
        plan_end: editForm.value.plan_end,
        production_line_id: editForm.value.production_line_id || null
      })
      dragTarget.value.plan_start = editForm.value.plan_start
      dragTarget.value.plan_end = editForm.value.plan_end
      if (editForm.value.production_line_id) {
        const pl = productionLines.value.find(
          p => String(p.id) === String(editForm.value.production_line_id),
        )
        dragTarget.value.production_line = pl ? pl.name : ''
        dragTarget.value.production_line_id = editForm.value.production_line_id
      } else {
        dragTarget.value.production_line = ''
        dragTarget.value.production_line_id = null
      }
      showToast('已保存')
      showEditModal.value = false
    } catch (e) { showToast(e.message || '保存失败', 'error') }
  }

  function undoLastDrag() {
    dragTarget.value = null
    showEditModal.value = false
  }

  // ── Production Lines ──
  const productionLines = ref([])
  const showLineMgr = ref(false)
  const lineForm = ref({ name: '', remark: '', capacity_per_day: 10 })

  async function loadLines() {
    try { const d = await api.domains.production.listProductionLines(); productionLines.value = d.lines || d || [] }
    catch (e) { console.warn('Production lines load failed:', e); productionLines.value = [] }
  }

  async function addLine() {
    if (!canManageLines.value) return
    if (!lineForm.value.name.trim()) { showToast('产线名称必填', 'error'); return }
    try { await api.domains.production.createProductionLine(lineForm.value); showToast('产线已添加'); lineForm.value = { name: '', remark: '', capacity_per_day: 10 }; await loadLines() }
    catch (e) { showToast(e.message || '添加失败', 'error') }
  }

  async function delLine(line) {
    if (!canManageLines.value) return
    if (!confirm('确定删除产线「' + line.name + '」？')) return
    try { await api.domains.production.deleteProductionLine(line.id); showToast('已删除'); await loadLines() }
    catch (e) { showToast(e.message || '删除失败', 'error') }
  }

  // ── Batch Operations ──
  const selectedOrderIds = ref([])
  const batchDays = ref(1)
  const allSelected = ref(false)

  function toggleAll() {
    if (!canEdit.value) return
    allSelected.value = !allSelected.value
    selectedOrderIds.value = allSelected.value
      ? filteredOrders.value.filter(o => !isCompleted(o)).map(o => o.id)
      : []
  }

  function toggleOrder(order) {
    if (!canAdjustOrder(order)) return
    const id = typeof order === 'object' ? order.id : order
    const idx = selectedOrderIds.value.indexOf(id)
    if (idx >= 0) selectedOrderIds.value.splice(idx, 1)
    else selectedOrderIds.value.push(id)
    const editableIds = filteredOrders.value.filter(o => canAdjustOrder(o)).map(o => o.id)
    allSelected.value = editableIds.length > 0 && editableIds.every(item => selectedOrderIds.value.includes(item))
  }

  async function batchShift(direction) {
    const editableIds = new Set(filteredOrders.value.filter(o => !isCompleted(o)).map(o => o.id))
    const orderIds = selectedOrderIds.value.filter(id => editableIds.has(id))
    if (!orderIds.length) { showToast('请先选择未完成订单', 'warning'); return }
    const days = batchDays.value * (direction === 'right' ? 1 : -1)
    try {
      const r = await api.domains.production.batchShiftSchedule({ order_ids: orderIds, days })
      showToast(r.message || ('已偏移 ' + r.count + ' 个订单'))
      selectedOrderIds.value = []
      allSelected.value = false
      await load()
    } catch (e) { showToast(e.message || '批量偏移失败', 'error') }
  }

  // ── API ──
  async function load() {
    loading.value = true
    try {
      const pageSize = 200
      let offset = 0
      let hasMore = true
      let loadedOrders = []
      while (hasMore) {
        const r = await api.domains.production.getScheduleGantt({
          status: scheduleScope.value,
          limit: pageSize,
          offset,
        })
        if (r.ok === false) throw new Error(r.error || '加载排程失败')
        const pageOrders = r.orders || []
        loadedOrders = loadedOrders.concat(pageOrders)
        if (offset === 0) {
          dateRange.value = { minDate: r.min_date || '', maxDate: r.max_date || '' }
          serverStats.value = r.stats || {
            total: r.total || pageOrders.length,
            producing: pageOrders.filter(o => o.status === 'producing' && !isCompleted(o)).length,
            pending: pageOrders.filter(o => o.status === 'pending' && !isCompleted(o)).length,
            completed: pageOrders.filter(o => isCompleted(o)).length,
          }
        }
        offset = loadedOrders.length
        hasMore = Boolean(r.has_more) && pageOrders.length > 0
      }
      orders.value = loadedOrders
    } catch (e) { showToast(e.message || '加载排程失败', 'error') }
    finally { loading.value = false }
  }

  async function setScheduleScope(scope) {
    if (scheduleScope.value === scope) return
    scheduleScope.value = scope
    selectedOrderIds.value = []
    allSelected.value = false
    await load()
  }

  function onKeyDown(e) {
    if (e.key === 'Escape') undoLastDrag()
  }

  // ── Shortcuts ──
  async function shiftDays(dir, big) {
    const editableIds = new Set(filteredOrders.value.filter(o => !isCompleted(o)).map(o => o.id))
    const orderIds = selectedOrderIds.value.filter(id => editableIds.has(id))
    if (!orderIds.length) return
    const days = big ? 7 : 1
    const shiftVal = days * dir
    try {
      const r = await api.domains.production.batchShiftSchedule({ order_ids: orderIds, days: shiftVal })
      showToast(r.message || ('Shifted ' + (r.count || 0) + ' orders'))
      selectedOrderIds.value = []
      await load()
    } catch (e) { showToast(e.message || '批量调整失败', 'error') }
  }

  async function exportImage() {
    const el = document.querySelector('.gantt-scroll')
    if (!el) { showToast('未找到甘特图', 'error'); return }
    try {
      const html2canvas = await getHtml2canvas()
      const canvas = await html2canvas(el, { backgroundColor: '#ffffff', scale: 2 })
      const link = document.createElement('a')
      link.download = '生产排程_' + new Date().toISOString().slice(0,10) + '.png'
      link.href = canvas.toDataURL('image/png')
      link.click()
      showToast('排程图已导出')
    } catch (e) { showToast('导出失败', 'error') }
  }

  onMounted(() => {
    load()
    loadLines()
    document.addEventListener('keydown', onKeyDown)
  })

  onBeforeUnmount(() => {
    document.removeEventListener('keydown', onKeyDown)
    document.removeEventListener('mousemove', onDragMove)
    document.removeEventListener('mouseup', onDragEnd)
  })

  return {
    orders, stats, loading, dayWidth, scheduleScope, setScheduleScope, wsFilter,
    filteredOrders, ganttData, barLeft, barWidth, barColor, statusLabel, zoomIn, zoomOut,
    isCompleted, canAdjustOrder, dragTarget, dragPreviewLeft, dragPreviewWidth, onBarMouseDown,
    showEditModal, editForm, editOrderDates, saveEditDates, undoLastDrag,
    productionLines, showLineMgr, lineForm, addLine, delLine,
    selectedOrderIds, batchDays, batchShift, allSelected, toggleAll, toggleOrder,
    canEdit, canManageLines, shiftDays, exportImage, dailyLoad, isOverloaded,
    load, loadLines, onKeyDown
  }
}
