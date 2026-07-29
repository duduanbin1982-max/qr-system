import { ref } from 'vue'

import { api } from '@/lib/api.js'
import { showToast } from '@/lib/store.js'


export function useMaterialActivity(selectedMaterial) {
  const logs = ref([])
  const showLogs = ref(false)
  const logsLoading = ref(false)
  const logsError = ref('')
  const logsPage = ref(1)
  const logsPageSize = 20
  const logsTotal = ref(0)

  const consumptions = ref([])
  const showConsume = ref(false)
  const consumptionsLoading = ref(false)
  const consumptionsError = ref('')
  const consumptionsPage = ref(1)
  const consumptionsPageSize = 20
  const consumptionsTotal = ref(0)

  const showDetail = ref(false)
  const detailConsumptions = ref([])
  const detailLoading = ref(false)
  const detailError = ref('')
  const trendChart = ref(null)

  let logsRequestSequence = 0
  let consumptionsRequestSequence = 0
  let detailRequestSequence = 0

  async function loadLogs() {
    if (!selectedMaterial.value) return
    const materialId = selectedMaterial.value.id
    const requestId = ++logsRequestSequence
    logsLoading.value = true
    logsError.value = ''
    try {
      const data = await api.domains.materials.getMaterialLogs(materialId, {
        page: logsPage.value,
        limit: logsPageSize,
      })
      if (requestId !== logsRequestSequence || selectedMaterial.value?.id !== materialId) return
      logs.value = data.logs || []
      logsTotal.value = Number(data.total || 0)
    } catch (error) {
      if (requestId !== logsRequestSequence) return
      logs.value = []
      logsTotal.value = 0
      logsError.value = error.message || '库存流水加载失败'
      showToast(logsError.value, 'error')
    } finally {
      if (requestId === logsRequestSequence) logsLoading.value = false
    }
  }

  function viewLogs(material) {
    selectedMaterial.value = material
    showLogs.value = true
    logs.value = []
    logsPage.value = 1
    logsTotal.value = 0
    return loadLogs()
  }

  function previousLogsPage() {
    if (logsPage.value <= 1 || logsLoading.value) return
    logsPage.value -= 1
    return loadLogs()
  }

  function nextLogsPage() {
    if (logsPage.value * logsPageSize >= logsTotal.value || logsLoading.value) return
    logsPage.value += 1
    return loadLogs()
  }

  async function loadConsumptions() {
    if (!selectedMaterial.value) return
    const materialId = selectedMaterial.value.id
    const requestId = ++consumptionsRequestSequence
    consumptionsLoading.value = true
    consumptionsError.value = ''
    try {
      const data = await api.domains.materials.getMaterialConsumptions(materialId, {
        page: consumptionsPage.value,
        limit: consumptionsPageSize,
      })
      if (requestId !== consumptionsRequestSequence || selectedMaterial.value?.id !== materialId) return
      consumptions.value = data.consumptions || []
      consumptionsTotal.value = Number(data.total || 0)
    } catch (error) {
      if (requestId !== consumptionsRequestSequence) return
      consumptions.value = []
      consumptionsTotal.value = 0
      consumptionsError.value = error.message || '消耗记录加载失败'
      showToast(consumptionsError.value, 'error')
    } finally {
      if (requestId === consumptionsRequestSequence) consumptionsLoading.value = false
    }
  }

  function openConsume(material) {
    selectedMaterial.value = material
    showConsume.value = true
    consumptions.value = []
    consumptionsPage.value = 1
    consumptionsTotal.value = 0
    return loadConsumptions()
  }

  function refreshConsumptions() {
    consumptionsPage.value = 1
    return loadConsumptions()
  }

  function previousConsumptionsPage() {
    if (consumptionsPage.value <= 1 || consumptionsLoading.value) return
    consumptionsPage.value -= 1
    return loadConsumptions()
  }

  function nextConsumptionsPage() {
    if (
      consumptionsPage.value * consumptionsPageSize >= consumptionsTotal.value
      || consumptionsLoading.value
    ) return
    consumptionsPage.value += 1
    return loadConsumptions()
  }

  async function openDetail(material) {
    selectedMaterial.value = material
    showDetail.value = true
    detailConsumptions.value = []
    detailError.value = ''
    detailLoading.value = true
    const materialId = material.id
    const requestId = ++detailRequestSequence
    try {
      const data = await api.domains.materials.getMaterialConsumptions(materialId, {
        page: 1,
        limit: 20,
      })
      if (requestId !== detailRequestSequence || selectedMaterial.value?.id !== materialId) return
      detailConsumptions.value = data.consumptions || []
      setTimeout(renderTrendChart, 0)
    } catch (error) {
      if (requestId !== detailRequestSequence) return
      detailError.value = error.message || '物料详情加载失败'
      showToast(detailError.value, 'error')
    } finally {
      if (requestId === detailRequestSequence) detailLoading.value = false
    }
  }

  function renderTrendChart() {
    if (!trendChart.value || typeof Chart === 'undefined') return
    const context = trendChart.value.getContext('2d')
    if (trendChart.value._chart) trendChart.value._chart.destroy()
    if (!detailConsumptions.value.length) return
    const consumptionByDate = {}
    detailConsumptions.value.forEach((consumption) => {
      const date = (consumption.created_at || '').slice(0, 10)
      if (!consumptionByDate[date]) consumptionByDate[date] = 0
      consumptionByDate[date] += Number(consumption.quantity || 0)
    })
    const dates = Object.keys(consumptionByDate).sort()
    trendChart.value._chart = new Chart(context, {
      type: 'bar',
      data: {
        labels: dates,
        datasets: [{
          label: '消耗量',
          data: dates.map(date => consumptionByDate[date]),
          backgroundColor: 'rgba(239,68,68,0.6)',
          borderColor: 'rgba(239,68,68,1)',
          borderWidth: 1,
          borderRadius: 4,
        }],
      },
      options: {
        responsive: true,
        plugins: { legend: { display: false } },
        scales: {
          y: { beginAtZero: true, title: { display: true, text: '消耗数量' } },
          x: { title: { display: true, text: '日期' } },
        },
      },
    })
  }

  return {
    logs,
    showLogs,
    logsLoading,
    logsError,
    logsPage,
    logsPageSize,
    logsTotal,
    loadLogs,
    viewLogs,
    previousLogsPage,
    nextLogsPage,
    consumptions,
    showConsume,
    consumptionsLoading,
    consumptionsError,
    consumptionsPage,
    consumptionsPageSize,
    consumptionsTotal,
    loadConsumptions,
    openConsume,
    refreshConsumptions,
    previousConsumptionsPage,
    nextConsumptionsPage,
    showDetail,
    detailConsumptions,
    detailLoading,
    detailError,
    trendChart,
    openDetail,
    renderTrendChart,
  }
}
