<!-- PriceList.vue -->
<template>
<div style="padding:var(--space-6)">
    <!-- 统计栏 -->
    <div class="summary-bar">
      <div class="summary-item"><span class="s-icon">🔀</span><div><div class="s-val">{{ totalRouteCount }}</div><div class="s-label">总路线</div></div></div>
      <div class="summary-item"><span class="s-icon">🔩</span><div><div class="s-val text-primary">{{ structRouteCount }}</div><div class="s-label">结构件</div></div></div>
      <div class="summary-item"><span class="s-icon">⚙️</span><div><div class="s-val text-success">{{ machRouteCount }}</div><div class="s-label">机加工</div></div></div>
      <div class="summary-item"><span class="s-icon">💰</span><div><div class="s-val text-warning">{{ pricedRouteCount || 0 }}</div><div class="s-label">已定价</div></div></div>
    </div>

    <!-- 分类选项卡 -->
    <div class="cat-tabs">
      <span class="cat-tab cat-tab-all" :class="{active: pricingCategory==='all'}" @click="switchCat('all')">📋 全部工价路线</span>
      <span class="cat-tab cat-tab-struct" :class="{active: pricingCategory==='结构件'}" @click="switchCat('结构件')">🔩 结构件工价</span>
      <span class="cat-tab cat-tab-mach" :class="{active: pricingCategory==='机加工'}" @click="switchCat('机加工')">⚙️ 机加工工价</span>
    </div>

    <div class="card">
      <div class="card-header">
        <h3>💰 工价路线</h3>
        <div style="display:flex;gap:var(--space-2)">
          <button class="btn btn-default btn-sm" @click="switchCat(pricingCategory); loadAllRoutes()">🔄 刷新</button>
        </div>
      </div>
      <div class="card-body">
        <div v-if="loading" style="text-align:center;padding:40px;color:var(--text-placeholder)">⏳ 加载中...</div>

        <div v-else>
          <div v-if="filteredRoutes.length">
        <div v-for="(r, idx) in filteredRoutes" :key="r.id" style="border:1px solid var(--border-light);border-radius:var(--radius-lg);margin-bottom:var(--space-3);background:white;overflow:hidden"
          :style="{borderLeft: expandedRoute===r.id ? '4px solid var(--primary)' : '4px solid transparent'}">

          <!-- 卡片头部 -->
          <div style="display:flex;align-items:center;justify-content:space-between;padding:var(--space-4) 20px;cursor:pointer"
            @click="toggleRoute(r.id)">
            <div style="display:flex;align-items:center;gap:var(--space-3)">
              <span style="display:inline-flex;width:28px;height:28px;border-radius:50%;background:var(--primary-light);color:var(--primary);align-items:center;justify-content:center;font-weight:bold;font-size:13px;flex-shrink:0">{{ idx + 1 }}</span>
              <span style="font-size:var(--text-xl)">{{ expandedRoute === r.id ? '▼' : '▶' }}</span>
              <div>
                <div style="font-weight:600;font-size:15px">{{ r.name }}</div>
                <div style="font-size:var(--text-xs);color:var(--text-placeholder);margin-top:2px">
                  点击展开编辑工价
                </div>
              </div>
            </div>
            <span style="font-size:var(--text-sm);color:var(--primary);font-weight:500">
              {{ expandedRoute === r.id ? '收起' : '编辑工价 →' }}
            </span>
          </div>

          <!-- 展开：工序编辑面板 -->
          <div v-if="expandedRoute === r.id && routeSteps.length" style="border-top:1px solid var(--bg-hover);padding:var(--space-5)">
            <div style="font-size:var(--text-sm);color:var(--text-placeholder);margin-bottom:var(--space-3)">
              💡 所有使用此路线的产品共享以下工价
            </div>

            <table class="data-table" style="font-size:var(--text-sm);width:100%">
              <thead>
                <tr>
                  <th class="col-num">#</th>
                  <th class="col-min-140">工序名称</th>
                  <th class="col-cat">分类</th>
                  <th class="col-min-110 text-center">当前工价</th>
                  <th class="col-min-110 text-center">生效日期</th>
                  <th class="col-min-130 text-center">新工价 (元)</th>
                </tr>
              </thead>
              <tbody>
                <tr v-for="(s, idx) in routeSteps" :key="s.process_id">
                  <td class="text-center"><span style="display:inline-flex;width:24px;height:24px;border-radius:50%;background:var(--primary-light);color:var(--primary);align-items:center;justify-content:center;font-weight:bold;font-size:var(--text-xs)">{{ idx+1 }}</span></td>
                  <td><strong>{{ s.process_name }}</strong></td>
                  <td class="text-center"><span class="badge" :style="{background:s.category==='机加工'?'var(--warning-lighter)':'var(--info-light)',color:s.category==='机加工'?'var(--warning)':'var(--info)',fontSize:'var(--text-xs-alt)'}">{{ s.category || '—' }}</span></td>
                  <td class="text-center">
                    <span v-if="s.unit_price != null" style="display:inline-block;padding:var(--space-1) 10px;background:var(--primary-light);border-radius:var(--radius-sm);color:var(--primary);font-weight:600;font-size:var(--text-sm)">¥{{ Number(s.unit_price).toFixed(2) }}</span>
                    <span v-else style="color:var(--border)">—</span>
                  </td>
                  <td class="text-center" style="font-size:var(--text-xs)">
                    <span v-if="s.effective_date" :style="{color: isRecentDate(s.effective_date) ? 'var(--warning)' : 'var(--text-placeholder)', fontWeight: isRecentDate(s.effective_date) ? 600 : 400}">
                      {{ s.effective_date }}
                      <span v-if="isRecentDate(s.effective_date)" style="display:inline-block;width:8px;height:8px;border-radius:50%;background:var(--warning);margin-left:4px;animation:pulse 2s infinite" :title="'最近更新'"></span>
                    </span>
                    <span v-else style="color:var(--border)">—</span>
                  </td>
                  <td class="text-center">
                    <input type="number" class="form-input" style="text-align:center;width:120px"
                      v-model.number="editPrices[s.process_id]" placeholder="输入单价" step="0.01" min="0">
                  </td>
                </tr>
              </tbody>
            </table>

            <!-- 操作栏 -->
            <div style="display:flex;gap:var(--space-3);align-items:center;margin-top:16px;flex-wrap:wrap">
              <div style="display:flex;gap:var(--space-2);align-items:center">
                <label style="font-size:var(--text-sm);color:var(--text-placeholder);white-space:nowrap">生效日期</label>
                <input type="date" class="form-input" style="width:150px" v-model="editMeta[expandedRoute].effectiveDate">
              </div>
              <div style="display:flex;gap:var(--space-2);align-items:center;flex:1">
                <label style="font-size:var(--text-sm);color:var(--text-placeholder);white-space:nowrap">备注</label>
                <input class="form-input" style="flex:1;max-width:300px" v-model="editMeta[expandedRoute].remark" placeholder="调价备注">
              </div>
              <button class="btn btn-primary" @click="saveRoute" :disabled="saving" style="margin-left:auto;white-space:nowrap">
                {{ saving ? '⏳ 保存中...' : '💾 保存工价' }}
              </button>
            </div>
            <!-- 调价历史 -->
            <div v-if="priceHistory.length" style="margin-top:16px;padding-top:12px;border-top:1px solid var(--border-light)">
              <div style="display:flex;align-items:center;justify-content:space-between;margin-bottom:8px">
                <span style="font-size:var(--text-sm);font-weight:600;color:var(--text-secondary)">📋 调价历史</span>
                <button @click="priceHistory=[]" style="border:none;background:none;color:var(--text-muted);cursor:pointer;font-size:var(--text-lg)">&times;</button>
              </div>
              <div style="max-height:200px;overflow-y:auto">
                <table style="width:100%;table-layout:fixed;border-collapse:collapse;font-size:var(--text-xs)">
                  <colgroup>
                    <col style="width:34%"><col style="width:20%"><col style="width:16%"><col style="width:16%"><col style="width:14%">
                  </colgroup>
                  <thead><tr style="border-bottom:1px solid var(--border-light);color:var(--text-placeholder)">
                    <th style="padding:4px 8px;text-align:left">日期</th>
                    <th style="padding:4px 8px;text-align:left">工序</th>
                    <th style="padding:4px 8px;text-align:right">旧价</th>
                    <th style="padding:4px 8px;text-align:right">新价</th>
                    <th style="padding:4px 8px;text-align:center">生效</th>
                  </tr></thead>
                  <tbody>
                    <tr v-for="h in priceHistory" :key="h.id" style="border-bottom:1px solid var(--bg-hover)">
                      <td style="padding:4px 8px;text-align:left;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;color:var(--text-placeholder)">{{ h.created_at ? h.created_at.slice(0,16) : '-' }}</td>
                      <td style="padding:4px 8px;text-align:left;white-space:nowrap;overflow:hidden;text-overflow:ellipsis">{{ h.process_name || '-' }}</td>
                      <td style="padding:4px 8px;text-align:right;white-space:nowrap;color:var(--text-muted)">¥{{ h.old_price != null ? Number(h.old_price).toFixed(2) : '-' }}</td>
                      <td style="padding:4px 8px;text-align:right;white-space:nowrap;font-weight:600;color:var(--warning)">¥{{ Number(h.new_price).toFixed(2) }}</td>
                      <td style="padding:4px 8px;text-align:center;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;color:var(--text-placeholder)">{{ h.effective_date || '-' }}</td>
                    </tr>
                  </tbody>
                </table>
              </div>
            </div>

          </div>
        </div>
      </div>

      <!-- 空状态 -->
      <div v-else style="text-align:center;padding:60px;color:var(--text-placeholder)">
        <div style="font-size:48px;margin-bottom:var(--space-3)">💰</div>
        <div>暂无工价配置</div>
        <div style="font-size:var(--text-sm);margin-top:4px">请先创建工序路线，再配置路线工价</div>
      </div>
    </div>
      </div>
    </div>

  </div>
</template>

<script>
import { ref, reactive, onMounted, computed, watch } from 'vue'
import { api } from '@/lib/api.js'
import { showToast } from '@/lib/store.js'
import { can } from '@/lib/auth.js'
import { router } from '@/lib/router.js'

export default {
  setup() {
    const loading = ref(true)
    const routeSteps = ref([])
    const allRoutes = ref([])
    const totalRouteCount = computed(() => filteredRoutes.value.length)
    const structRouteCount = computed(() => {
      const pool = pricingCategory.value === 'all' ? allRoutes.value : filteredRoutes.value
      return pool.filter(r => r.category === '结构件').length
    })
    const machRouteCount = computed(() => {
      const pool = pricingCategory.value === 'all' ? allRoutes.value : filteredRoutes.value
      return pool.filter(r => r.category === '机加工').length
    })
    const pricedRouteCount = computed(() => {
      return filteredRoutes.value.filter(r => r.priced_route_count > 0).length
    })
    const editPrices = reactive({}) // {process_id: unit_price}
    const saving = ref(false)
    const priceHistory = ref([])
    const switching = ref(false)

    // 复制


    // RBAC 权限
    const canEdit = computed(() => can('prices:edit'))
    const canCreate = computed(() => can('prices:create'))
    const canDelete = computed(() => can('prices:delete'))

    const pricingCategory = ref('all')

    // 按分类筛选产品
    const filteredRoutes = computed(() => {
      if (pricingCategory.value === 'all') return allRoutes.value
      return allRoutes.value.filter(r => r.category === pricingCategory.value)
    })

    // ====== 路线卡片模式 ======
    const expandedRoute = ref(null)
    const editMeta = reactive({})  // { route_id: { effectiveDate, remark } }

    async function toggleRoute(routeId) {
      if (expandedRoute.value === routeId) {
        expandedRoute.value = null
        return
      }
      expandedRoute.value = routeId
      // Initialize editMeta for this route (safely via Vue.set-like assignment)
      if (!editMeta[routeId]) {
        editMeta[routeId] = { effectiveDate: '', remark: '' }
      }
      // Ensure reactive access doesn't fail on first render
      if (!editMeta[expandedRoute.value]) {
        editMeta[expandedRoute.value] = { effectiveDate: '', remark: '' }
      }
      // Load route pricing steps
      try {
        const d = await api.getRoutePricingDetail(routeId)
        routeSteps.value = d.steps || []
        routeStepsByRoute[routeId] = d.steps || []
        loadPriceHistory(routeId)
        // Init editPrices
        const prices = {}
        routeSteps.value.forEach(s => {
          if (s.unit_price != null) prices[s.process_id] = s.unit_price
        })
        Object.keys(editPrices).forEach(k => delete editPrices[k])
        Object.assign(editPrices, prices)
      } catch (e) {
        showToast('加载路线工价失败', 'error')
        expandedRoute.value = null
      }
    }

    function isRecentDate(dateStr) {
      if (!dateStr) return false
      const d = new Date(dateStr)
      const now = new Date()
      const diff = (now - d) / (1000 * 60 * 60 * 24)
      return diff <= 7
    }

    async function loadPriceHistory(routeId) {
      try {
        const d = await api.getRoutePricingHistory(routeId)
        priceHistory.value = d.history || []
      } catch (e) { priceHistory.value = [] }
    }

    const routeStepsByRoute = reactive({})  // { routeId: [...] }

    async function saveRoute() {
      const rid = expandedRoute.value
      if (!rid) return
      saving.value = true
      try {
        const steps = routeStepsByRoute[rid] || []
        const prices = {}
        steps.forEach(s => {
          if (editPrices[s.process_id] != null && editPrices[s.process_id] !== '') {
            prices[s.process_id] = parseFloat(editPrices[s.process_id])
          }
        })
        if (!Object.keys(prices).length) { showToast('请至少填写一个工序的单价', 'error'); saving.value = false; return }
        const meta = editMeta[rid] || {}
        const data = { prices, effective_date: meta.effectiveDate, remark: meta.remark }
        const res = await api.saveRouteLevelPricing(rid, data)
        showToast(res.message || '保存成功')
        priceHistory.value = []
        expandedRoute.value = null
      loading.value = false
      } catch (e) { showToast(e.message || '保存失败', 'error') }
      finally { saving.value = false }
    }

    const pageTitle = computed(() => {
      const cat = pricingCategory.value
      const cnt = filteredRoutes.value.length
      if (cat === '结构件') return '🔩 结构件工价 (' + cnt + ')'
      if (cat === '机加工') return '⚙️ 机加工工价 (' + cnt + ')'
      return '📋 全部工价路线 (' + cnt + ')'
    })

    // 分类筛选
    function categoryFromPage(page) {
      if (page === 'structure-prices') return '结构件'
      if (page === 'machining-prices') return '机加工'
      return 'all'
    }


    // ====== 数据加载 ======
    async function loadStats() { /* counts now computed reactively */ }

    async function loadAllRoutes(category) {
      try {
        const params = {}
        if (category && category !== 'all') params.category = category
        const d = await api.listProcessRoutes(Object.keys(params).length ? params : null)
        allRoutes.value = d.routes || []
      } catch (e) { showToast('加载路线失败: ' + (e.message || '网络错误'), 'error') }
    }



    // ====== 透视表操作 ======


    async function switchCat(cat) {
      if (switching.value) return
      switching.value = true
      if (pricingCategory.value === cat && allRoutes.value.length > 0) return
      pricingCategory.value = cat
      loading.value = true
      await loadAllRoutes(cat === 'all' ? null : cat)
      loading.value = false
      switching.value = false
    }

    onMounted(async () => {
      try {
        const cat = categoryFromPage(router.page)
        pricingCategory.value = cat
        await loadStats()
        await loadAllRoutes(cat === 'all' ? null : cat)
        loading.value = false
      } catch (e) {
        showToast('加载失败: ' + (e.message || '网络错误'), 'error')
      }
    })

    watch(() => router.page, (page) => {
      const cat = categoryFromPage(page)
      if (pricingCategory.value !== cat) { pricingCategory.value = cat; loadAllRoutes(cat === 'all' ? null : cat); loading.value = false }
    })

    return {
      // 状态
      loading, pricingCategory, pageTitle,
      routeSteps, allRoutes, filteredRoutes,
      editPrices, saving, priceHistory,
      
      totalRouteCount, structRouteCount, machRouteCount, pricedRouteCount,
      can, canEdit, canCreate, canDelete,
      // 卡片模式
      expandedRoute, toggleRoute, editMeta, saveRoute, isRecentDate, loadPriceHistory,
      // 方法
      switchCat, loadAllRoutes,

    }
  }
}
</script>
