import { ref } from 'vue'

import { api } from '@/lib/api.js'
import { showToast } from '@/lib/store.js'


export function useShipmentActions({ reload }) {
  const detailShipment = ref(null)
  const showDetail = ref(false)
  const showPayModal = ref(false)
  const payTarget = ref(null)
  const payAmount = ref(0)
  const payMethod = ref('')
  const payDate = ref(new Date().toISOString().slice(0, 10))
  const payRemark = ref('')

  async function del(shipment) {
    let impactInfo = ''
    try {
      const result = await api.domains.shipments.shipmentImpact(shipment.id)
      if (result.items > 0) impactInfo = `（含 ${result.items} 个物品，将自动归还库存）`
    } catch (error) {
      // Impact text is advisory; deletion confirmation remains available.
    }
    if (!confirm(`确定删除出库单 ${shipment.shipment_no} 吗？${impactInfo}`)) return
    try {
      await api.domains.shipments.deleteShipment(shipment.id)
      showToast('删除成功')
      await reload()
    } catch (error) {
      showToast(error.message || '删除失败', 'error')
    }
  }

  async function viewDetail(shipment) {
    try {
      detailShipment.value = await api.domains.shipments.getShipment(shipment.id)
      showDetail.value = true
    } catch (error) {
      showToast('加载详情失败', 'error')
    }
  }

  async function doReceive(shipment) {
    if (!confirm(`确认签收 ${shipment.shipment_no} 吗？`)) return
    try {
      await api.domains.shipments.receiveShipment(shipment.id, {
        receiver: '',
        receive_date: new Date().toISOString().slice(0, 10),
      })
      showToast('已签收')
      await reload()
    } catch (error) {
      showToast(error.message || '签收失败', 'error')
    }
  }

  function openPayment(shipment) {
    payTarget.value = shipment
    payAmount.value = (shipment.receivable_amount || 0) - (shipment.paid_amount || 0)
    payMethod.value = ''
    payDate.value = new Date().toISOString().slice(0, 10)
    payRemark.value = ''
    showPayModal.value = true
  }

  async function doPayment() {
    if (!payAmount.value || payAmount.value <= 0) {
      showToast('请输入有效收款金额', 'error')
      return
    }
    try {
      await api.domains.shipments.recordPayment(payTarget.value.id, {
        amount: payAmount.value,
        method: payMethod.value,
        remark: payRemark.value,
      })
      showToast('收款成功')
      showPayModal.value = false
      await reload()
    } catch (error) {
      showToast(error.message || '收款失败', 'error')
    }
  }

  async function doComplete(shipment) {
    if (!confirm(`确定完成出库单 ${shipment.shipment_no} ？将扣减库存。`)) return
    try {
      await api.domains.shipments.completeShipment(shipment.id)
      showToast('出库完成')
      await reload()
    } catch (error) {
      showToast(error.message || '出库失败', 'error')
    }
  }

  return {
    detailShipment,
    showDetail,
    showPayModal,
    payTarget,
    payAmount,
    payMethod,
    payDate,
    payRemark,
    del,
    viewDetail,
    doReceive,
    openPayment,
    doPayment,
    doComplete,
  }
}
