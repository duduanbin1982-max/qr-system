// ProductList Component — 产品管理（参照index.html重构：自动编码/分类布局/拼音首字母/附件管理）
import { ref, onMounted, computed, watch } from '../../vendor/vue.esm.js'
import { api } from '../../api.js'
import { showToast } from '../../store.js'
import { auth, can } from '../../auth.js'
import { router } from '../../router.js'

export default {
  template: '#product-list-template',
  setup() {
    const products = ref([])
    const loading = ref(true)
    const searchKeyword = ref('')
    const currentEditProductId = ref(null)
    const productAttachments = ref([])

    // 根据当前路由页面确定分类筛选
    function categoryFromPage(page) {
      if (page === 'structure-products') return '结构件'
      if (page === 'machining-products') return '机加工'
      return '' // all-products or products → 全部
    }
    const filterCategory = ref(categoryFromPage(router.page))
    const activeCat = computed(() => {
      if (!filterCategory.value) return 'all'
      return filterCategory.value
    })

    // Tab 切换分类
    function switchCat(cat) {
      filterCategory.value = cat === 'all' ? '' : cat
      load()
    }

    // 页面标题
    const pageTitle = computed(() => {
      const cat = filterCategory.value
      if (cat === '结构件') return '🔩 结构件产品'
      if (cat === '机加工') return '⚙️ 机加工产品'
      return '📋 全部产品'
    })

    // 模态框
    const showModal = ref(false)
    const modalEdit = ref(false)
    const modalId = ref(null)
    const form = ref({
      product_name: '', product_code: '', model: '', spec: '', style: '',
      upper_opening: '', plate_thickness: '', weight: '',
      category: '结构件', price: '', description: ''
    })

    const categories = ['结构件', '机加工']
    const specOptions = ['三角型', '静音型', '分体直型', '一体直型']

    // 统计
    const structCount = computed(() => products.value.filter(p => p.category === '结构件').length)
    const machCount   = computed(() => products.value.filter(p => p.category === '机加工').length)
    const canEdit    = computed(() => can('products:edit'))
    const canCreate  = computed(() => can('products:create'))
    const canDelete  = computed(() => can('products:delete'))

    // ===== 拼音首字母映射 =====
    const pinyinMap = {
      '三':'S','档':'D','单':'S','双':'S','一':'Y','二':'E','四':'S','五':'W','六':'L','七':'Q','八':'B','九':'J','十':'S',
      '宽':'K','窄':'Z','高':'G','低':'D','短':'D','长':'C','小':'X','大':'D','厚':'H','薄':'B','普':'P','通':'T',
      '型':'X','开':'K','口':'K','圆':'Y','方':'F','角':'J','上':'S','下':'X','左':'Z','右':'Y',
      '中':'Z','重':'Z','新':'X','全':'Q','钢':'G','铁':'T','铜':'T','铝':'L','不':'B','超':'C','特':'T','精':'J',
      '加':'J','工':'G','冲':'C','压':'Y','焊':'H','切':'Q','折':'Z','卷':'J','车':'C','铣':'X','磨':'M','钻':'Z',
      '前':'Q','后':'H','内':'N','顶':'D','底':'D','侧':'C','正':'Z','反':'F',
    }

    function getPinyinInitial(ch) {
      return pinyinMap[ch] || ''
    }

    // ===== 自动生成产品编码 =====
    // 注：与后端 modules/config.py generate_product_code() 逻辑重复，
    // 前端用于实时预览，后端为权威来源。修改时需同步两边。
    function updateProductCode() {
      const m = (form.value.model || '').trim()
      const s = (form.value.spec || '').trim()
      const u = (form.value.upper_opening || '').trim()
      const t = (form.value.plate_thickness || '').trim()
      if (!m) { form.value.product_code = ''; return }

      let initials = ''
      for (let i = 0; i < Math.min(s.length, 2); i++) {
        const ch = s[i]
        if (/[\u4e00-\u9fff]/.test(ch)) initials += getPinyinInitial(ch)
        else if (/[a-zA-Z]/.test(ch)) initials += ch.toUpperCase()
      }
      const opening = u.replace(/\D/g, '')
      const thick = t.replace(/\D/g, '')
      const parts = [m.toUpperCase()]
      if (initials) parts.push(initials)
      if (opening) parts.push(opening)
      if (thick) parts.push(thick)
      form.value.product_code = parts.join('-')
    }

    // ===== 附件工具函数 =====
    function getAttachmentIcon(fileType) {
      if (!fileType) return '📄'
      const t = fileType.toLowerCase()
      if (t.includes('image')) return '🖼️'
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

    function openAttachment(att) {
      // httpOnly cookie handles auth automatically
      window.open('/api/product-attachments/' + att.id + '/view', '_blank')
    }

    function getThumbnailUrl(thumbnailId) {
      if (!thumbnailId) return null
      return '/api/product-attachments/' + thumbnailId + '/thumbnail'
    }

    function openThumbnail(thumbnailId) {
      window.open('/api/product-attachments/' + thumbnailId + '/view', '_blank')
    }

    async function loadProductAttachments(productId) {
      try {
        const d = await api.get('/api/products/' + productId + '/attachments')
        productAttachments.value = d.attachments || []
      } catch(e) { /* silently fail for non-blocking feature */ }
    }

    async function handleAttachmentUpload(event) {
      const files = event.target.files
      if (!files.length) return
      if (!currentEditProductId.value) {
        showToast('请先保存产品后再上传附件', 'error'); event.target.value = ''; return
      }
      const formData = new FormData()
      formData.append('file', files[0])
      try {
        const resp = await fetch('/api/products/' + currentEditProductId.value + '/attachments', {
          method: 'POST',
          body: formData
        })
        if (resp.ok) {
          showToast('上传成功')
          await loadProductAttachments(currentEditProductId.value)
        } else {
          const d = await resp.json()
          showToast(d.error || '上传失败', 'error')
        }
      } catch(e) { showToast('上传失败', 'error') }
      event.target.value = ''
    }

    async function deleteProductAttachment(attachmentId) {
      if (!confirm('确认删除该附件？')) return
      try {
        await api.delete('/api/product-attachments/' + attachmentId)
        showToast('删除成功')
        await loadProductAttachments(currentEditProductId.value)
      } catch(e) { showToast(e.message || '删除失败', 'error') }
    }

    // ===== 数据加载 =====
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
        showToast(e.message || '加载失败', 'error')
      } finally {
        loading.value = false
      }
    }

    // ===== 模态框操作 =====
    function openAdd() {
      form.value = {
        product_name: '', product_code: '', model: '', spec: '', style: '',
        upper_opening: '', plate_thickness: '', weight: '',
        category: filterCategory.value || '结构件', price: '', description: ''
      }
      modalEdit.value = false
      modalId.value = null
      currentEditProductId.value = null
      productAttachments.value = []
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
        plate_thickness: p.plate_thickness || '',
        weight: p.weight || '',
        category: p.category || '结构件',
        price: p.price || '',
        description: p.description || ''
      }
      modalEdit.value = true
      modalId.value = p.id
      currentEditProductId.value = p.id
      productAttachments.value = []
      loadProductAttachments(p.id)
      showModal.value = true
    }

    async function save() {
      if (!(form.value.product_name || '').trim()) {
        showToast('请输入产品名称', 'error')
        return
      }
      try {
        if (!form.value.product_code && form.value.model) updateProductCode()
        const data = { ...form.value }
        if (modalEdit.value) {
          await api.updateProduct(modalId.value, data)
          showToast('更新成功')
        } else {
          await api.createProduct(data)
          showToast('创建成功')
        }
        showModal.value = false
        await load()
      } catch(e) {
        if (e.code === 409) {
          showToast(e.message || '产品编码重复，无法保存', 'error')
        } else {
          showToast(e.message || '保存失败', 'error')
        }
      }
    }

    async function del(p) {
      if (!confirm('确定删除产品 "' + p.product_name + '" 吗？')) return
      try {
        await api.deleteProduct(p.id)
        showToast('删除成功')
        await load()
      } catch(e) {
        showToast(e.message || '删除失败', 'error')
      }
    }

    const importFile = ref(null)

    function triggerImport() {
      importFile.value.click()
    }

    async function handleImport(event) {
      const files = event.target.files
      if (!files.length) return
      const formData = new FormData()
      formData.append('file', files[0])
      try {
        const d = await api.uploadProductImport(formData)
        showToast(d.message || '导入成功')
        await load()
      } catch(e) {
        showToast(e.message || '导入失败', 'error')
      }
      event.target.value = ''
    }

    onMounted(() => load())

    // 监听路由变化，切换分类并重新加载
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
      structCount, machCount, categories, specOptions, can, canEdit, canCreate, canDelete,
      updateProductCode,
      // 附件
      currentEditProductId, productAttachments,
      getAttachmentIcon, formatFileSize, openAttachment, getThumbnailUrl, openThumbnail,
      handleAttachmentUpload, deleteProductAttachment,
      // 导入 + Tab
      importFile, triggerImport, handleImport, activeCat, switchCat,
    }
  }
}
