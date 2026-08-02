import { ref } from 'vue'

import { api } from '@/lib/api.js'
import { showToast } from '@/lib/store.js'


export function useGanttEditor({
  dayWidth,
  ganttData,
  barLeft,
  canAdjustOrder,
  productionLines,
}) {
  const dragTarget = ref(null)
  const dragPreviewLeft = ref(0)
  const dragPreviewWidth = ref(0)
  const showEditModal = ref(false)
  const editForm = ref({ plan_start: '', plan_end: '', production_line_id: '' })
  let dragStartX = 0
  let dragStartWidth = 0
  let dragResizeEdge = null

  function onBarMouseDown(event, order) {
    if (!canAdjustOrder(order)) return
    const bar = event.currentTarget
    const rect = bar.getBoundingClientRect()
    const offsetX = event.clientX - rect.left
    if (offsetX < 10) dragResizeEdge = 'left'
    else if (offsetX > rect.width - 10) dragResizeEdge = 'right'
    else return

    event.preventDefault()
    dragStartX = event.clientX
    dragStartWidth = rect.width
    dragTarget.value = order
    if (dragResizeEdge === 'right') {
      dragPreviewLeft.value = (
        (new Date(order.plan_start) - new Date(ganttData.value.minDate))
        / 86400000
        * dayWidth.value
      )
    } else {
      dragPreviewLeft.value = barLeft(order)
    }
    dragPreviewWidth.value = rect.width
    document.addEventListener('mousemove', onDragMove)
    document.addEventListener('mouseup', onDragEnd)
  }

  function onDragMove(event) {
    if (!dragTarget.value) return
    const delta = event.clientX - dragStartX
    if (dragResizeEdge === 'right') {
      dragPreviewWidth.value = Math.max(dayWidth.value, dragStartWidth + delta)
    } else if (dragResizeEdge === 'left') {
      const newLeft = barLeft(dragTarget.value) + delta
      dragPreviewLeft.value = Math.max(
        0,
        Math.round(newLeft / dayWidth.value) * dayWidth.value,
      )
    }
  }

  async function onDragEnd() {
    removeDragListeners()
    if (!dragTarget.value) return
    const order = dragTarget.value
    try {
      if (dragResizeEdge === 'right') await saveRightResize(order)
      else if (dragResizeEdge === 'left') await saveLeftResize(order)
    } catch (error) {
      showToast(error.message || '调整失败', 'error')
    }
    dragTarget.value = null
    dragResizeEdge = null
  }

  async function saveRightResize(order) {
    const days = Math.max(1, Math.round(dragPreviewWidth.value / dayWidth.value))
    const newEnd = new Date(order.plan_start)
    newEnd.setDate(newEnd.getDate() + days - 1)
    const planEnd = newEnd.toISOString().slice(0, 10)
    await api.domains.production.updateScheduleOrder(order.id, {
      plan_start: order.plan_start,
      plan_end: planEnd,
    })
    order.plan_end = planEnd
    showToast(`工期已调整为 ${days} 天`)
  }

  async function saveLeftResize(order) {
    const daysOffset = Math.round(dragPreviewLeft.value / dayWidth.value)
    const newStart = new Date(ganttData.value.minDate)
    newStart.setDate(newStart.getDate() + daysOffset)
    const planStart = newStart.toISOString().slice(0, 10)
    await api.domains.production.updateScheduleOrder(order.id, {
      plan_start: planStart,
      plan_end: order.plan_end,
    })
    order.plan_start = planStart
    showToast('开始日期已调整')
  }

  function editOrderDates(order) {
    if (!canAdjustOrder(order)) return
    dragTarget.value = order
    editForm.value = {
      plan_start: order.plan_start || '',
      plan_end: order.plan_end || '',
      production_line_id: order.production_line_id || '',
    }
    showEditModal.value = true
  }

  async function saveEditDates() {
    if (!dragTarget.value) return
    try {
      await api.domains.production.updateScheduleOrder(dragTarget.value.id, {
        plan_start: editForm.value.plan_start,
        plan_end: editForm.value.plan_end,
        production_line_id: editForm.value.production_line_id || null,
      })
      applyEditedDates()
      showToast('已保存')
      showEditModal.value = false
    } catch (error) {
      showToast(error.message || '保存失败', 'error')
    }
  }

  function applyEditedDates() {
    dragTarget.value.plan_start = editForm.value.plan_start
    dragTarget.value.plan_end = editForm.value.plan_end
    const line = productionLines.value.find(
      item => String(item.id) === String(editForm.value.production_line_id),
    )
    dragTarget.value.production_line = line?.name || ''
    dragTarget.value.production_line_id = editForm.value.production_line_id || null
  }

  function undoLastDrag() {
    dragTarget.value = null
    showEditModal.value = false
  }

  function removeDragListeners() {
    document.removeEventListener('mousemove', onDragMove)
    document.removeEventListener('mouseup', onDragEnd)
  }

  function cleanup() {
    removeDragListeners()
  }

  return {
    dragTarget,
    dragPreviewLeft,
    dragPreviewWidth,
    showEditModal,
    editForm,
    onBarMouseDown,
    editOrderDates,
    saveEditDates,
    undoLastDrag,
    cleanup,
  }
}
