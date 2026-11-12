export const PIECEWORK_EXPORT_PAGE_SIZE = 1000

export function escapeHtml(value) {
  return String(value == null ? '' : value).replace(/[&<>"']/g, character => ({
    '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;',
  })[character])
}

export function buildPayslipHtml(wage, month, fmtMoney) {
  const w = wage || {}
  const money = value => escapeHtml(fmtMoney(value))
  return `<!DOCTYPE html><html><head><meta charset="utf-8"><title>工资条</title><style>body{font-family:Microsoft YaHei,sans-serif;max-width:400px;margin:0 auto;padding:20px}h2{text-align:center;margin:0 0 4px}h4{text-align:center;color:#666;margin:0 0 16px;font-weight:400}table{width:100%;border-collapse:collapse;margin:12px 0}td,th{border:1px solid #ddd;padding:6px 10px;font-size:14px}th{background:#f5f5f5;text-align:right;width:40%}td{text-align:left}.total{font-size:18px;font-weight:700;color:#e67e22}.footer{margin-top:20px;display:flex;justify-content:space-between;font-size:13px}@media print{body{padding:0}}</style></head><body><h2>工资条</h2><h4>${escapeHtml(month)} · 扫码报工生产管理系统</h4><table><tr><th>姓名</th><td>${escapeHtml(w.employee_name || '-')}</td></tr><tr><th>工号</th><td>${escapeHtml(w.employee_no || '-')}</td></tr><tr><th>岗位</th><td>${escapeHtml(w.position_name || '-')}</td></tr><tr><th>总件数</th><td>${escapeHtml(w.total_quantity || 0)}</td></tr><tr><th>计件工资</th><td class="total">¥${money(w.total_wage)}</td></tr><tr><th>返工工资</th><td>¥${money(w.rework_wage || 0)}</td></tr><tr><th>合计</th><td class="total">¥${money((w.total_wage || 0) + (w.rework_wage || 0))}</td></tr></table><div class="footer"><span>员工签收：___________</span><span>日期：___________</span></div><script>window.onload=function(){window.print();setTimeout(function(){window.close()},500)}<\/script></body></html>`
}

export async function collectAllPages(fetchPage, itemKey, pageSize) {
  const first = await fetchPage(1, pageSize)
  const firstItems = Array.isArray(first?.[itemKey]) ? first[itemKey] : []
  const reportedTotal = Number(first?.total)
  const total = Math.max(Number.isFinite(reportedTotal) ? reportedTotal : 0, firstItems.length)
  const pages = Math.max(1, Math.ceil(total / pageSize))
  const items = [...firstItems]
  for (let pageNumber = 2; pageNumber <= pages; pageNumber += 1) {
    const response = await fetchPage(pageNumber, pageSize)
    const responseTotal = Number(response?.total)
    if (Number.isFinite(responseTotal) && responseTotal !== total) {
      throw new Error('导出期间数据发生变化，请刷新后重试')
    }
    items.push(...(Array.isArray(response?.[itemKey]) ? response[itemKey] : []))
  }
  if (items.length !== total) throw new Error('导出数据不完整，请刷新后重试')
  return { ...(first || {}), [itemKey]: items, total, page: 1, limit: pageSize }
}

export function buildPieceworkCsvRows(wages, fmtDate, fmtMoney) {
  const rows = [["姓名","岗位","工号","日期","订单号","产品","产品编码","工序","数量","单价","工资"]]
  let totalQuantity = 0
  let totalWage = 0
  for (const w of (wages || [])) {
    for (const d of (w.details || [])) {
      rows.push([w.employee_name, w.position_name || "", w.employee_no, fmtDate(d.date), d.order_no, d.product_name, d.product_code || "", d.process_name, d.quantity, fmtMoney(d.unit_price), fmtMoney(d.wage)])
    }
    rows.push([w.employee_name, w.position_name || "", w.employee_no, "", "", "", "", "小计", w.total_quantity, "", fmtMoney(w.total_wage)])
    totalQuantity += Number(w.total_quantity || 0)
    totalWage += Number(w.total_wage || 0)
  }
  rows.push(["", "", "", "", "", "", "", "合计", totalQuantity, "", fmtMoney(totalWage)])
  return rows
}

export function buildMonthlyCsvRows(summary, totals, fmtMoney) {
  const rows = [["排名","姓名","工号","总件数","总工资","占比"]]
  const grandTotalWage = Number(totals?.grand_total_wage || 0)
  for (let index = 0; index < (summary || []).length; index += 1) {
    const item = summary[index]
    const percent = grandTotalWage ? ((Number(item.total_wage || 0) / grandTotalWage) * 100).toFixed(1) : '0.0'
    rows.push([index + 1, item.employee_name, item.employee_no || '-', item.total_quantity, fmtMoney(item.total_wage), `${percent}%`])
  }
  rows.push(['', '', '合计', totals?.grand_total_quantity || 0, fmtMoney(grandTotalWage), grandTotalWage ? '100.0%' : '0.0%'])
  return rows
}
