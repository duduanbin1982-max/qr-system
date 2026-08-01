// QR Code Composable — extracted from useOrder.js
import { ref } from 'vue'
import { api } from '@/lib/api.js'
import { showToast } from '@/lib/store.js'

export function useQrcode() {
  const showQrPrint = ref(false)
  const qrPrintOrder = ref(null)
  const qrMode = ref('order')
  const qrCodes = ref([])
  const qrPrintLoading = ref(false)
  const qrPrintCopies = ref(1)
  const qrPrintSize = ref('small')
  const qrPrintRecording = ref(false)

  function qrPrintCount(order) {
    const count = Number(order?.qr_print_count || 0)
    return Number.isFinite(count) && count > 0 ? count : 0
  }

  function formatQrPrintTime(value) {
    return value ? String(value).slice(0, 16) : '-'
  }

  function qrPrintTitle(order) {
    const count = qrPrintCount(order)
    if (!count) return '打印二维码'
    const operator = order?.qr_printed_by_name || '未知人员'
    return `已打印 ${count} 次；最近 ${formatQrPrintTime(order?.qr_printed_at)}，${operator}`
  }

  function openQrPrint(o) {
    qrPrintOrder.value = o
    const existingMode = (o.qr_mode || '').trim()
    qrMode.value = existingMode || 'order'
    qrCodes.value = []
    qrPrintCopies.value = 1
    showQrPrint.value = true
    if (qrPrintCount(o) > 0) {
      showToast(`该订单二维码已打印 ${qrPrintCount(o)} 次，本次属于重新打印`, 'warn')
    }
  }

  async function generateQrCodes() {
    if (!qrPrintOrder.value) return
    qrPrintLoading.value = true
    qrCodes.value = []
    try {
      const d = await api.domains.qrcode.qrcodeBatch({
        order_ids: [qrPrintOrder.value.id],
        mode: qrMode.value
      })
      qrCodes.value = d.codes || []
      if (!qrCodes.value.length) {
        showToast('未生成二维码', 'warn')
      } else {
        const modeText = qrMode.value === 'serial' ? '序列号模式' : '订单模式'
        showToast(`已生成 ${qrCodes.value.length} 个二维码 (${modeText})`)
      }
    } catch(e) {
      showToast('二维码生成失败: ' + (e.message || '未知错误'), 'error')
    } finally {
      qrPrintLoading.value = false
    }
  }

  function switchQrMode(mode) {
    const existingMode = ((qrPrintOrder.value?.qr_mode) || '').trim()
    if (existingMode && existingMode !== mode) {
      showToast('该订单已锁定为 ' + (existingMode === 'serial' ? '序列号模式' : '订单模式') + '，不可切换', 'warn')
      return
    }
    qrMode.value = mode
    qrCodes.value = []
  }

  function escapeHtml(text) {
    if (!text) return ''
    const div = document.createElement('div')
    div.appendChild(document.createTextNode(text))
    return div.innerHTML
  }

  function printQrCodes() {
    if (!qrCodes.value.length) { showToast('请先生成二维码', 'warn'); return }
    if (qrPrintRecording.value) return
    const previousPrints = qrPrintCount(qrPrintOrder.value)
    if (previousPrints > 0 && !window.confirm(
      `该订单二维码已打印 ${previousPrints} 次，确定要重新打印吗？`
    )) return
    const root = document.getElementById('qr-print-root')
    if (!root) { showToast('打印容器未找到', 'error'); return }
    qrPrintRecording.value = true
    root.innerHTML = ''
    const grid = document.createElement('div')
    grid.className = 'qr-print-grid'
    const images = []
    for (let copy = 0; copy < qrPrintCopies.value; copy++) {
      for (const code of qrCodes.value) {
        const card = document.createElement('div')
        card.className = 'qr-card'
        const img = document.createElement('img')
        img.src = code.qrcode
        img.alt = code.serial_no || code.order_no || ''
        img.setAttribute('decoding', 'sync')
        images.push(img)
        card.appendChild(img)
        const info = document.createElement('div')
        info.className = 'qr-label-info'
        const no = document.createElement('div')
        no.className = 'qr-label-no'
        no.textContent = code.serial_no || code.order_no || ''
        info.appendChild(no)
        if (code.product_code) {
          const pc = document.createElement('div')
          pc.className = 'qr-label-code'
          pc.textContent = code.product_code
          info.appendChild(pc)
        }
        card.appendChild(info)
        grid.appendChild(card)
      }
    }
    root.appendChild(grid)
    var oldParent = root.parentNode
    var oldNext = root.nextSibling
    document.body.appendChild(root)

    async function doPrint() {
      try {
        window.print()
        const result = await api.domains.orders.recordQrPrint(qrPrintOrder.value.id, {
          mode: qrMode.value,
          copies: qrPrintCopies.value,
          label_count: qrCodes.value.length * qrPrintCopies.value
        })
        Object.assign(qrPrintOrder.value, result.print_status || {})
        showToast(previousPrints > 0 ? '重新打印已记录' : '打印状态已记录')
      } catch (error) {
        showToast('打印已发起，但状态记录失败: ' + (error.message || '未知错误'), 'error')
      } finally {
        qrPrintRecording.value = false
      }
      setTimeout(function() {
        if (oldParent) {
          if (oldNext) oldParent.insertBefore(root, oldNext)
          else oldParent.appendChild(root)
        }
      }, 500)
    }

    let loaded = 0
    if (images.length === 0) { doPrint(); return }
    images.forEach(function(img) {
      if (img.complete) {
        loaded++
        if (loaded === images.length) doPrint()
      } else {
        img.onload = img.onerror = function() {
          loaded++
          if (loaded === images.length) doPrint()
        }
      }
    })
  }

  return {
    showQrPrint, qrPrintOrder, qrMode, qrCodes, qrPrintLoading,
    qrPrintCopies, qrPrintSize, qrPrintRecording,
    openQrPrint, generateQrCodes, switchQrMode, printQrCodes,
    qrPrintCount, qrPrintTitle, formatQrPrintTime
  }
}
