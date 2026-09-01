<!-- GanttChart.vue — 生产排程甘特图 -->
<template>
<div style="padding:var(--space-6);max-width:100%;overflow-x:auto">
  <div class="summary-bar">
    <div class="summary-item"><span class="s-icon">📅</span><div><div class="s-val">{{ stats.total }}</div><div class="s-label">总订单</div></div></div>
    <div class="summary-item"><span class="s-icon">⚙️</span><div><div class="s-val text-info">{{ stats.producing }}</div><div class="s-label">生产中</div></div></div>
    <div class="summary-item"><span class="s-icon">⏳</span><div><div class="s-val">{{ stats.pending }}</div><div class="s-label">待生产</div></div></div>
    <div class="summary-item"><span class="s-icon">✅</span><div><div class="s-val text-success">{{ stats.completed }}</div><div class="s-label">已完成</div></div></div>
  </div>

  <div class="card" style="border-radius:var(--radius-lg);overflow:hidden;padding:0">
    <div class="card-header" style="display:flex;align-items:center;gap:var(--space-3);flex-wrap:wrap;padding:var(--space-3) 20px;border-bottom:1px solid var(--bg-hover)">
      <h3 style="font-size:var(--text-lg);font-weight:700;margin:0">📅 生产排程</h3>
      <div style="display:flex;gap:var(--space-2);align-items:center;margin-left:auto;flex-wrap:wrap">
        <div style="display:flex;gap:4px;background:var(--bg-hover);padding:3px;border-radius:999px">
          <button type="button" class="btn btn-sm" :style="{padding:'4px 12px',borderRadius:'999px',background:viewMode==='orders'?'var(--primary)':'transparent',color:viewMode==='orders'?'#fff':'var(--text-secondary)',boxShadow:'none'}" @click="setViewMode('orders')">订单甘特</button>
          <button type="button" class="btn btn-sm" :style="{padding:'4px 12px',borderRadius:'999px',background:viewMode==='operations'?'var(--primary)':'transparent',color:viewMode==='operations'?'#fff':'var(--text-secondary)',boxShadow:'none'}" @click="setViewMode('operations')">工序排程</button>
        </div>
        <div style="display:flex;gap:4px;background:var(--bg-hover);padding:3px;border-radius:999px">
          <button
            v-for="tab in [
              { key: 'active', label: '进行中' },
              { key: 'completed', label: '已完成' },
              { key: 'all', label: '全部' }
            ]"
            :key="tab.key"
            type="button"
            class="btn btn-sm"
            :style="{padding:'4px 12px',borderRadius:'999px',background:scheduleScope===tab.key?'var(--primary)':'transparent',color:scheduleScope===tab.key?'#fff':'var(--text-secondary)',boxShadow:'none'}"
            @click="setScheduleScope(tab.key)">{{ tab.label }}</button>
        </div>
        <select v-if="viewMode==='orders'" v-model="wsFilter" class="form-input" style="width:140px;padding:6px 10px;font-size:var(--text-sm)">
          <option value="">全部产线</option>
          <option v-for="pl in productionLines" :key="pl.id" :value="String(pl.id)">{{ pl.name }}</option>
        </select>
        <button v-if="canManageLines" class="btn btn-sm" style="background:var(--teal);color:#fff" @click="showLineMgr=true">🏭 产线管理</button>
        <button @click="zoomOut" title="缩小" class="btn-default btn-sm">−</button>
        <button @click="zoomIn" title="放大" class="btn-default btn-sm">+</button>
        <button class="btn btn-sm" style="background:var(--success);color:#fff" @click="exportImage" title="导出PNG">📥 导出</button>
      </div>
    </div>

    <div v-if="viewMode==='orders' && selectedOrderIds.length" style="padding:8px 20px;background:var(--primary-light);border-bottom:1px solid var(--border-light);display:flex;gap:8px;align-items:center;flex-wrap:wrap">
      <span style="font-size:var(--text-xs);font-weight:600">已选 {{ selectedOrderIds.length }} 个订单</span>
      <input v-model.number="batchDays" type="number" min="1" class="form-input" style="width:60px;padding:2px 6px;font-size:var(--text-xs)">
      <span style="font-size:var(--text-xs)">天</span>
      <button class="btn-default btn-sm" @click="batchShift('left')" style="font-size:var(--text-xs)">◀ 左移</button>
      <button class="btn-default btn-sm" @click="batchShift('right')" style="font-size:var(--text-xs)">右移 ▶</button>
      <span style="font-size:10px;color:var(--text-placeholder);margin-left:8px">提示: ← → 微调1天, Shift+← → 微调7天</span>
    </div>

    <div v-if="viewMode==='orders' && dailyLoad.length" style="padding:6px 20px;background:var(--danger-light);border-bottom:1px solid var(--danger);font-size:var(--text-xs);color:var(--danger);display:flex;gap:16px;flex-wrap:wrap;align-items:center">
      <span>⚠️ 产能超载:</span>
      <span v-for="v in dailyLoad.slice(0,5)" :key="v.date+v.line" style="white-space:nowrap">{{ v.date }} {{ v.line }}: {{ v.count }}/{{ v.capacity }}</span>
      <span v-if="dailyLoad.length > 5" style="color:var(--text-placeholder)">...共 {{ dailyLoad.length }} 处</span>
    </div>

    <div v-if="viewMode==='operations'" style="padding:16px 20px">
      <div style="display:flex;gap:8px;align-items:center;flex-wrap:wrap;margin-bottom:14px">
        <select v-model="capacityProcessFilter" class="form-input" style="width:150px;padding:6px 10px;font-size:var(--text-sm)">
          <option value="">全部工序</option>
          <option v-for="process in processOptions" :key="process.id" :value="String(process.id)">{{ process.name }}</option>
        </select>
        <select v-model="capacityLineFilter" class="form-input" style="width:170px;padding:6px 10px;font-size:var(--text-sm)">
          <option value="">全部工序产线</option>
          <option v-for="line in capacityLines" :key="line.id" :value="String(line.id)">{{ line.process_name }} · {{ line.line_name }}</option>
        </select>
        <span style="font-size:var(--text-xs);color:var(--text-secondary)">共 {{ capacitySummary.total }} 道工序 · 已排 {{ capacitySummary.planned }} · 阻断 {{ capacitySummary.blocked }} · {{ Math.round(capacitySummary.minutes) }} 分钟</span>
        <div style="display:flex;gap:6px;align-items:center;margin-left:auto;flex-wrap:wrap">
          <select v-model="generationOrderId" @change="prepareGeneration(generationOrderId)" class="form-input" style="width:180px;padding:6px 10px;font-size:var(--text-sm)">
            <option value="">选择订单生成排程</option>
            <option v-for="order in capacityOrders" :key="order.id" :value="order.id">{{ order.order_no }}</option>
          </select>
          <input v-model="generationStartDate" type="date" class="form-input" style="width:145px;padding:6px 10px;font-size:var(--text-sm)">
          <button v-if="canEdit" type="button" class="btn btn-sm" style="background:var(--primary);color:#fff" @click="generateSchedule">生成工序排程</button>
          <button type="button" class="btn-default btn-sm" @click="loadCapacity">刷新</button>
        </div>
      </div>
      <div v-if="capacityLoading" style="padding:36px;text-align:center;color:var(--text-placeholder)">⏳ 加载工序排程中...</div>
      <div v-else-if="!filteredOperations.length" style="padding:36px;text-align:center;color:var(--text-placeholder)">暂无工序排程数据，请选择订单生成排程</div>
      <div v-else style="overflow:auto;border:1px solid var(--border-light)">
        <table style="width:100%;border-collapse:collapse;min-width:1200px;font-size:var(--text-sm)">
          <thead><tr style="background:var(--bg-hover);text-align:left">
            <th style="padding:9px 10px">订单</th><th style="padding:9px 10px">工序</th><th style="padding:9px 10px">产线</th><th style="padding:9px 10px">预计时间</th><th style="padding:9px 10px">数量</th><th style="padding:9px 10px">标准工时</th><th style="padding:9px 10px">来源</th><th style="padding:9px 10px">难度系数</th><th style="padding:9px 10px">占用分钟</th><th style="padding:9px 10px">状态</th>
          </tr></thead>
          <tbody><tr v-for="row in filteredOperations" :key="row.id || `${row.order_id}-${row.order_process_id}`" style="border-top:1px solid var(--bg-hover)">
            <td style="padding:8px 10px;font-weight:600;color:var(--primary)">{{ row.order_no || row.order_id }}</td>
            <td style="padding:8px 10px">{{ row.process_name || '-' }}</td>
            <td style="padding:8px 10px">{{ lineLabel(row) }}</td>
            <td style="padding:8px 10px;white-space:nowrap">{{ row.planned_start_at || row.plan_start || '-' }}<span v-if="row.planned_end_at"> ~ {{ row.planned_end_at }}</span><span v-else-if="row.plan_end"> ~ {{ row.plan_end }}</span></td>
            <td style="padding:8px 10px">{{ row.quantity || row.scheduled_quantity || 0 }}</td>
            <td style="padding:8px 10px">{{ row.standard_minutes_per_unit || 0 }} / 件</td>
            <td style="padding:8px 10px;white-space:nowrap">{{ standardScopeLabel(row.standard_match_scope) }}</td>
            <td style="padding:8px 10px">{{ row.difficulty_factor || 1 }}</td>
            <td style="padding:8px 10px">{{ Math.round(row.occupied_minutes || row.planned_minutes || 0) }}</td>
            <td style="padding:8px 10px"><span :style="{color:(row.schedule_status==='blocked'||row.status==='blocked')?'var(--danger)':'var(--success)',fontWeight:600}">{{ (row.schedule_status==='blocked'||row.status==='blocked') ? `阻断：${row.blocked_reason || row.reason || '前置条件不满足'}` : '已排程' }}</span></td>
          </tr></tbody>
        </table>
      </div>
    </div>

    <div v-if="viewMode==='orders' && loading" style="text-align:left;padding:60px;color:var(--text-placeholder)">⏳ 加载中...</div>
    <div v-else-if="viewMode==='orders' && !filteredOrders.length" style="text-align:left;padding:60px;color:var(--text-placeholder)">
      <p style="font-size:48px;margin:0">📅</p><p style="margin-top:12px">暂无排程数据</p>
    </div>

    <div v-else-if="viewMode==='orders'" class="gantt-scroll" style="position:relative;overflow-x:auto;padding-bottom:16px" @keydown.left.prevent="shiftDays(-1,false)" @keydown.right.prevent="shiftDays(1,false)" @keydown.shift.left.prevent="shiftDays(-1,true)" @keydown.shift.right.prevent="shiftDays(1,true)" tabindex="0">
      <div :style="{width: Math.max(ganttData.totalDays * dayWidth + 360, 100) + 'px', minWidth:'100%'}">
        <!-- Date Header -->
        <div style="display:flex;border-bottom:2px solid var(--border-light);position:sticky;top:0;background:var(--bg-surface);z-index:2">
          <div style="min-width:360px;max-width:360px;padding:8px 14px;font-weight:600;font-size:var(--text-xs);color:var(--text-placeholder);border-right:1px solid var(--border-light);display:flex;gap:10px;align-items:center"><input v-if="canEdit" type="checkbox" :checked="allSelected" @change="toggleAll" style="width:18px;flex-shrink:0" title="全选当前列表中的未完成订单"><span v-else style="width:18px"></span><span style="width:85px;white-space:nowrap">订单号</span><span style="width:80px">客户</span><span style="width:56px">状态</span><span style="width:50px">交期</span></div>
          <div style="display:flex;flex:1" v-if="ganttData.days.length">
            <div v-for="d in ganttData.days" :key="d.date"
              :style="{width:dayWidth+'px',textAlign:'center',padding:'8px 2px',fontSize:'10px',borderRight:'1px solid var(--bg-hover)',background:d.isWeekend?'var(--bg-hover)':d.isToday?'var(--primary-light)':'',color:d.isToday?'var(--primary)':'var(--text-placeholder)'}">
              {{ d.label }}
            </div>
          </div>
        </div>

        <!-- Order Rows -->
        <div v-for="(order, i) in filteredOrders" :key="order.id" style="position:relative;border-bottom:1px solid var(--bg-hover)" :style="{background:i%2===0?'#fff':'var(--bg-table-stripe)'}">
          <div style="display:flex;min-height:52px;align-items:stretch">
            <!-- Order Info Card -->
            <div style="min-width:360px;max-width:360px;padding:6px 14px;border-right:1px solid var(--border-light);display:flex;flex-direction:column;justify-content:center;gap:4px">
              <!-- 第一行：复选框 + 订单号 + 客户 + 状态 + 交期 -->
              <div style="display:flex;align-items:center;gap:10px">
                <input v-if="canEdit" type="checkbox" :checked="selectedOrderIds.includes(order.id)" :disabled="isCompleted(order)" @change="toggleOrder(order)" style="width:18px;flex-shrink:0" :title="isCompleted(order) ? '已完成订单只读，不参与批量调整' : ''"><span v-else style="width:18px;flex-shrink:0"></span>
                <span style="font-size:var(--text-sm);font-weight:600;color:var(--primary);white-space:nowrap;overflow:hidden;text-overflow:ellipsis;width:85px;text-align:left" :title="order.order_no">{{ order.order_no }}</span>
                <span style="flex-shrink:0;font-size:var(--text-xs);color:var(--text-secondary);white-space:nowrap;overflow:hidden;text-overflow:ellipsis;width:80px;text-align:left" :title="order.customer_name||''">{{ order.customer_name || '-' }}</span>
                <span :style="{flexShrink:0,fontSize:'12px',padding:'1px 6px',borderRadius:'3px',textAlign:'left',minWidth:'56px',background:order.status==='producing'?'var(--primary-light)':order.status==='completed'?'var(--success-light)':'var(--bg-hover)',color:order.status==='producing'?'var(--primary)':order.status==='completed'?'var(--success)':'var(--text-placeholder)'}">{{ statusLabel(order.status) }}</span>
                <span v-if="order.risk!=='normal'" style="width:16px;flex-shrink:0;font-size:10px;text-align:left" :title="order.risk==='overdue'?'已过期':'即将到期'">{{ order.risk==='overdue'?'🔴':'🟡' }}</span>
                <span style="flex-shrink:0;font-size:9px;color:var(--text-placeholder);width:50px;text-align:left" :title="order.deadline||''">{{ order.deadline ? order.deadline.slice(5) : '-' }}</span>
              </div>
              <!-- 第二行：产品编码 + 进度条 -->
              <div style="display:flex;align-items:center;gap:10px">
                <span style="font-size:9px;color:var(--text-secondary);font-weight:400;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;flex:1" :title="order.product_code||order.product_name||''">{{ order.product_code || order.product_name || '-' }}</span>
                <span style="flex-shrink:0;display:flex;align-items:center;gap:4px;min-width:60px">
                  <span style="display:inline-block;width:40px;height:4px;background:var(--bg-hover);border-radius:2px">
                    <span :style="{display:'inline-block',height:'100%',borderRadius:'2px',background:order.progress>=100?'var(--success)':order.progress>=60?'var(--primary)':order.progress>=30?'var(--warning)':'var(--danger)',width:Math.min(order.progress,100)+'%'}"></span>
                  </span>
                  <span style="font-size:9px;color:var(--text-placeholder);min-width:24px;text-align:right">{{ order.completed_qty||0 }}/{{ order.quantity||0 }}</span>
                </span>
              </div>
            </div>
            <!-- Gantt Bar Area -->
            <div :style="{flex:1,position:'relative',minHeight:'52px'}">
              <div v-for="d in ganttData.days" :key="'bg'+d.date"
                :style="{position:'absolute',left:(ganttData.days.indexOf(d)*dayWidth)+'px',top:0,width:dayWidth+'px',height:'100%',background:d.isWeekend?'rgba(0,0,0,0.03)':'transparent'}">
              </div>
              <div v-for="d in ganttData.days.filter(x=>x.isToday)" :key="'today'+d.date"
                :style="{position:'absolute',left:(ganttData.days.indexOf(d)*dayWidth+dayWidth/2)+'px',top:0,width:'2px',height:'100%',background:'#ef4444',zIndex:4,pointerEvents:'none'}">
              </div>
              <div v-if="order.plan_start && order.plan_end"
                :style="{position:'absolute',left:barLeft(order)+'px',top:'12px',
                  width:barWidth(order)+'px',height:'28px',
                  background:barColor(order.status),borderRadius:'6px',
                  cursor: canAdjustOrder(order) ? 'col-resize' : 'default',
                  display:'flex',alignItems:'center',justifyContent:'center',
                  color:'#fff',fontSize:'10px',fontWeight:600,
                  boxShadow: isOverloaded(ganttData.days[Math.floor(barLeft(order)/dayWidth)]?.date, order.production_line_id) ? '0 0 0 2px var(--danger), 0 1px 3px rgba(0,0,0,0.3)' : '0 1px 3px rgba(0,0,0,0.15)',zIndex:1,
                  transition: dragTarget===order ? 'none' : 'box-shadow 0.15s',
                  userSelect:'none'
                }"
                @mousedown="onBarMouseDown($event, order)"
                @dblclick="editOrderDates(order)"
                :title="order.plan_start + ' ~ ' + order.plan_end + ' | 产量: ' + (order.completed_qty||0) + '/' + (order.quantity||0) + (order.production_line ? ' | 产线: ' + order.production_line : '') + (isOverloaded(ganttData.days[Math.floor(barLeft(order)/dayWidth)]?.date, order.production_line_id) ? ' ⚠️产能超载' : '') + (isCompleted(order) ? ' | 已完成订单只读' : '')" >
                <span v-if="order.quantity" style="margin-right:4px">{{ order.completed_qty||0 }}/{{ order.quantity }}</span>
                {{ order.production_line || statusLabel(order.status) }}
              </div>
              <div v-if="dragTarget===order"
                :style="{position:'absolute',left:dragPreviewLeft+'px',top:'12px',width:dragPreviewWidth+'px',height:'28px',background:'rgba(37,99,235,0.3)',border:'2px dashed #2563eb',borderRadius:'6px',zIndex:3,pointerEvents:'none'}">
              </div>
            </div>
          </div>
        </div>
      </div>
    </div>

    <!-- Edit Modal -->
    <div v-if="showEditModal" class="modal-overlay" @click.self="undoLastDrag">
      <div class="modal" style="max-width:420px">
        <div class="modal-header"><h3>✏️ 编辑排程</h3></div>
        <div class="modal-body">
          <div class="form-group"><label>开始日期</label><input v-model="editForm.plan_start" type="date" class="form-input"></div>
          <div class="form-group"><label>结束日期</label><input v-model="editForm.plan_end" type="date" class="form-input"></div>
          <div class="form-group"><label>产线</label>
            <select v-model="editForm.production_line_id" class="form-input">
              <option value="">未分配</option>
              <option v-for="pl in productionLines" :key="pl.id" :value="pl.id">{{ pl.name }}</option>
            </select>
          </div>
        </div>
        <div class="modal-footer">
          <button class="btn btn-default" @click="undoLastDrag">取消</button>
          <button class="btn btn-primary" @click="saveEditDates">保存</button>
        </div>
      </div>
    </div>

    <!-- Prod Line Modal -->
    <div v-if="showLineMgr" class="modal-overlay" @click.self="showLineMgr=false">
      <div class="modal" style="max-width:480px">
        <div class="modal-header"><h3>🏭 产线管理</h3></div>
        <div class="modal-body">
          <div style="display:flex;gap:8px;margin-bottom:12px;flex-wrap:wrap">
            <input v-model="lineForm.name" class="form-input" placeholder="产线名称" style="flex:1;min-width:120px">
            <input v-model="lineForm.remark" class="form-input" placeholder="描述" style="flex:1;min-width:100px">
            <input v-model.number="lineForm.capacity_per_day" type="number" class="form-input" placeholder="产能/天" style="width:80px">
            <button class="btn btn-primary btn-sm" @click="addLine">添加</button>
          </div>
          <div v-if="productionLines.length" style="max-height:200px;overflow-y:auto">
            <div v-for="pl in productionLines" :key="pl.id" style="display:flex;align-items:center;justify-content:space-between;padding:6px 8px;border-bottom:1px solid var(--bg-hover);gap:8px">
              <span style="font-weight:600;min-width:80px">{{ pl.name }}</span>
              <span style="font-size:var(--text-xs);color:var(--text-placeholder);flex:1">{{ pl.remark || '-' }} · 产能: {{ pl.capacity_per_day || '-' }}/天</span>
              <button class="btn-default" style="font-size:var(--text-xs);padding:2px 8px;color:var(--danger)" @click="delLine(pl)">删除</button>
            </div>
          </div>
        </div>
        <div class="modal-footer"><button class="btn btn-default" @click="showLineMgr=false">关闭</button></div>
      </div>
    </div>
  </div>
</div>
</template>

<script>
import { useGantt } from '@/composables/useGantt.js'

export default {
  setup() {
    return { ...useGantt() }
  }
}
</script>
