import { ref } from 'vue'
import { api } from '@/lib/api.js'
import { showToast } from '@/lib/store.js'

export function useScanReport() {
  const scanCode = ref('')
  const scanning = ref(false)
  const order = ref(null)
  const reportProcess = ref('')
  const reportQty = ref(1)
  const reportType = ref('normal')
  const reportRemark = ref('')
  const serialNo = ref(null)
  const reporting = ref(false)

  async function doScan() {
    const code = scanCode.value.trim()
    if (!code) { showToast('请输入或扫描订单号/二维码', 'error'); return }
    scanning.value = true
    try {
      const d = await api.domains.scan.scan({ code })
      order.value = d.order
      serialNo.value = (d.item && d.item.serial_no) || null
      reportType.value = 'normal'
      selectDefaultProcess()
      reportRemark.value = ''
    } catch (e) {
      showToast(e.message || '扫描失败', 'error')
      order.value = null
    } finally {
      scanning.value = false
    }
  }

  async function doReport() {
    if (!order.value) { showToast('请先扫描订单', 'error'); return }
    if (!reportProcess.value) { showToast('请选择工序', 'error'); return }
    const process = selectedProcess()
    if (reportType.value === 'normal' && !process?.normal_reportable) {
      showToast('当前工序不满足报工顺序或数量条件', 'error')
      return
    }
    const qty = parseInt(reportQty.value)
    if (!qty || qty <= 0) { showToast('请输入有效数量', 'error'); return }

    reporting.value = true
    try {
      await api.domains.scan.report({
        order_id: order.value.id,
        process_id: parseInt(reportProcess.value),
        quantity: qty,
        report_type: reportType.value,
        remark: reportRemark.value,
        serial_no: serialNo.value
      })
      showToast('报工成功！')
      reportQty.value = 1
      reportRemark.value = ''
      if (order.value) {
        try {
          const d = await api.domains.scan.scan({ code: serialNo.value || order.value.order_no })
          if (d.order) {
            order.value = d.order
            serialNo.value = (d.item && d.item.serial_no) || null
            selectDefaultProcess()
          }
        } catch (_) { /* keep existing order data */ }
      }
    } catch (e) {
      showToast(e.message || '报工失败', 'error')
    } finally {
      reporting.value = false
    }
  }

  function pctDone() {
    if (!order.value || !order.value.quantity) return 0
    return Math.min(100, Math.round((order.value.completed || 0) / order.value.quantity * 100))
  }

  function selectedProcess() {
    return (order.value?.processes || []).find(p => String(p.process_id) === String(reportProcess.value))
  }

  function syncReportQuantity() {
    const process = selectedProcess()
    const maximum = process?.max_report_quantity || order.value?.quantity || 1
    reportQty.value = serialNo.value ? 1 : Math.max(1, Math.min(parseInt(reportQty.value) || 1, maximum))
  }

  function selectDefaultProcess() {
    const processes = order.value?.processes || []
    const preferred = processes.find(p => p.normal_reportable)
    reportProcess.value = preferred?.process_id || order.value?.current_process?.process_id || ''
    syncReportQuantity()
  }

  function syncReportSelection() {
    if (reportType.value === 'normal' && !selectedProcess()?.normal_reportable) {
      selectDefaultProcess()
      return
    }
    syncReportQuantity()
  }

  function processOrderLabel() {
    if (order.value?.process_order_scope === 'serial_sequential') return '序列号当前工序'
    return order.value?.process_order_mode === 'out_of_order' ? '跨工序补报' : '按工艺顺序'
  }

  return {
    scanCode, scanning, order, doScan,
    reportProcess, reportQty, reportType, reportRemark, serialNo, reporting, doReport,
    pctDone, selectedProcess, syncReportQuantity, syncReportSelection, processOrderLabel
  }
}
