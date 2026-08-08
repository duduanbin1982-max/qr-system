import { ref } from 'vue'

import { api } from '@/lib/api.js'
import { showToast } from '@/lib/store.js'


export function useOrderMaterials({ modalId, products }) {
  const orderMaterials = ref([])
  const orderMatForm = ref({ material_id: '', quantity_per_unit: 1, process_id: null })
  const materialOptions = ref([])
  const processOptions = ref([])

  async function loadOrderMaterials(orderId) {
    try {
      const data = await api.domains.products.listOrderMaterials(orderId)
      orderMaterials.value = data.materials || []
    } catch (error) {
      orderMaterials.value = []
    }
  }

  async function loadMaterialOptions() {
    try {
      const data = await api.domains.materials.listMaterials()
      materialOptions.value = data.materials || []
    } catch (error) {
      materialOptions.value = []
      showToast(error.message || '加载物料选项失败', 'error')
    }
  }

  async function loadProcessOptions() {
    try {
      const data = await api.domains.processes.listProcesses()
      processOptions.value = data.items || data.processes || []
      const cuttingProcess = processOptions.value.find(process => process.name === '下料')
      orderMatForm.value.process_id = cuttingProcess?.id || processOptions.value[0]?.id || null
    } catch (error) {
      processOptions.value = []
      showToast(error.message || '加载工序选项失败', 'error')
    }
  }

  async function prepareOrderMaterials(order) {
    await Promise.all([
      loadMaterialOptions(),
      loadProcessOptions(),
      loadOrderMaterials(order.id),
    ])
    const product = products.value.find(item => (
      (order.product_id && item.id === order.product_id)
      || item.product_code === order.product_code
    ))
    orderMatForm.value.quantity_per_unit = (
      parseFloat(product?.weight)
      || parseFloat(order.weight)
      || parseFloat(order.product_weight)
      || 1
    )
  }

  async function addOrderMaterial() {
    if (!orderMatForm.value.material_id) { showToast('请选择物料', 'error'); return }
    try {
      await api.domains.products.addOrderMaterial(modalId.value, {
        material_id: orderMatForm.value.material_id,
        quantity_per_unit: parseFloat(orderMatForm.value.quantity_per_unit) || 1,
        process_id: orderMatForm.value.process_id || null,
      })
      orderMatForm.value = { material_id: '', quantity_per_unit: 1, process_id: null }
      showToast('物料已添加')
      await loadOrderMaterials(modalId.value)
    } catch (error) {
      showToast(error.message || '添加失败', 'error')
    }
  }

  async function removeOrderMaterial(orderMaterialId) {
    try {
      await api.domains.products.deleteOrderMaterial(modalId.value, orderMaterialId)
      await loadOrderMaterials(modalId.value)
    } catch (error) {
      showToast(error.message || '删除失败', 'error')
    }
  }

  return {
    orderMaterials, orderMatForm, materialOptions, processOptions,
    loadOrderMaterials, loadMaterialOptions, loadProcessOptions, prepareOrderMaterials,
    addOrderMaterial, removeOrderMaterial,
  }
}
