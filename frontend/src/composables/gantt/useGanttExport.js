import { showToast } from '@/lib/store.js'


let html2canvasLibrary = null

async function getHtml2canvas() {
  if (!html2canvasLibrary) {
    const module = await import('html2canvas')
    html2canvasLibrary = module.default
  }
  return html2canvasLibrary
}

export function useGanttExport() {
  async function exportImage() {
    const element = document.querySelector('.gantt-scroll')
    if (!element) {
      showToast('未找到甘特图', 'error')
      return
    }
    try {
      const html2canvas = await getHtml2canvas()
      const canvas = await html2canvas(element, {
        backgroundColor: '#ffffff',
        scale: 2,
      })
      const link = document.createElement('a')
      link.download = `生产排程_${new Date().toISOString().slice(0, 10)}.png`
      link.href = canvas.toDataURL('image/png')
      link.click()
      showToast('排程图已导出')
    } catch (error) {
      showToast('导出失败', 'error')
    }
  }

  function exportScheduleCsv(rows = [], kind = 'orders') {
    const source = Array.isArray(rows) ? rows : []
    const headers = kind === 'operations'
      ? ['订单号', '工序', '生产节点', '计划开始', '计划结束', '实际开始', '实际结束', '数量', '占用分钟', '风险等级', '阻断原因']
      : ['订单号', '产品编码', '产品名称', '状态', '优先级', '交期', '计划开始', '计划结束', '实际开始', '实际结束', '风险等级', '延期分钟', '锁定']
    const values = source.map(row => kind === 'operations'
      ? [
        row.order_no || row.order_id || '',
        row.process_name || row.process_id || '',
        [row.node_code, row.node_name].filter(Boolean).join(' · ') || row.production_node_id || '',
        row.planned_start_at || row.plan_start || '',
        row.planned_end_at || row.plan_end || '',
        row.actual_start_at || row.actual_start || '',
        row.actual_end_at || row.actual_end || '',
        row.quantity || row.scheduled_quantity || 0,
        row.occupied_minutes || row.planned_minutes || 0,
        row.risk_level || '',
        row.blocked_reason || row.reason || '',
      ]
      : [
        row.order_no || row.id || '', row.product_code || '', row.product_name || '', row.status || '',
        row.priority_level || row.priority || '', row.deadline || row.deadline_at || '', row.plan_start || '', row.plan_end || '',
        row.actual_start_at || row.actual_start || '', row.actual_end_at || row.actual_end || '', row.risk_level || '',
        row.delay_minutes || 0, row.locked || row.is_locked ? '是' : '否',
      ])
    const csv = `\uFEFF${[headers, ...values].map(row => row.map(csvCell).join(',')).join('\r\n')}`
    const blob = new Blob([csv], { type: 'text/csv;charset=utf-8;' })
    const url = URL.createObjectURL(blob)
    const link = document.createElement('a')
    link.href = url
    link.download = `生产排程_${kind === 'operations' ? '工序节点' : '订单'}_${new Date().toISOString().slice(0, 10)}.csv`
    link.click()
    URL.revokeObjectURL(url)
    showToast('排程 CSV 已导出')
  }

  return { exportImage, exportScheduleCsv }
}

function csvCell(value) {
  const text = String(value ?? '')
  return /[",\r\n]/.test(text) ? `"${text.replace(/"/g, '""')}"` : text
}
