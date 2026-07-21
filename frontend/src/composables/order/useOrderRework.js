import { ref } from 'vue'

import { api } from '@/lib/api.js'
import { showToast } from '@/lib/store.js'


export function useOrderRework({ load, isCompletedOrder, completedReadonlyToast }) {
  const showReworkModal = ref(false)
  const reworkOrder = ref(null)
  const reworkForm = ref({ process_id: '', quantity: 1, reason: '' })

  function openRework(order) {
    if (isCompletedOrder(order)) { completedReadonlyToast(); return }
    reworkOrder.value = order
    reworkForm.value = { process_id: '', quantity: 1, reason: '' }
    showReworkModal.value = true
  }

  async function submitRework() {
    const order = reworkOrder.value
    const data = reworkForm.value
    if (!data.process_id) { showToast('请选择工序', 'error'); return }
    if (!data.quantity || data.quantity < 1) { showToast('数量必须大于0', 'error'); return }
    if (!data.reason.trim()) { showToast('请输入返工原因', 'error'); return }
    try {
      await api.domains.scan.scan({
        order_id: order.id,
        process_id: parseInt(data.process_id),
        quantity: parseInt(data.quantity),
        report_type: 'rework',
        remark: data.reason,
      })
      showToast('返工申请已提交')
      showReworkModal.value = false
      await load()
    } catch (error) {
      showToast(error.message || '提交失败', 'error')
    }
  }

  return { showReworkModal, reworkOrder, reworkForm, openRework, submitRework }
}
