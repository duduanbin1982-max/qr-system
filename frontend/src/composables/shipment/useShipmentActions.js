import { ref } from 'vue'

import { api } from '@/lib/api.js'
import { showToast } from '@/lib/store.js'


function requestKey(prefix, id) {
  const random = globalThis.crypto?.randomUUID?.()
    || `${Date.now()}-${Math.random().toString(16).slice(2)}`
  return `${prefix}:${id}:${random}`
}


export function useShipmentActions({ reload }) {
  const detailShipment = ref(null)
  const showDetail = ref(false)

  const showPayModal = ref(false)
  const payTarget = ref(null)
  const payMode = ref('receipt')
  const payAmount = ref(0)
  const payMethod = ref('')
  const payDate = ref(new Date().toISOString().slice(0, 10))
  const payRemark = ref('')
  const payIdempotencyKey = ref('')

  const showCancelModal = ref(false)
  const cancelTarget = ref(null)
  const cancelReason = ref('')

  const showReceiveModal = ref(false)
  const receiveTarget = ref(null)
  const receiverName = ref('')
  const receiveDate = ref(new Date().toISOString().slice(0, 10))

  const showLogisticsModal = ref(false)
  const logisticsTarget = ref(null)
  const logisticsCompany = ref('')
  const trackingNo = ref('')

  async function viewDetail(shipment) {
    try {
      detailShipment.value = await api.domains.shipments.getShipment(shipment.id)
      showDetail.value = true
    } catch (error) {
      showToast(error.message || '加载详情失败', 'error')
    }
  }

  function openCancel(shipment) {
    cancelTarget.value = shipment
    cancelReason.value = ''
    showCancelModal.value = true
  }

  async function doCancel() {
    if (!cancelReason.value.trim()) {
      showToast('请填写取消或冲销原因', 'error')
      return
    }
    try {
      const result = await api.domains.shipments.cancelShipment(cancelTarget.value.id, {
        reason: cancelReason.value.trim(),
      })
      showToast(result.status === 'reversed' ? '出库单已冲销' : '出库单已取消')
      showCancelModal.value = false
      await reload()
    } catch (error) {
      showToast(error.message || '取消或冲销失败', 'error')
    }
  }

  function openReceive(shipment) {
    receiveTarget.value = shipment
    receiverName.value = ''
    receiveDate.value = new Date().toISOString().slice(0, 10)
    showReceiveModal.value = true
  }

  async function doReceive() {
    try {
      await api.domains.shipments.receiveShipment(receiveTarget.value.id, {
        receiver: receiverName.value.trim(),
        receive_date: receiveDate.value,
      })
      showToast('已签收')
      showReceiveModal.value = false
      await reload()
    } catch (error) {
      showToast(error.message || '签收失败', 'error')
    }
  }

  function openLogistics(shipment) {
    logisticsTarget.value = shipment
    logisticsCompany.value = shipment.logistics_company || ''
    trackingNo.value = shipment.tracking_no || ''
    showLogisticsModal.value = true
  }

  async function saveLogistics() {
    try {
      await api.domains.shipments.updateLogistics(logisticsTarget.value.id, {
        logistics_company: logisticsCompany.value.trim(),
        tracking_no: trackingNo.value.trim(),
      })
      showToast('物流信息已更新')
      showLogisticsModal.value = false
      await reload()
    } catch (error) {
      showToast(error.message || '物流信息更新失败', 'error')
    }
  }

  function openPayment(shipment, mode = 'receipt') {
    payTarget.value = shipment
    payMode.value = mode
    payAmount.value = mode === 'refund'
      ? Number(shipment.paid_amount || 0)
      : Math.max(0, Number(shipment.receivable_amount || 0) - Number(shipment.paid_amount || 0))
    payMethod.value = ''
    payDate.value = new Date().toISOString().slice(0, 10)
    payRemark.value = ''
    payIdempotencyKey.value = requestKey(mode, shipment.id)
    showPayModal.value = true
  }

  async function doPayment() {
    if (!payAmount.value || payAmount.value <= 0) {
      showToast(`请输入有效${payMode.value === 'refund' ? '退款' : '收款'}金额`, 'error')
      return
    }
    const payload = {
      amount: payAmount.value,
      method: payMethod.value,
      payment_date: payDate.value,
      remark: payRemark.value,
      idempotency_key: payIdempotencyKey.value,
    }
    try {
      if (payMode.value === 'refund') {
        await api.domains.shipments.refundPayment(payTarget.value.id, payload)
      } else {
        await api.domains.shipments.recordPayment(payTarget.value.id, payload)
      }
      showToast(payMode.value === 'refund' ? '退款成功' : '收款成功')
      showPayModal.value = false
      await reload()
    } catch (error) {
      showToast(error.message || '收付款失败', 'error')
    }
  }

  function isPaymentReversed(payment) {
    return Boolean(detailShipment.value?.payments?.some(
      row => row.type === 'reversal' && row.reversal_of_id === payment.id,
    ))
  }

  function paymentTypeLabel(type) {
    return { receipt: '收款', refund: '退款', reversal: '冲销' }[type] || type
  }

  function eventLabel(type) {
    return {
      legacy_imported: '历史导入',
      created: '创建',
      updated: '编辑',
      completed: '完成出库',
      received: '签收',
      cancelled: '取消',
      reversed: '冲销出库',
      logistics_updated: '更新物流',
      payment_received: '收款',
      payment_refunded: '退款',
      payment_reversed: '冲销收付款',
    }[type] || type
  }

  async function reversePayment(payment) {
    if (!confirm(`确认冲销流水 ${payment.payment_no} 吗？`)) return
    try {
      await api.domains.shipments.reversePayment(detailShipment.value.id, payment.id, {
        idempotency_key: requestKey('payment-reversal', payment.id),
      })
      showToast('收付款流水已冲销')
      detailShipment.value = await api.domains.shipments.getShipment(detailShipment.value.id)
      await reload()
    } catch (error) {
      showToast(error.message || '流水冲销失败', 'error')
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
    payMode,
    payAmount,
    payMethod,
    payDate,
    payRemark,
    showCancelModal,
    cancelTarget,
    cancelReason,
    showReceiveModal,
    receiveTarget,
    receiverName,
    receiveDate,
    showLogisticsModal,
    logisticsTarget,
    logisticsCompany,
    trackingNo,
    viewDetail,
    openCancel,
    doCancel,
    openReceive,
    doReceive,
    openLogistics,
    saveLogistics,
    openPayment,
    doPayment,
    isPaymentReversed,
    paymentTypeLabel,
    eventLabel,
    reversePayment,
    doComplete,
  }
}
