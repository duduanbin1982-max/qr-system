// ProductList Composable
import { ref, onMounted, computed, watch } from 'vue'
import { api } from '@/lib/api.js'
import { showToast } from '@/lib/store.js'
import { auth, can } from '@/lib/auth.js'
import { router } from '@/lib/router.js'

export function useProduct() {
const products = ref([])
    const loading = ref(true)
    const searchKeyword = ref('')
    const currentEditProductId = ref(null)
    const productAttachments = ref([])

    function categoryFromPage(page) {
      if (page === 'structure-products') return '\u7ed3\u6784\u4ef6'
      if (page === 'machining-products') return '\u673a\u52a0\u5de5'
      return ''
    }
    const filterCategory = ref(categoryFromPage(router.page))
    const activeCat = computed(() => {
      if (!filterCategory.value) return 'all'
      return filterCategory.value
    })

    const switching = ref(false)
    async function switchCat(cat) {
      if (switching.value) return
      switching.value = true
      filterCategory.value = cat === 'all' ? '' : cat
      try { await load() } finally { switching.value = false }
    }

    const pageTitle = computed(() => {
      const cat = filterCategory.value
      if (cat === '\u7ed3\u6784\u4ef6') return '\u2699\ufe0f \u7ed3\u6784\u4ef6\u4ea7\u54c1'
      if (cat === '\u673a\u52a0\u5de5') return '\u2699\ufe0f \u673a\u52a0\u5de5\u4ea7\u54c1'
      return '📋 \u5168\u90e8\u4ea7\u54c1'
    })

    const showModal = ref(false)
    const modalEdit = ref(false)
    const modalId = ref(null)
    const form = ref({
      product_name: '', product_code: '', model: '', spec: '', style: '',
      upper_opening: '', lower_opening: '', plate_thickness: '', weight: '',
      category: '\u7ed3\u6784\u4ef6', price: '', description: ''
    })

    const categories = ['\u7ed3\u6784\u4ef6', '\u673a\u52a0\u5de5']
    const structSpecOptions = ['\u4e09\u89d2\u578b', '\u9759\u97f3\u578b', '\u5206\u4f53\u76f4\u578b', '\u4e00\u4f53\u76f4\u578b']
    const machSpecOptions = ['\u7ecf\u6d4e\u578b', '\u6807\u51c6\u578b', '\u5b9a\u5236\u578b']

    const currentSpecOptions = computed(() => {
      return form.value.category === '\u673a\u52a0\u5de5' ? machSpecOptions : structSpecOptions
    })

    const structCount = computed(() => products.value.filter(p => p.category === '\u7ed3\u6784\u4ef6').length)
    const machCount   = computed(() => products.value.filter(p => p.category === '\u673a\u52a0\u5de5').length)
    const canEdit    = computed(() => can('products:edit'))
    const canCreate  = computed(() => can('products:create'))
    const canDelete  = computed(() => can('products:delete'))

    // 产品编码由后端统一生成（config.generate_product_code）。
    // 前端仅做基础预览拼接；保存时后端会返回最终 product_code。
    function updateProductCode() {
      const m = (form.value.model || '').trim()
      if (!m) { form.value.product_code = ''; return }
      let preview = m.toUpperCase()
      const cat = form.value.category || '结构件'
      if (cat === '结构件') {
        const dims = [(form.value.upper_opening || '').replace(/\D/g, ''),
                      (form.value.lower_opening || '').replace(/\D/g, ''),
                      (form.value.plate_thickness || '').replace(/\D/g, '')].filter(Boolean)
        if (dims.length) preview += '-' + dims.join('-')
      } else {
        const t = (form.value.plate_thickness || '').replace(/\D/g, '')
        if (t) preview += '-' + t
      }
      form.value.product_code = preview
    }

    function getAttachmentIcon(fileType) {
      if (!fileType) return '📄'
      const t = fileType.toLowerCase()
      if (t.includes('image')) return '🖼\ufe0f'
      if (t.includes('pdf')) return '📕'
      if (t.includes('cad') || t.includes('dwg') || t.includes('dxf')) return '📐'
      if (t.includes('word') || t.includes('doc')) return '📝'
      if (t.includes('excel') || t.includes('sheet')) return '📊'
      return '📄'
    }

    function formatFileSize(bytes) {
      if (!bytes) return '0 B'
      if (bytes < 1024) return bytes + ' B'
      if (bytes < 1024 * 1024) return (bytes / 1024).toFixed(1) + ' KB'
      return (bytes / (1024 * 1024)).toFixed(1) + ' MB'
    }

    function getThumbnailUrl(attId) {
      return '/api/product-attachments/' + attId + '/thumbnail?token=' + (auth.token || '')
    }

    function openThumbnail(attId) {
      window.open('/api/product-attachments/' + attId + '/download?token=' + (auth.token || ''), '_blank')
    }

    function openAttachment(att) {
      window.open('/api/product-attachments/' + att.id + '/download?token=' + (auth.token || ''), '_blank')
    }

    async function loadProductAttachments(productId) {
      try {
        const d = await api.listProductAttachments(productId)
        productAttachments.value = d.attachments || []
      } catch(e) { /* silent */ }
    }

    function triggerAttachmentInput() {
      // Vue template ref    https://stackoverflow.com/a/123
      const input = document.getElementById('product-attachment-input')
      if (input) input.click()
    }

    async function handleAttachmentUpload(event) {
      const files = event.target.files
      if (!files.length) return
      if (!currentEditProductId.value) { showToast('\u8bf7\u5148\u4fdd\u5b58\u4ea7\u54c1', 'warning'); return }
      for (const file of files) {
        if (file.size > 10 * 1024 * 1024) { showToast(file.name + ' \u8d85\u8fc710MB\u9650\u5236', 'error'); continue }
        const fd = new FormData()
        fd.append('file', file)
        try {
          await api.uploadProductAttachment(currentEditProductId.value, fd)
        } catch(e) { showToast(e.message || '\u4e0a\u4f20\u5931\u8d25', 'error') }
      }
      event.target.value = ''
      await loadProductAttachments(currentEditProductId.value)
    }

    async function deleteProductAttachment(attId) {
      if (!confirm('\u786e\u5b9a\u5220\u9664\u6b64\u9644\u4ef6\uff1f')) return
      try {
        await api.deleteProductAttachment(attId)
        showToast('\u5220\u9664\u6210\u529f')
        if (currentEditProductId.value) await loadProductAttachments(currentEditProductId.value)
      } catch(e) { showToast(e.message || '\u5220\u9664\u5931\u8d25', 'error') }
    }

    // ===== \u6570\u636e\u52a0\u8f7d =====
    async function load() {
      loading.value = true
      try {
        const params = {}
        const kw = searchKeyword.value.trim()
        const cat = filterCategory.value
        if (kw) params.keyword = kw
        if (cat) params.category = cat
        const d = await api.listProducts(Object.keys(params).length ? params : null)
        products.value = d.products || []
      } catch(e) {
        showToast(e.message || '\u52a0\u8f7d\u5931\u8d25', 'error')
      } finally {
        loading.value = false
      }
    }

    function openAdd() {
      form.value = {
        product_name: '', product_code: '', model: '', spec: '', style: '',
        upper_opening: '', lower_opening: '', plate_thickness: '', weight: '',
        category: filterCategory.value || '\u7ed3\u6784\u4ef6', price: '', description: ''
      }
      modalEdit.value = false
      modalId.value = null
      currentEditProductId.value = null
      productAttachments.value = []
      bomForm.value = { material_id: '', quantity: parseFloat(form.value.weight) || 1, process_id: 10730 }
      showModal.value = true
    }

    function openEdit(p) {
      form.value = {
        product_name: p.product_name || '',
        product_code: p.product_code || '',
        model: p.model || '',
        spec: p.spec || '',
        style: p.style || '',
        upper_opening: p.upper_opening || '',
        lower_opening: p.lower_opening || '',
        plate_thickness: p.plate_thickness || '',
        weight: p.weight || '',
        category: p.category || '\u7ed3\u6784\u4ef6',
        price: p.price || '',
        description: p.description || ''
      }
      modalEdit.value = true
      modalId.value = p.id
      currentEditProductId.value = p.id
      productAttachments.value = []
      loadMaterialOptions()
      loadProcessOptions()
      loadProductAttachments(p.id)
      loadProductBom(p.id)
      bomForm.value.quantity = parseFloat(form.value.weight) || 1
      showModal.value = true
    }

    async function save() {
      if (!(form.value.product_name || '').trim()) {
        showToast('\u8bf7\u8f93\u5165\u4ea7\u54c1\u540d\u79f0', 'error')
        return
      }
      try {
        if (modalEdit.value && !form.value.product_code && form.value.model) updateProductCode()
        const data = { ...form.value }
        // Let backend generate product_code for new products
        if (!modalEdit.value) delete data.product_code
        if (modalEdit.value) {
          await api.updateProduct(modalId.value, data)
          showToast('\u66f4\u65b0\u6210\u529f')
        } else {
          await api.createProduct(data)
          showToast('\u521b\u5efa\u6210\u529f')
        }
        showModal.value = false
        await load()
      } catch(e) {
        if (e.code === 409) {
          showToast(e.message || '\u4ea7\u54c1\u7f16\u7801\u91cd\u590d\uff0c\u65e0\u6cd5\u4fdd\u5b58', 'error')
        } else {
          showToast(e.message || '\u4fdd\u5b58\u5931\u8d25', 'error')
        }
      }
    }

    async function del(p) {
      if (!confirm('\u786e\u5b9a\u5220\u9664\u4ea7\u54c1 "' + p.product_name + '" \u5417\uff1f')) return
      try {
        await api.deleteProduct(p.id)
        showToast('\u5220\u9664\u6210\u529f')
        await load()
      } catch(e) {
        showToast(e.message || '\u5220\u9664\u5931\u8d25', 'error')
      }
    }

    const importFile = ref(null)
    const importLoading = ref(false)
    const productBom = ref([])
    const bomForm = ref({ material_id: '', quantity: 1, process_id: 10730 })
    const materialOptions = ref([])
    const processOptions = ref([])
    const showTrash = ref(false)
    const trashedProducts = ref([])

    function triggerImport() {
      importFile.value.click()
    }

    async function handleImport(event) {
      const files = event.target.files
      if (!files.length) return
      const file = files[0]
      if (file.size > 10 * 1024 * 1024) { showToast('\u6587\u4ef6\u5927\u5c0f\u8d85\u8fc710MB\u9650\u5236', 'error'); event.target.value = ''; return }
      const formData = new FormData()
      formData.append('file', file)
      importLoading.value = true
      showToast('\u6b63\u5728\u5bfc\u5165 ' + file.name + ' ...')
      try {
        const d = await api.uploadProductImport(formData)
        let parts = [d.message || '\u5bfc\u5165\u5b8c\u6210']
        if (d.error_summary) parts.push(d.error_summary)
        if (d.columns_found && d.columns_found.length) parts.push('\u8bc6\u522b\u5217: ' + d.columns_found.join(','))
        showToast(parts.join(' | '))
        await load()
      } catch(e) {
        showToast(e.message || '\u5bfc\u5165\u5931\u8d25', 'error')
      } finally {
        importLoading.value = false
      }
      event.target.value = ''
    }

    async function loadTrash() {
      loading.value = true
      try {
        const d = await api.listProducts({ deleted: 1 })
        trashedProducts.value = d.products || []
      } catch(e) {
        showToast(e.message || '加载失败', 'error')
      } finally {
        loading.value = false
      }
    }

    function toggleTrash() {
      showTrash.value = !showTrash.value
      if (showTrash.value) loadTrash()
    }

    async function purge(pid, name) {
      if (!confirm('Permanently delete "' + name + '"? This cannot be undone!')) return
      try {
        await api.purgeProduct(pid)
        showToast('Permanently deleted')
        await loadTrash()
        await load()
      } catch(e) {
        showToast(e.message || 'Purge failed', 'error')
      }
    }

    async function restore(pid) {
      try {
        await api.restoreProduct(pid)
        showToast('恢复成功')
        await loadTrash()
        await load()
      } catch(e) {
        showToast(e.message || '恢复失败', 'error')
      }
    }

    async function loadMaterialOptions() {
      try {
        const d = await api.listMaterials()
        materialOptions.value = d.materials || []
      } catch(e) {
        materialOptions.value = []
        showToast(e.message || '加载物料选项失败', 'error')
      }
    }
    async function loadProcessOptions() {
      try {
        const d = await api.listProcesses()
        processOptions.value = d.items || d.processes || []
        const xl = processOptions.value.find(p => p.name === '下料')
        if (xl) bomForm.value.process_id = xl.id
      } catch(e) {
        processOptions.value = []
        showToast(e.message || '加载工序选项失败', 'error')
      }
    }
    async function loadProductBom(pid) {
      try { const d = await api.listProductBom(pid); productBom.value = d.bom || [] } catch(e) { productBom.value = [] }
    }
    async function addBomItem() {
      if (!bomForm.value.material_id) { showToast('请选择物料', 'error'); return }
      try {
        await api.addProductBom(currentEditProductId.value, {
          material_id: bomForm.value.material_id,
          quantity_per_unit: parseFloat(bomForm.value.quantity) || 1,
          process_id: bomForm.value.process_id || null
        })
        bomForm.value = { material_id: '', quantity: parseFloat(form.value.weight) || 1, process_id: 10730 }
        showToast('BOM added')
        await loadProductBom(currentEditProductId.value)
      } catch(e) { showToast(e.message || 'Failed', 'error') }
    }
    async function removeBomItem(bomId) {
      try {
        await api.deleteProductBom(currentEditProductId.value, bomId)
        await loadProductBom(currentEditProductId.value)
      } catch(e) { showToast(e.message || 'Failed', 'error') }
    }
    onMounted(() => load())

    watch(() => router.page, (page) => {
      const cat = categoryFromPage(page)
      if (filterCategory.value !== cat) {
        filterCategory.value = cat
        load()
      }
    })

    return {
      products, loading, searchKeyword, filterCategory, pageTitle, load,
      showModal, modalEdit, form, openAdd, openEdit, save, del,
      structCount, machCount, categories, specOptions: currentSpecOptions, can, canEdit, canCreate, canDelete,
      updateProductCode,
      currentEditProductId, productAttachments,
      getAttachmentIcon, formatFileSize, openAttachment, getThumbnailUrl, openThumbnail,
      triggerAttachmentInput, handleAttachmentUpload, deleteProductAttachment,
      importFile, triggerImport, handleImport, importLoading, activeCat, switchCat, auth,
      showTrash, trashedProducts, loadTrash, toggleTrash, restore, purge,
      productBom, bomForm, materialOptions, processOptions, loadProductBom, addBomItem, removeBomItem,
    }
}
