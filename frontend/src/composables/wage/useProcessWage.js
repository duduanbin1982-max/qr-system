import { computed, onMounted, ref } from 'vue'
import { useWage } from '@/composables/useWage.js'
import { api } from '@/lib/api.js'
import { can } from '@/lib/auth.js'
import { showToast } from '@/lib/store.js'
import { formatUnitPrice as money } from '@/composables/wage/payrollFormat.js'

export function useProcessWage() {
  const wage = useWage()

  const { activeTab, processLoading, processData, processMonth, loadProcess, processColor, processPercent, barHeight, fmtMoney } = wage

  const coverageLoading = ref(false)

  const routeReferences = ref([])

  const priceVersions = ref([])

  const canViewCoverage = computed(() => can('wages:prepare') || can('wages:approve'))

  const coverageRows = computed(() => routeReferences.value.map(reference => {
    const exact = priceVersions.value.filter(price => (
      Number(price.route_version_id) === Number(reference.route_version_id)
      && Number(price.process_version_id) === Number(reference.process_version_id)
    ))
    return {
      ...reference,
      approvedPrice: exact.find(price => price.status === 'approved') || null,
      draftPrices: exact.filter(price => price.status === 'draft'),
    }
  }))

  const coverageGroups = computed(() => {
    const groups = new Map()
    coverageRows.value.forEach(row => {
      if (!groups.has(row.route_version_id)) groups.set(row.route_version_id, { route_version_id: row.route_version_id, rows: [] })
      groups.get(row.route_version_id).rows.push(row)
    })
    return [...groups.values()]
  })

  const coveredCount = computed(() => coverageRows.value.filter(row => row.approvedPrice).length)

  const missingCount = computed(() => coverageRows.value.length - coveredCount.value)

  async function loadCoverage() {
    if (!canViewCoverage.value) return
    coverageLoading.value = true
    try {
      const [references, prices] = await Promise.all([
        api.domains.wages.getRoutePriceVersionReference(),
        api.domains.wages.listRoutePriceVersions(),
      ])
      routeReferences.value = references.items || []
      priceVersions.value = prices.versions || []
    } catch (error) {
      showToast(error.message || '工价覆盖加载失败', 'error')
    } finally {
      coverageLoading.value = false
    }
  }

  onMounted(loadCoverage)

  return {
    wage,
    activeTab,
    processLoading,
    processData,
    processMonth,
    loadProcess,
    processColor,
    processPercent,
    barHeight,
    fmtMoney,
    coverageLoading,
    routeReferences,
    priceVersions,
    canViewCoverage,
    coverageRows,
    coverageGroups,
    coveredCount,
    missingCount,
    money,
    loadCoverage
  }
}
