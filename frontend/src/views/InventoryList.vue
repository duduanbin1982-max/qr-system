<!-- InventoryList.vue -->
<template>
<div class="inventory-page">
    <header class="inventory-page-header">
      <div class="inventory-page-title-block">
        <div class="inventory-page-eyebrow">物料与库存</div>
        <div class="inventory-page-title-row">
          <span class="inventory-page-icon" aria-hidden="true">📦</span>
          <div>
            <h1>库存管理</h1>
            <p>按订单追溯库存明细，按产品编码查看跨订单汇总。</p>
          </div>
        </div>
      </div>
      <div class="inventory-page-status" aria-live="polite">
        <span class="inventory-page-status-dot" aria-hidden="true"></span>
        <span>{{ productState.viewMode === 'product' ? '产品编码视图' : '订单明细视图' }}</span>
      </div>
    </header>

    <div class="inventory-navigation">
      <InventoryViewTabs v-model="productState.viewMode" :product-enabled="productState.enabled" @update:model-value="productActions.setViewMode" />
      <span class="inventory-navigation-hint">切换视图不会改变库存事实，只改变统计与列表口径。</span>
    </div>

    <section class="inventory-overview" aria-labelledby="inventory-overview-title">
      <div class="inventory-section-heading">
        <div>
          <h2 id="inventory-overview-title">库存概览</h2>
          <p>统计卡片会随当前筛选条件实时更新，点击低库存可直接进入预警清单。</p>
        </div>
        <span class="inventory-section-context">{{ productState.viewMode === 'product' ? '按产品编码汇总' : '按订单明细' }}</span>
      </div>
      <div class="summary-bar inventory-summary-bar" aria-live="polite" :aria-busy="productState.viewMode === 'product' ? productState.summaryLoading : summaryLoading">
      <div class="summary-item"><span class="s-icon">📦</span><div><div class="s-val">{{ summaryValue('total_items') }}</div><div class="s-label">当前筛选库存品类</div></div></div>
      <div class="summary-item"><span class="s-icon">📊</span><div><div class="s-val text-primary">{{ summaryValue('total_quantity') }}</div><div class="s-label">当前筛选库存总量</div></div></div>
      <div class="summary-item"><span class="s-icon">💎</span><div><div class="s-val" style="color:var(--primary)">{{ Number(summaryValue('total_value') || 0).toLocaleString() }}</div><div class="s-label">当前筛选库存总值</div></div></div>
      <div class="summary-item"><span class="s-icon">📥</span><div><div class="s-val text-success">{{ summaryValue('today_in') }}</div><div class="s-label">筛选范围今日入库</div></div></div>
      <div class="summary-item"><span class="s-icon">📤</span><div><div class="s-val text-warning">{{ summaryValue('today_out') }}</div><div class="s-label">筛选范围今日出库</div></div></div>
      <button class="summary-item summary-item-action" type="button" :aria-label="`筛选低库存，共 ${summaryValue('low_stock')} 项`" @click="focusLowStock">
        <span class="s-icon">⚠️</span><div><div class="s-val" :style="{color: summaryValue('low_stock') > 0 ? 'var(--danger)' : 'var(--success)'}">{{ summaryValue('low_stock') }}</div><div class="s-label">低库存预警（点击筛选）</div></div>
      </button>
      </div>
    </section>

    <div v-if="productState.viewMode === 'product'" class="card inventory-product-card">
      <div class="inventory-card-heading">
        <div>
          <h2>按产品编码查看</h2>
          <p>合并同一产品在不同订单、批次和库位中的库存。</p>
        </div>
        <span class="inventory-card-count">{{ productState.total }} 个产品</span>
      </div>
      <ProductInventoryTable
        :groups="productState.groups"
        :filters="productState.filters"
        :filter-options="productState.filterOptions"
        :saved-filters="productState.savedFilters"
        :can-export="productState.canExport"
        :loading="productState.loading"
        :error="productState.error"
        :total="productState.total"
        :page="productState.page"
        :limit="productState.limit"
        :columns="productState.productColumns"
        :visible-columns="productState.visibleColumns"
        :selected-ids="productState.selectedIds"
        :selected-count="productState.selectedCount"
        :sort-by="productState.sortBy"
        :sort-dir="productState.sortDir"
        @search="productActions.searchGroups"
        @reset="productActions.resetFilters"
        @update-filter="productActions.setFilter"
        @clear-filter="productActions.clearFilter"
        @save-filter="productActions.saveFilter"
        @apply-filter="productActions.applyFilter"
        @remove-filter="productActions.removeFilterPreset"
        @export="productActions.exportGroups"
        @export-csv="productActions.exportGroupsCsv"
        @change-page="productActions.changePage"
        @change-limit="productActions.changeLimit"
        @open-product="productActions.openProduct"
        @update-columns="productActions.setVisibleColumns"
        @reset-columns="productActions.resetVisibleColumns"
        @toggle-select-all="productActions.toggleSelectAll"
        @toggle-select="productActions.toggleSelect"
        @batch-export="productActions.exportSelected"
        @sort="productActions.setSort"
      />
    </div>
    <ProductInventoryDrawer :open="productState.drawerOpen" :product="productState.selectedProduct" :details="productState.selectedDetails" :capabilities="productState.capabilities" :can-export="productState.canExport" @close="productActions.closeDrawer" />
    <InventoryOrderDrawer :open="Boolean(orderDrawerItem)" :item="orderDrawerItem" @close="closeOrderDetails" @logs="openOrderLogs" />
    <!-- ====== 主内容卡片 ====== -->
    <div v-if="productState.viewMode !== 'product'" class="card inventory-order-card">
      <div class="inventory-card-heading inventory-order-header">
        <div>
          <h2>按订单查看</h2>
          <p>保留订单归属、库位和出入库操作，适合逐条追溯。</p>
        </div>
        <span class="inventory-card-count">{{ total }} 条库存</span>
      </div>
      <div class="inventory-order-filter-area">
        <InventoryFilterWorkbench
          view-mode="order"
          :filters="filters"
          :filter-options="filterOptions"
          :saved-filters="savedFilters"
          :result-count="total"
          :loading="loading"
          @search="search"
          @reset="resetFilters"
          @update-filter="setFilter"
          @clear-filter="clearFilter"
          @save-filter="saveFilter"
          @apply-filter="applyFilter"
          @remove-filter="removeFilterPreset"
        >
          <template #actions>
            <div class="inventory-action-group">
              <InventoryColumnConfigurator :columns="orderColumns" :visible-keys="visibleColumns" @update="setVisibleColumns" @reset="resetVisibleColumns" />
              <label class="inventory-page-select" title="选择当前页"><input type="checkbox" :checked="orderPageSelected" :disabled="!items.length" @change="toggleSelectAll"> 选择当前页</label>
              <span v-if="selectedCount" class="inventory-selection-count">已选 {{ selectedCount }} 项</span>
            </div>
            <div class="inventory-action-group inventory-action-group-secondary">
              <button v-if="canExport && selectedCount" class="btn btn-default btn-sm" type="button" @click="exportSelected">批量导出</button>
              <button class="btn btn-default btn-sm" type="button" @click="doABC">ABC</button>
              <button class="btn btn-default btn-sm" type="button" @click="loadLogs()">流水</button>
              <button class="btn btn-default btn-sm" type="button" @click="loadTurnover">周转</button>
              <button class="btn btn-default btn-sm" type="button" @click="doCount">盘点</button>
            </div>
            <div class="inventory-action-group">
              <button v-if="canExport" class="btn btn-default btn-sm" type="button" @click="exportExcel">导出 XLSX</button>
              <button v-if="canExport" class="btn btn-default btn-sm" type="button" @click="exportCsv">导出 CSV</button>
              <button v-if="canCreate" class="btn btn-primary btn-sm" type="button" @click="openAdd">+ 新增库存</button>
            </div>
          </template>
        </InventoryFilterWorkbench>
      </div>
      <div class="card-body" style="padding:0">
        <div class="table-wrap inventory-table-scroll" style="border-radius:0">
          <table v-if="items.length" class="data-table inventory-order-table" style="min-width:850px;margin:0">
            <thead>
              <tr style="background:var(--bg-table-header)">
                <th v-for="column in orderVisibleColumnDefs" :key="column.key" :class="column.key === 'actions' ? 'inventory-order-actions-head' : ''" :aria-sort="ariaSort(column.key)">
                  <button v-if="column.key !== 'actions'" class="inventory-sort-button" type="button" @click="setSort(column.key)">{{ column.label }}<span class="inventory-sort-indicator" aria-hidden="true">{{ sortIndicator(column.key) }}</span></button>
                  <span v-else>{{ column.label }}</span>
                </th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="item in items" :key="item.id" class="inv-row" :class="{'inv-row-low': item.is_low}" @click="openOrderDetails(item)" style="cursor:pointer">
                <td v-for="column in orderVisibleColumnDefs" :key="column.key">
                  <template v-if="column.key === 'product_name'"><span style="font-weight:500">{{ item.product_name || '-' }}</span></template>
                  <template v-else-if="column.key === 'order_no'"><code style="font-size:var(--text-xs-alt)">{{ item.order_no || '-' }}</code></template>
                  <template v-else-if="column.key === 'customer'"><span style="font-size:var(--text-xs)">{{ item.customer || '-' }}</span></template>
                  <template v-else-if="column.key === 'product_model'"><div style="display:flex;align-items:center;gap:var(--space-2)"><input class="inventory-row-select" type="checkbox" :checked="selectedIds.includes(item.id)" :aria-label="`选择 ${item.product_model}`" @click.stop @change="toggleSelect(item.id)"><span :style="{display:'inline-block',width:8,height:8,borderRadius:'50%',background: item.is_low ? 'var(--danger)' : 'var(--success)',flexShrink:0}"></span><code style="font-size:var(--text-xs);font-weight:600;color:var(--text-primary)">{{ item.product_model }}</code></div></template>
                  <template v-else-if="column.key === 'specification'"><span style="font-size:var(--text-xs);color:var(--text-placeholder)">{{ item.specification || '-' }}</span></template>
                  <template v-else-if="column.key === 'category'"><span v-if="item.category" class="badge" :class="item.category==='A'?'badge-danger':item.category==='B'?'badge-warning':'badge-success'">{{ item.category }}</span><span v-else>-</span></template>
                  <template v-else-if="column.key === 'quantity'"><span class="inventory-order-quantity" :class="item.is_low ? 'is-low' : ''">{{ item.available_quantity ?? 0 }}</span><small v-if="item.reserved">现存 {{ item.quantity }} / 预留 {{ item.reserved }}</small></template>
                  <template v-else-if="column.key === 'safe_stock'"><span>{{ item.safe_stock || 0 }}</span></template>
                  <template v-else-if="column.key === 'location'"><span>{{ item.location || '-' }}</span></template>
                  <template v-else-if="column.key === 'unit'"><span>{{ item.unit || '-' }}</span></template>
                  <template v-else-if="column.key === 'actions'"><div class="inv-actions" @click.stop><button v-if="canEdit" class="inv-btn inv-btn-in" @click="openMove(item, 'in')" title="入库"><span>📥</span><span>入库</span></button><button v-if="canEdit" class="inv-btn inv-btn-out" @click="openMove(item, 'out')" title="出库"><span>📤</span><span>出库</span></button><button class="inv-btn inv-btn-edit" @click="openEdit(item)" v-if="canEdit" title="编辑"><span>✏️</span></button><button class="inv-btn inv-btn-del" @click="del(item)" v-if="canDelete" title="停用"><span>🗑️</span></button></div></template>
                </td>
              </tr>
            </tbody>
          </table>
          <div v-else style="text-align:center;padding:60px 20px">
            <div style="font-size:48px;margin-bottom:var(--space-3);opacity:0.4">🏗️</div>
            <div style="font-size:var(--text-base);color:var(--text-placeholder);margin-bottom:6px">暂无库存数据</div>
            <div style="font-size:var(--text-xs);color:var(--border)">点击「+ 新增库存」添加第一条记录</div>
          </div>
        </div>
        <div v-if="total > 0" class="inventory-pagination" aria-label="按订单库存分页" style="display:flex;align-items:center;justify-content:flex-end;flex-wrap:wrap;gap:10px;padding:12px 16px;border-top:1px solid var(--border-light);background:var(--bg-table-stripe);font-size:13px;color:var(--text-secondary)">
          <span>共 {{ total }} 条，当前显示 {{ (page - 1) * limit + 1 }}–{{ Math.min(page * limit, total) }}</span>
          <label>每页
            <select class="form-input" :value="limit" @change="changeLimit(Number($event.target.value))">
              <option :value="50">50</option><option :value="100">100</option><option :value="200">200</option><option :value="500">500</option>
            </select>
          </label>
          <button class="btn btn-default btn-sm" :disabled="page <= 1" @click="changePage(page - 1)">上一页</button>
          <span>第 {{ page }} / {{ Math.max(1, Math.ceil(total / limit)) }} 页</span>
          <button class="btn btn-default btn-sm" :disabled="page >= Math.ceil(total / limit)" @click="changePage(page + 1)">下一页</button>
        </div>
      </div>
    </div>
    <!-- 新增/编辑模态框 -->
    <div v-if="showModal" class="modal-overlay" >
      <div class="modal" style="max-width:550px">
        <div class="modal-header">
          <span>{{ modalEdit ? '编辑库存' : '新增库存' }}</span>
          <span class="modal-close" @click="showModal=false">&times;</span>
        </div>
        <div class="modal-body">
          <div class="form-row">
            <div class="form-col" style="flex:2"><div class="form-group"><label>产品型号 *</label><input class="form-input" v-model="form.product_model" :disabled="modalEdit" placeholder="唯一标识"></div></div>
            <div v-if="!modalEdit" class="form-col" style="flex:1"><div class="form-group"><label>关联订单</label><select class="form-input" v-model="form.order_id"><option value="">-- 无 --</option><option v-for="o in orderOptions" :key="o.id" :value="o.id">{{ o.order_no }} {{ o.product_name }}</option></select></div></div>
            <div class="form-col" style="flex:1"><div class="form-group"><label>单位</label><input class="form-input" v-model="form.unit" placeholder="件"></div></div>
          </div>
          <div class="form-row">
            <div class="form-col"><div class="form-group"><label>产品名称</label><input class="form-input" v-model="form.product_name" placeholder="名称"></div></div>
            <div class="form-col"><div class="form-group"><label>规格</label><input class="form-input" v-model="form.specification" placeholder="规格"></div></div>
          </div>
          <div class="form-row">
            <div class="form-col" v-if="!modalEdit"><div class="form-group"><label>初始数量</label><input class="form-input" v-model.number="form.quantity" type="number" min="0"></div></div>
            <div class="form-col"><div class="form-group"><label>安全库存</label><input class="form-input" v-model.number="form.safe_stock" type="number" min="0"></div></div>
            <div class="form-col"><div class="form-group"><label>存放位置</label><input class="form-input" v-model="form.location" placeholder="如：A区-3号架"></div></div>
          </div>
          <div class="form-group"><label>备注</label><input class="form-input" v-model="form.remark" placeholder="备注"></div>
        </div>
        <div class="modal-footer">
          <button class="btn btn-default" @click="showModal=false">取消</button>
          <button class="btn btn-primary" @click="save">保存</button>
        </div>
      </div>
    </div>
    <!-- 出入库模态框 -->
    <div v-if="showMoveModal" class="modal-overlay" >
      <div class="modal" style="max-width:400px">
        <div class="modal-header">
          <span>{{ moveType === 'in' ? '📥 入库' : '📤 出库' }} — {{ moveTarget?.product_model }}</span>
          <span class="modal-close" @click="showMoveModal=false">&times;</span>
        </div>
        <div class="modal-body" style="text-align:center">
          <p style="color:var(--text-placeholder);margin-bottom:var(--space-4)">当前库存：<strong>{{ moveTarget?.quantity }}</strong> {{ moveTarget?.unit }}</p>
          <div class="form-group" v-if="moveType==='in'" style="margin-bottom:var(--space-3)">
            <label>关联订单</label>
            <select class="form-input" v-model="moveOrderId" style="text-align:center">
              <option value="">-- 无 --</option>
              <option v-for="o in orderOptions" :key="o.id" :value="o.id">{{ o.order_no }} {{ o.product_name }}</option>
            </select>
          </div>
          <div class="form-group">
            <label>{{ moveType === 'in' ? '入库' : '出库' }}数量</label>
            <input class="form-input" v-model.number="moveQty" type="number" min="1" style="text-align:center;font-size:24px;font-weight:700;width:150px;margin:0 auto" autofocus @keyup.enter="doMove">
          </div>
          <div class="form-row" style="margin-top:var(--space-3)">
            <div class="form-col"><div class="form-group"><label>批次号</label><input class="form-input" v-model="moveLotNo" placeholder="可选"></div></div>
            <div class="form-col"><div class="form-group"><label>序列号</label><input class="form-input" v-model="moveSerialNo" placeholder="可选"></div></div>
          </div>
        </div>
        <div class="modal-footer" style="justify-content:center">
          <button class="btn btn-default" @click="showMoveModal=false">取消</button>
          <button class="btn" :class="moveType === 'in' ? 'btn-success' : 'btn-warning'" @click="doMove" style="min-width:100px">
            {{ moveType === 'in' ? '确认入库' : '确认出库' }}
          </button>
        </div>
      </div>
    </div>
    <!-- 流水日志 -->
    <div v-if="showLogs" class="modal-overlay" >
      <div class="modal" style="max-width:1500px">
        <div class="modal-header">
          <span>📋 库存流水</span>
          <div style="display:flex;gap:var(--space-2);align-items:center">
            <button class="btn btn-default btn-sm" @click="window.open('/api/inventory/logs/export','_blank')" style="font-size:var(--text-xs)">📥导出</button>
            <span class="modal-close" @click="showLogs=false">&times;</span>
          </div>
        </div>
        <div class="modal-body">
          <div v-if="logsLoading" style="text-align:center;padding:40px">⏳ 加载中...</div>
          <table v-else-if="logs.length" class="data-table">
            <thead><tr><th style="min-width:150px">时间</th><th style="min-width:130px">型号</th><th style="min-width:60px">类型</th><th style="min-width:60px">数量</th><th style="min-width:80px">操作人</th><th style="min-width:180px">备注</th></tr></thead>
            <tbody>
              <tr v-for="l in logs" :key="l.id">
                <td style="font-size:var(--text-xs);white-space:nowrap">{{ l.created_at }}</td>
                <td style="white-space:nowrap"><code style="font-size:var(--text-xs-alt)">{{ l.product_model }}</code></td>
                <td><span class="badge" :class="Number(l.qty_delta)>=0?'badge-success':'badge-warning'" style="font-size:var(--text-xs-alt)">{{ ({in:'入库',out:'出库',opening_balance:'期初',count_gain:'盘盈',count_loss:'盘亏',return:'归还',reserve:'预留',release:'释放'})[l.type] || l.type }}</span></td>
                <td style="font-weight:600" :style="{color: Number(l.qty_delta)>=0?'var(--success)':'var(--danger)'}">{{ Number(l.qty_delta)>0?'+':'' }}{{ l.qty_delta }}</td>
                <td style="font-size:var(--text-sm);white-space:nowrap">{{ l.operator_name || '-' }}</td>
                <td style="font-size:var(--text-xs);color:var(--text-placeholder);white-space:nowrap">{{ l.remark || '-' }}</td>
              </tr>
            </tbody>
          </table>
          <p v-else style="text-align:center;color:var(--text-muted);padding:40px">暂无流水记录</p>
        </div>
      </div>
    </div>

    <!-- 盘点任务 -->
    <div v-if="showCount" class="modal-overlay">
      <div class="modal" style="max-width:1100px">
        <div class="modal-header">
          <span>盘点任务 {{ countTask?.task_no }}</span>
          <span class="modal-close" @click="showCount=false">&times;</span>
        </div>
        <div class="modal-body">
          <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:var(--space-3);gap:var(--space-3)">
            <span class="badge">{{ ({counting:'盘点中',submitted:'待审批',posted:'已过账'})[countTask?.status] || countTask?.status }}</span>
            <span style="font-size:var(--text-sm);color:var(--text-muted)">{{ countItems.filter(item => item.status !== 'pending').length }} / {{ countItems.length }}</span>
          </div>
          <div class="table-wrap">
            <table class="data-table" style="min-width:760px">
              <thead><tr><th>产品型号</th><th>产品名称</th><th>账面数量</th><th>实盘数量</th><th>差异</th><th>备注</th><th>操作</th></tr></thead>
              <tbody>
                <tr v-for="item in countItems" :key="item.id">
                  <td><code>{{ item.product_model }}</code></td>
                  <td>{{ item.product_name || '-' }}</td>
                  <td style="text-align:center">{{ item.book_quantity }}</td>
                  <td style="width:130px"><input class="form-input" type="number" min="0" v-model.number="item.actual_qty" :disabled="countTask?.status !== 'counting'"></td>
                  <td style="text-align:center" :style="{color:Number(item.actual_qty)-Number(item.book_quantity)===0?'var(--text-muted)':'var(--danger)'}">{{ Number(item.actual_qty)-Number(item.book_quantity) }}</td>
                  <td><input class="form-input" v-model="item.remark" :disabled="countTask?.status !== 'counting'" placeholder="可选"></td>
                  <td style="text-align:center"><button v-if="countTask?.status === 'counting'" class="btn btn-default btn-sm" @click="saveCountItem(item)">保存</button><span v-else>{{ item.status === 'posted' ? '已过账' : '已录入' }}</span></td>
                </tr>
              </tbody>
            </table>
          </div>
        </div>
        <div class="modal-footer">
          <button class="btn btn-default" @click="showCount=false">关闭</button>
          <button v-if="countTask?.status === 'submitted'" class="btn btn-primary" :disabled="countLoading" @click="approveCount">审批过账</button>
        </div>
      </div>
    </div>

    <!-- 周转率模态框 -->
    <div v-if="showTurnover" class="modal-overlay" >
      <div class="modal" style="max-width:700px">
        <div class="modal-header">
          <span>📊 库存周转分析</span>
          <span class="modal-close" @click="showTurnover=false">&times;</span>
        </div>
        <div class="modal-body">
          <div v-if="turnoverLoading" style="text-align:center;padding:40px">⏳ 加载中...</div>
          <table v-else-if="turnoverData.length" class="data-table">
            <thead><tr><th>产品型号</th><th>当前库存</th><th>月出库</th><th>月周转率</th><th>状态</th></tr></thead>
            <tbody>
              <tr v-for="t in turnoverData" :key="t.id">
                <td><code style="font-size:var(--text-xs-alt)">{{ t.product_model }}</code></td>
                <td style="text-align:center;font-weight:600">{{ t.current_stock }}</td>
                <td style="text-align:center">{{ t.total_out || 0 }}</td>
                <td style="text-align:center">{{ t.turnover_rate || '-' }}</td>
                <td><span class="badge" :class="t.total_out===0?'badge-danger':t.turnover_rate<0.5?'badge-warning':'badge-success'" style="font-size:var(--text-2xs)">{{ t.total_out===0?'滞销':t.turnover_rate<0.5?'慢动':'正常' }}</span></td>
              </tr>
            </tbody>
          </table>
          <p v-else style="text-align:center;color:var(--text-muted);padding:40px">暂无数据</p>
        </div>
      </div>
    </div>
  </div>
</template>
<script>
import { reactive, ref, computed } from 'vue'
import { useInventory } from '@/composables/useInventory.js'
import { useInventoryProductGroups } from '@/composables/inventory/useInventoryProductGroups.js'
import InventoryViewTabs from '@/components/inventory/InventoryViewTabs.vue'
import InventoryFilterWorkbench from '@/components/inventory/InventoryFilterWorkbench.vue'
import ProductInventoryTable from '@/components/inventory/ProductInventoryTable.vue'
import ProductInventoryDrawer from '@/components/inventory/ProductInventoryDrawer.vue'
import InventoryColumnConfigurator from '@/components/inventory/InventoryColumnConfigurator.vue'
import InventoryOrderDrawer from '@/components/inventory/InventoryOrderDrawer.vue'

export default {
  components: { InventoryViewTabs, InventoryFilterWorkbench, ProductInventoryTable, ProductInventoryDrawer, InventoryColumnConfigurator, InventoryOrderDrawer },
  setup() {
    const inventory = useInventory()
    const product = useInventoryProductGroups()
    const productActions = product.actions
    // The composable exposes refs for direct JavaScript consumers. Convert the
    // nested state object at the view boundary so Vue unwraps those refs in the
    // template (tabs, table and drawer otherwise receive Ref objects).
    const productState = reactive(product.state)
    const orderDrawerItem = ref(null)
    const orderColumns = inventory.orderColumns
    const orderVisibleColumnDefs = computed(() => orderColumns.filter(column => inventory.visibleColumns.value.includes(column.key)))
    const orderPageSelected = computed(() => inventory.items.value.length > 0 && inventory.items.value.every(item => inventory.selectedIds.value.includes(item.id)))
    const openOrderDetails = (item) => { orderDrawerItem.value = item }
    const openOrderLogs = (item) => { closeOrderDetails(); loadLogs(item?.id) }
    const setSort = (key) => inventory.setSort(key)
    const toggleSelectAll = () => inventory.toggleSelectAll()
    const toggleSelect = (id) => inventory.toggleSelect(id)
    const sortIndicator = (key) => inventory.sortBy.value === key ? (inventory.sortDir.value === 'asc' ? ' ↑' : ' ↓') : ''
    const ariaSort = (key) => inventory.sortBy.value === key ? (inventory.sortDir.value === 'asc' ? 'ascending' : 'descending') : 'none'
    const closeOrderDetails = () => { orderDrawerItem.value = null }
    const summaryValue = (key) => {
      if (productState.viewMode === 'product') return productState.summary?.[key] || 0
      return inventory.stats.value?.[key] || 0
    }
    const focusLowStock = () => {
      if (productState.viewMode === 'product') {
        productActions.setFilter({ key: 'low_stock', value: true })
        return productActions.searchGroups()
      }
      inventory.setFilter({ key: 'low_stock', value: true })
      return inventory.search()
    }
    return { ...inventory, productState, productActions, orderDrawerItem, orderColumns, orderVisibleColumnDefs, orderPageSelected, openOrderDetails, closeOrderDetails, openOrderLogs, setSort, toggleSelectAll, toggleSelect, sortIndicator, ariaSort, summaryValue, focusLowStock }
  }
}
</script>
