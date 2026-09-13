import { ref } from 'vue'

import { api } from '@/lib/api.js'
import { showToast } from '@/lib/store.js'
import { useOrderFormSearch } from './useOrderFormSearch.js'


const emptyForm = () => ({
  order_no: '', customer: '', customer_id: null, product_name: '', product_id: null, product_code: '',
  model: '', spec: '', style: '', upper_opening: '', plate_thickness: '', category: '',
  quantity: 1, plan_start: '', plan_end: '', deadline: '', route_id: '',
  production_line_id: null, remark: '', status: 'pending',
  priority_level: 3, is_expedited: false, priority_reason: '',
  priority_effective_at: '', schedule_policy: 'auto', schedule_change_reason: '',
})


export function useOrderEditor({ customers, products, processRoutes, loadDropdownData, load }) {
  const showModal = ref(false)
  const modalEdit = ref(false)
  const modalId = ref(null)
  const form = ref(emptyForm())
  const originalScheduleState = ref(null)
  const search = useOrderFormSearch({ form, products, processRoutes })

  function isCompletedOrder(order) {
    return (order?.status || '') === 'completed'
  }

  function completedReadonlyToast() {
    showToast('已完成订单已归档，只读，请先重新打开订单', 'error')
  }

  function onCustomerChange() {
    const customerId = form.value.customer_id
    if (!customerId) {
      form.value.customer = ''
      return
    }
    const selected = customers.value.find(customer => customer.id == customerId)
    form.value.customer = selected ? selected.name : ''
  }

  async function openAdd() {
    form.value = emptyForm()
    originalScheduleState.value = null
    search.resetSearch()
    modalEdit.value = false
    modalId.value = null
    await loadDropdownData()
    try {
      const data = await api.domains.orders.nextOrderNo()
      form.value.order_no = data.order_no
    } catch (error) {
      showToast(`自动生成订单号失败：${error.message || '请手动输入'}`, 'warn')
    }
    showModal.value = true
  }

  async function openEdit(order) {
    if (isCompletedOrder(order)) {
      completedReadonlyToast()
      return false
    }
    form.value = {
      ...emptyForm(),
      order_no: order.order_no || '',
      customer: order.customer || '',
      customer_id: order.customer_id || null,
      product_name: order.product_name || '',
      product_id: order.product_id || null,
      product_code: order.product_code || '',
      quantity: order.quantity || 1,
      plan_start: order.plan_start || '',
      plan_end: order.plan_end || '',
      deadline: order.deadline || '',
      route_id: order.route_id || '',
      production_line_id: order.production_line_id || null,
      remark: order.remark || '',
      status: order.status || 'pending',
      priority_level: Number(order.priority_level || 3),
      is_expedited: Boolean(Number(order.is_expedited || 0)),
      priority_reason: order.priority_reason || '',
      priority_effective_at: order.priority_effective_at || '',
      schedule_policy: order.schedule_policy || 'auto',
      schedule_change_reason: '',
    }
    originalScheduleState.value = {
      priority_level: Number(order.priority_level || 3),
      is_expedited: Boolean(Number(order.is_expedited || 0)),
      deadline: order.deadline || '',
      priority_effective_at: order.priority_effective_at || '',
      schedule_policy: order.schedule_policy || 'auto',
    }
    search.productSearch.value = order.product_code || ''
    search.routeSearch.value = order.route_name || ''
    modalEdit.value = true
    modalId.value = order.id
    showModal.value = true
    await loadDropdownData()
    search.syncRoute(order.route_id, search.routeSearch.value)
    return true
  }

  async function save() {
    if (!form.value.order_no) { showToast('请输入订单号', 'error'); return }
    if (!(form.value.product_name || '').trim()) { showToast('请输入产品名称', 'error'); return }
    if (!form.value.quantity || form.value.quantity < 1) { showToast('请输入有效数量', 'error'); return }
    try {
      const data = { ...form.value, quantity: parseInt(form.value.quantity) }
      if (data.route_id) data.route_id = parseInt(data.route_id) || null
      else if (modalEdit.value) data.route_id = null
      else delete data.route_id
      if (data.customer_id) data.customer_id = parseInt(data.customer_id)
      if (data.production_line_id) data.production_line_id = parseInt(data.production_line_id) || null
      else data.production_line_id = null
      data.priority_level = parseInt(data.priority_level, 10) || 3
      data.is_expedited = Boolean(data.is_expedited)
      data.priority_effective_at = data.priority_effective_at || ''
      data.schedule_policy = data.schedule_policy || 'auto'

      if (modalEdit.value && originalScheduleState.value) {
        const changed = [
          data.priority_level !== originalScheduleState.value.priority_level,
          data.is_expedited !== originalScheduleState.value.is_expedited,
          (data.deadline || '') !== originalScheduleState.value.deadline,
          (data.priority_effective_at || '') !== originalScheduleState.value.priority_effective_at,
          data.schedule_policy !== originalScheduleState.value.schedule_policy,
        ].some(Boolean)
        if (changed && !(data.schedule_change_reason || '').trim()) {
          showToast('调整优先级、加急、交期或排程策略时必须填写本次调整原因', 'error')
          return
        }
      } else {
        delete data.schedule_change_reason
      }

      if (modalEdit.value) {
        await api.domains.orders.updateOrder(modalId.value, data)
        showToast('更新成功')
      } else {
        await api.domains.orders.createOrder(data)
        showToast('创建成功')
      }
      showModal.value = false
      await load()
    } catch (error) {
      showToast(error.message || '保存失败', 'error')
    }
  }

  async function del(order) {
    if (isCompletedOrder(order)) { completedReadonlyToast(); return }
    if (!confirm(`确定将订单 ${order.order_no} 移入回收站吗？\n30天后可从回收站彻底删除。`)) return
    try {
      await api.domains.orders.deleteOrder(order.id)
      showToast('已移至回收站')
      await load()
    } catch (error) {
      showToast(error.message || '删除失败', 'error')
    }
  }

  async function reopenOrder(order) {
    const reason = window.prompt('请输入重新打开订单的原因：', '')
    if (reason === null) return
    if (!reason.trim()) { showToast('请填写重新打开原因', 'error'); return }
    try {
      await api.domains.orders.reopenOrder(order.id, { reason: reason.trim(), status: 'producing' })
      showToast('订单已重新打开')
      await load()
    } catch (error) {
      showToast(error.message || '重新打开失败', 'error')
    }
  }

  return {
    showModal, modalEdit, modalId, form,
    ...search,
    onCustomerChange,
    openAdd, openEdit, save, del, reopenOrder,
    isCompletedOrder, completedReadonlyToast,
  }
}
