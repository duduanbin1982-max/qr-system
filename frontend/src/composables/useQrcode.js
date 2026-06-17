// QR Code Composable — extracted from useOrder.js
import { ref } from '''vue'''
import { api } from '''@/lib/api.js'''
import { showToast } from '''@/lib/store.js'''

export function useQrcode() {
  const showQrPrint = ref(false)
  const qrPrintOrder = ref(null)
  const qrMode = ref('''order''')
  const qrCodes = ref([])
  const qrPrintLoading = ref(false)
  const qrPrintCopies = ref(1)
  const qrPrintSize = ref('''small''')

  function openQrPrint(o) {
    qrPrintOrder.value = o
    const existingMode = (o.qr_mode || '''''').trim()
    qrMode.value = existingMode || '''order'''
    qrCodes.value = []
    showQrPrint.value = true
  }

  async function generateQrCodes() {
    if (!qrPrintOrder.value) return
    qrPrintLoading.value = true
    qrCodes.value = []
    try {
      const d = await api.post('''/api/qrcode/batch''', {
        order_ids: [qrPrintOrder.value.id],
        mode: qrMode.value
      })
      qrCodes.value = d.codes || []
      if (!qrCodes.value.length) {
        showToast('''未生成二维码''', '''warn''')
      } else {
        const modeText = qrMode.value === '''serial''' ? '''序列号模式''' : '''订单模式'''
        showToast(`已生成 ${qrCodes.value.length} 个二维码 (${modeText})`)
      }
    } catch(e) {
      showToast('''二维码生成失败: ''' + (e.message || '''未知错误'''), '''error''')
    } finally {
      qrPrintLoading.value = false
    }
  }

  function switchQrMode(mode) {
    const existingMode = ((qrPrintOrder.value?.qr_mode) || '''''').trim()
    if (existingMode && existingMode !== mode) {
      showToast('''该订单已锁定为 ''' + (existingMode === '''serial''' ? '''序列号模式''' : '''订单模式''') + '''，不可切换''', '''warn''')
      return
    }
    qrMode.value = mode
    qrCodes.value = []
  }

  function escapeHtml(text) {
    if (!text) return ''''''
    const div = document.createElement('''div''')
    div.appendChild(document.createTextNode(text))
    return div.innerHTML
  }

  function printQrCodes() {
    if (!qrCodes.value.length) { showToast('''请先生成二维码''', '''warn'''); return }
    const root = document.getElementById('''qr-print-root''')
    if (!root) { showToast('''打印容器未找到''', '''error'''); return }
    root.innerHTML = ''''''
    const grid = document.createElement('''div''')
    grid.className = '''qr-print-grid'''
    const images = []
    for (let copy = 0; copy < qrPrintCopies.value; copy++) {
      for (const code of qrCodes.value) {
        const card = document.createElement('''div''')
        card.className = '''qr-card'''
        const img = document.createElement('''img''')
        img.src = code.qrcode
        img.alt = code.serial_no || code.order_no || ''''''
        img.setAttribute('''decoding''', '''sync''')
        images.push(img)
        card.appendChild(img)
        const info = document.createElement('''div''')
        info.className = '''qr-label-info'''
        const no = document.createElement('''div''')
        no.className = '''qr-label-no'''
        no.textContent = code.serial_no || code.order_no || ''''''
        info.appendChild(no)
        if (code.product_code) {
          const pc = document.createElement('''div''')
          pc.className = '''qr-label-code'''
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

    function doPrint() {
      window.print()
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
    qrPrintCopies, qrPrintSize,
    openQrPrint, generateQrCodes, switchQrMode, printQrCodes
  }
}
