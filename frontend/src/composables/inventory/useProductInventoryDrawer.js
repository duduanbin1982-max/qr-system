import { computed, ref, watch } from 'vue'
import { api } from '@/lib/api.js'

export function useProductInventoryDrawer(props) {
  const compatibilityKey = ref('')
  const allocationQuantity = ref(1)
  const allocationMode = ref('fifo')
  const allocationReason = ref('')
  const selectedInventoryIds = ref([])
  const allocationPreview = ref(null)
  const allocationError = ref('')
  const allocationLoading = ref(false)
  const history = ref([])
  const historyLoading = ref(false)
  const compatibleItems = computed(() => (props.details?.inventory_items || []).filter(item => !compatibilityKey.value || item.compatibility_key === compatibilityKey.value))

  watch(() => props.product?.product_id, () => {
    compatibilityKey.value = ''
    allocationPreview.value = null
    selectedInventoryIds.value = []
    allocationError.value = ''
    loadHistory()
  })

  async function loadHistory() {
    if (!props.product?.product_id || !props.capabilities?.cross_order_outbound_enabled) return
    historyLoading.value = true
    try {
      history.value = (await api.domains.inventory.listAllocationRuns({ product_id: props.product.product_id, limit: 20 })).items || []
    } catch (_) {
      history.value = []
    } finally {
      historyLoading.value = false
    }
  }

  async function previewAllocation() {
    allocationLoading.value = true
    allocationError.value = ''
    try {
      allocationPreview.value = await api.domains.inventory.allocationPreview(props.product.product_id, {
        quantity: allocationQuantity.value,
        mode: allocationMode.value,
        compatibility_key: compatibilityKey.value,
        selected_inventory_ids: selectedInventoryIds.value,
        reason: allocationReason.value,
      })
    } catch (error) {
      allocationError.value = error.message || '无法生成分配预览'
    } finally {
      allocationLoading.value = false
    }
  }

  async function confirmOutbound() {
    if (!allocationPreview.value) return
    allocationLoading.value = true
    allocationError.value = ''
    try {
      await api.domains.inventory.productGroupOutbound(props.product.product_id, {
        quantity: allocationQuantity.value,
        mode: allocationMode.value,
        compatibility_key: allocationPreview.value.compatibility_key,
        selected_inventory_ids: selectedInventoryIds.value,
        preview_digest: allocationPreview.value.preview_digest,
        idempotency_key: `inventory-ui-${Date.now()}`,
        reason: allocationReason.value,
      })
      allocationPreview.value = null
      await loadHistory()
      window.alert('出库成功')
    } catch (error) {
      allocationError.value = error.message || '正式出库失败'
    } finally {
      allocationLoading.value = false
    }
  }

  async function reverseRun(run) {
    if (!window.confirm(`确认撤销分配运行 #${run.id}？`)) return
    allocationLoading.value = true
    allocationError.value = ''
    try {
      await api.domains.inventory.reverseAllocation(run.id, {
        idempotency_key: `inventory-ui-reverse-${run.id}-${Date.now()}`,
        reason: '库存产品视图撤销',
      })
      await loadHistory()
      window.alert('撤销成功')
    } catch (error) {
      allocationError.value = error.message || '撤销失败'
    } finally {
      allocationLoading.value = false
    }
  }

  function exportDetails() {
    if (!props.product?.product_id || !props.canExport) return
    window.open(api.domains.inventory.productGroupDetailsExportUrl(props.product.product_id, { compatibility_key: compatibilityKey.value }), '_blank')
  }

  return {
    compatibilityKey, allocationQuantity, allocationMode, allocationReason,
    selectedInventoryIds, allocationPreview, allocationError, allocationLoading,
    history, historyLoading, compatibleItems,
    previewAllocation, confirmOutbound, reverseRun, exportDetails,
  }
}
