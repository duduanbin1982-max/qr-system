import { showToast } from '@/lib/store.js'


function escapeHtml(value) {
  if (!value) return ''
  return String(value)
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#39;')
}

export function useDeliveryNote() {
  function printDeliveryNote(shipment) {
    const now = new Date().toLocaleString('zh-CN')
    const detailItems = shipment.items || []
    const totalQuantity = detailItems.reduce((sum, item) => sum + (item.quantity || 0), 0)
    const html = `<!DOCTYPE html><html><head><meta charset="UTF-8"><title>送货单-${shipment.shipment_no}</title>
<style>body{font-family:'SimSun',serif;padding:40px;max-width:700px;margin:0 auto;color:#333}
h2{text-align:center;font-size:22px;margin-bottom:4px}h4{text-align:center;font-weight:400;color:#666;margin:0 0 24px}
.row{display:flex;justify-content:space-between;font-size:14px;margin-bottom:8px}
table{width:100%;border-collapse:collapse;margin-top:20px}th,td{border:1px solid #333;padding:8px 10px;font-size:13px;text-align:center}
th{background:#f5f5f5}td{text-align:center}.right{text-align:right}.total-row{font-weight:700;font-size:14px}
.footer{margin-top:40px;display:flex;justify-content:space-between;font-size:14px}
@media print{body{padding:20px}@page{margin:15mm}}</style></head><body>
<h2>送 货 单</h2><h4>${now} | 单号: ${shipment.shipment_no}</h4>
<div class="row"><span><strong>客户:</strong> ${escapeHtml(shipment.customer) || '-'}</span><span><strong>联系人:</strong> ${escapeHtml(shipment.contact_person) || '-'}</span></div>
<div class="row"><span><strong>电话:</strong> ${escapeHtml(shipment.contact_phone) || '-'}</span><span><strong>地址:</strong> ${escapeHtml(shipment.address) || '-'}</span></div>
${shipment.remark ? '<p style="font-size:13px;color:#666"><strong>备注:</strong> ' + escapeHtml(shipment.remark) + '</p>' : ''}
<table><thead><tr><th>#</th><th>型号</th><th>产品名称</th><th>数量</th><th>单位</th><th>备注</th></tr></thead><tbody>
${detailItems.map((item, index) => '<tr><td>' + (index + 1) + '</td><td>' + (escapeHtml(item.product_model) || '-') + '</td><td>' + (escapeHtml(item.product_name) || '-') + '</td><td>' + item.quantity + '</td><td>' + (item.unit || '件') + '</td><td>' + (escapeHtml(item.remark) || '') + '</td></tr>').join('')}
<tr class="total-row"><td colspan="3" class="right">合计</td><td>${totalQuantity}</td><td colspan="2"></td></tr></tbody></table>
<div class="footer"><span>发货人签字: ___________</span><span>收货人签字: ___________</span></div>
<script>window.onload=function(){window.print();setTimeout(function(){window.close()},500)}</` + `script></body></html>`
    const printWindow = window.open('', '_blank', 'width=800,height=600')
    if (!printWindow) {
      showToast('浏览器阻止了送货单打印窗口', 'error')
      return
    }
    printWindow.document.write(html)
    printWindow.document.close()
  }

  return { printDeliveryNote }
}
