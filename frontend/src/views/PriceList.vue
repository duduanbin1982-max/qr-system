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
              旧工价仅供查阅。新增或调整工价请通过版本化工价流程，并由另一名用户审批。
            </div>

            <table class="data-table" style="font-size:var(--text-sm);width:100%">
              <thead>
                <tr>
                  <th class="col-num">#</th>
                  <th class="col-min-140">工序名称</th>
                  <th class="col-cat">分类</th>
                  <th class="col-min-110 text-center">当前工价</th>
                  <th class="col-min-110 text-center">生效日期</th>
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
                </tr>
              </tbody>
            </table>

            <!-- 操作栏 -->
            <div style="display:flex;justify-content:flex-end;margin-top:16px">
              <button class="btn btn-primary" @click="openVersionedPricing">前往工价版本</button>
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
import { usePriceList } from '@/composables/wage/usePriceList.js'

export default {
  setup() {
    return usePriceList()
  }
}
</script>
