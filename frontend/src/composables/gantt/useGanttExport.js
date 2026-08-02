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

  return { exportImage }
}
