// ScanReport Component — 扫码报工
import { ref, onMounted } from '../../vendor/vue.esm.js'
import { api } from '../../api.js?v=56'
import { showToast } from '../../store.js?v=56'
import { auth } from '../../auth.js?v=56'

export default {
  template: '#scan-report-template',
  setup() {
    const scanCode = ref('')
    const scanning = ref(false)
    const order = ref(null)

    // 报工表单
    const reportProcess = ref('')
    const reportQty = ref(1)
    const reportType = ref('normal')
    const reportRemark = ref('')
    const serialNo = ref(null)
    const reporting = ref(false)

    // RBAC

    async function doScan() {
      const code = scanCode.value.trim()
      if (!code) { showToast('请输入或扫描订单号/二维码','error'); return }
      scanning.value = true
      try {
        const d = await api.scan({ code })
        order.value = d.order
        serialNo.value = (d.item && d.item.serial_no) || null
        // 自动选当前工序
        if (order.value.processes && order.value.processes.length) {
          for (const p of order.value.processes) {
            if (p.completed < order.value.quantity) { reportProcess.value = p.process_id; break }
          }
          if (!reportProcess.value) reportProcess.value = order.value.processes[0].process_id
        }
        reportType.value = 'normal'
        reportQty.value = 1
        reportRemark.value = ''
      } catch(e) {
        showToast(e.message || '扫描失败','error')
        order.value = null
      } finally {
        scanning.value = false
      }
    }

    async function doReport() {
      if (!order.value) { showToast('请先扫描订单','error'); return }
      if (!reportProcess.value) { showToast('请选择工序','error'); return }
      const qty = parseInt(reportQty.value)
      if (!qty || qty <= 0) { showToast('请输入有效数量','error'); return }

      reporting.value = true
      try {
        await api.report({
          order_id: order.value.id,
          process_id: parseInt(reportProcess.value),
          quantity: qty,
          type: reportType.value,
          remark: reportRemark.value,
          serial_no: serialNo.value
        })
        showToast('报工成功！')
        reportQty.value = 1
        reportRemark.value = ''
        // 重新扫描刷新数据
        scanCode.value = order.value.order_no
        await doScan()
      } catch(e) {
        showToast(e.message || '报工失败','error')
      } finally {
        reporting.value = false
      }
    }

    function pctDone() {
      if (!order.value || !order.value.quantity) return 0
      return Math.min(100, Math.round((order.value.completed || 0) / order.value.quantity * 100))
    }

    return {
      scanCode, scanning, order, doScan,
      reportProcess, reportQty, reportType, reportRemark, serialNo, reporting, doReport,
      pctDone, auth
    }
  }
}
