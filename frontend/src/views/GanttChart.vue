<!-- GanttChart.vue — 生产排程甘特图 -->
<template>
<div style="padding:var(--space-6);max-width:100%;overflow-x:auto">
  <div class="summary-bar">
    <div class="summary-item"><span class="s-icon">📅</span><div><div class="s-val">{{ stats.total }}</div><div class="s-label">总订单</div></div></div>
    <div class="summary-item"><span class="s-icon">⚙️</span><div><div class="s-val text-info">{{ stats.producing }}</div><div class="s-label">生产中</div></div></div>
    <div class="summary-item"><span class="s-icon">⏳</span><div><div class="s-val">{{ stats.pending }}</div><div class="s-label">待生产</div></div></div>
    <div class="summary-item"><span class="s-icon">✅</span><div><div class="s-val text-success">{{ stats.completed }}</div><div class="s-label">已完成</div></div></div>
    <div class="summary-item" :style="{borderColor:riskSummary.overdue?'var(--danger)':'var(--border-light)'}"><span class="s-icon">⛔</span><div><div class="s-val" :style="{color:riskSummary.overdue?'var(--danger)':'var(--text-primary)'}">{{ riskSummary.overdue }}</div><div class="s-label">已逾期</div></div></div>
    <div class="summary-item" :style="{borderColor:riskSummary.high?'#f97316':'var(--border-light)'}"><span class="s-icon">⚠️</span><div><div class="s-val" :style="{color:riskSummary.high?'#f97316':'var(--text-primary)'}">{{ riskSummary.high + riskSummary.medium }}</div><div class="s-label">高/中风险</div></div></div>
    <div v-if="riskSummary.delayed" class="summary-item"><span class="s-icon">🕒</span><div><div class="s-val" style="color:var(--danger)">{{ formatRiskMinutes(riskSummary.totalDelayMinutes) }}</div><div class="s-label">预计延期总量</div></div></div>
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
        <button v-if="canManageNodes || canManageCalendars" class="btn btn-sm" style="background:var(--teal);color:#fff" @click="showNodeMgr=true">⚙️ 生产节点管理</button>
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

    <div v-if="viewMode==='orders' && (riskSummary.overdue || riskSummary.high || riskSummary.medium)" style="padding:7px 20px;background:linear-gradient(90deg,#fff7ed,#fff1f2);border-bottom:1px solid #fed7aa;font-size:var(--text-xs);display:flex;gap:14px;align-items:center;flex-wrap:wrap">
      <span style="font-weight:700;color:#c2410c">⚠️ 交期预警</span>
      <span v-if="riskSummary.overdue" style="color:var(--danger)">已逾期 {{ riskSummary.overdue }} 单</span>
      <span v-if="riskSummary.high" style="color:#c2410c">高风险 {{ riskSummary.high }} 单</span>
      <span v-if="riskSummary.medium" style="color:#a16207">中风险 {{ riskSummary.medium }} 单</span>
      <span v-if="riskSummary.delayed" style="color:var(--text-secondary)">预计延期 {{ formatRiskMinutes(riskSummary.totalDelayMinutes) }}</span>
    </div>

    <div v-if="viewMode==='operations'" style="padding:16px 20px">
      <div style="display:flex;gap:8px;align-items:center;flex-wrap:wrap;margin-bottom:14px">
        <select v-model="capacityProcessFilter" class="form-input" style="width:150px;padding:6px 10px;font-size:var(--text-sm)">
          <option value="">全部工序</option>
          <option v-for="process in processOptions" :key="process.id" :value="String(process.id)">{{ process.name }}</option>
        </select>
        <select v-model="capacityNodeFilter" class="form-input" style="width:210px;padding:6px 10px;font-size:var(--text-sm)">
          <option value="">全部生产节点</option>
          <option v-for="node in capacityNodes" :key="node.id" :value="String(node.id)">{{ node.process_name }} · {{ node.node_code }} · {{ node.node_name }}</option>
        </select>
        <span style="font-size:var(--text-xs);color:var(--text-secondary)">共 {{ capacitySummary.total }} 道工序 · 已排 {{ capacitySummary.planned }} · 阻断 {{ capacitySummary.blocked }} · {{ Math.round(capacitySummary.minutes) }} 分钟</span>
        <div style="display:flex;gap:6px;align-items:center;margin-left:auto;flex-wrap:wrap">
          <select v-model="generationOrderId" @change="prepareGeneration(generationOrderId)" class="form-input" style="width:180px;padding:6px 10px;font-size:var(--text-sm)">
            <option value="">选择订单生成排程</option>
            <option v-for="order in capacityOrders" :key="order.id" :value="order.id">{{ order.order_no }}</option>
          </select>
          <input v-model="generationStartDate" type="date" class="form-input" style="width:145px;padding:6px 10px;font-size:var(--text-sm)">
          <button v-if="canGenerateSchedules" type="button" class="btn btn-sm" style="background:var(--primary);color:#fff" @click="generateSchedule">生成工序排程</button>
          <select v-model="replanOrderId" @change="prepareDynamicReplan(replanOrderId)" class="form-input" style="width:180px;padding:6px 10px;font-size:var(--text-sm)" title="依据已报工、返工和停机事实重排未完成工作">
            <option value="">选择订单动态重排</option>
            <option v-for="order in capacityOrders" :key="`replan-${order.id}`" :value="order.id">{{ order.order_no }}</option>
          </select>
          <input v-model="replanStartAt" type="datetime-local" class="form-input" style="width:175px;padding:6px 10px;font-size:var(--text-sm)" title="重排起点">
          <input v-model="replanReason" type="text" class="form-input" style="width:220px;padding:6px 10px;font-size:var(--text-sm)" placeholder="动态重排原因">
          <button v-if="canGenerateSchedules" type="button" class="btn btn-sm" style="background:var(--warning);color:#fff" @click="dynamicReplanSchedule">按实际进度重排</button>
          <button v-if="canGenerateSchedules" type="button" class="btn btn-sm" style="background:var(--teal);color:#fff" @click="prepareAutoPlan">⚡ 自动排程</button>
          <button type="button" class="btn-default btn-sm" @click="loadCapacity">刷新</button>
        </div>
      </div>
      <div v-if="autoPlanVisible" class="card" style="margin:0 0 14px;padding:12px 14px;border:1px solid var(--teal);background:var(--bg-surface)">
        <div style="display:flex;align-items:center;gap:8px;flex-wrap:wrap;margin-bottom:10px">
          <strong style="font-size:var(--text-sm)">⚡ 按优先级自动排程</strong>
          <span style="font-size:var(--text-xs);color:var(--text-secondary)">按 P1→P5、加急、交期和订单号排序；每次运行使用独立幂等键并保留运行台账</span>
          <button type="button" class="btn-default btn-sm" style="margin-left:auto" @click="autoPlanVisible=false">收起</button>
        </div>
        <form v-if="canGenerateSchedules" style="display:flex;gap:8px;align-items:center;flex-wrap:wrap" @submit.prevent="runAutoPlan">
          <label style="display:flex;align-items:center;gap:5px;font-size:var(--text-xs);color:var(--text-secondary)">开始日期
            <input v-model="autoPlanStartDate" type="date" class="form-input" style="width:145px;padding:6px 8px;font-size:var(--text-sm)" required>
          </label>
          <label style="display:flex;align-items:center;gap:5px;font-size:var(--text-xs);color:var(--text-secondary)">订单数
            <input v-model.number="autoPlanLimit" type="number" min="1" max="1000" class="form-input" style="width:90px;padding:6px 8px;font-size:var(--text-sm)" required>
          </label>
          <input v-model="autoPlanKey" type="text" maxlength="128" class="form-input" style="width:260px;padding:6px 10px;font-size:var(--text-sm)" placeholder="自动排程幂等键" required>
          <button type="submit" class="btn btn-sm" style="background:var(--teal);color:#fff" :disabled="autoPlanLoading">{{ autoPlanLoading ? '排程中…' : '运行自动排程' }}</button>
        </form>
        <div v-if="autoPlanResult" style="margin-top:10px;padding:8px 10px;background:var(--bg-hover);border-radius:var(--radius-sm);font-size:var(--text-xs)">
          <span>运行状态：<b>{{ autoPlanResult.status }}</b></span>
          <span style="margin-left:12px">队列 {{ autoPlanResult.queue_count || 0 }} 单</span>
          <span style="margin-left:12px">失败 {{ autoPlanResult.failed_count || 0 }} 单</span>
          <span v-if="autoPlanResult.idempotent_replay" style="margin-left:12px;color:var(--primary)">幂等重放</span>
        </div>
      </div>
      <div class="card" style="margin:0 0 14px;padding:12px 14px;border:1px solid var(--border-light);background:var(--bg-surface)">
        <div style="display:flex;align-items:center;gap:8px;flex-wrap:wrap;margin-bottom:10px">
          <strong style="font-size:var(--text-sm)">🛑 生产节点停机管理</strong>
          <span style="font-size:var(--text-xs);color:var(--text-secondary)">停机事实会参与动态重排；取消仅标记为已取消并保留审计记录</span>
          <button type="button" class="btn-default btn-sm" style="margin-left:auto" @click="loadDowntime">刷新停机记录</button>
        </div>
        <form v-if="canManageDowntime" style="display:flex;gap:8px;align-items:center;flex-wrap:wrap" @submit.prevent="createDowntime">
          <select v-model="downtimeForm.production_node_id" class="form-input" style="width:220px;padding:6px 10px;font-size:var(--text-sm)" aria-label="停机生产节点">
            <option value="">选择生产节点</option>
            <option v-for="node in capacityNodes" :key="`downtime-node-${node.id}`" :value="node.id">{{ node.process_name }} · {{ node.node_code }} · {{ node.node_name }}</option>
          </select>
          <label style="display:flex;align-items:center;gap:5px;font-size:var(--text-xs);color:var(--text-secondary)">开始
            <input v-model="downtimeForm.start_at" type="datetime-local" class="form-input" style="width:175px;padding:6px 8px;font-size:var(--text-sm)" required>
          </label>
          <label style="display:flex;align-items:center;gap:5px;font-size:var(--text-xs);color:var(--text-secondary)">结束
            <input v-model="downtimeForm.end_at" type="datetime-local" class="form-input" style="width:175px;padding:6px 8px;font-size:var(--text-sm)" required>
          </label>
          <input v-model="downtimeForm.reason" type="text" maxlength="512" class="form-input" style="width:220px;padding:6px 10px;font-size:var(--text-sm)" placeholder="停机原因（如设备检修）">
          <button type="submit" class="btn btn-sm" style="background:var(--danger);color:#fff">保存停机</button>
        </form>
        <div v-if="downtimeLoading" style="padding:12px 0 2px;font-size:var(--text-xs);color:var(--text-placeholder)">⏳ 加载停机记录中...</div>
        <div v-else-if="downtimeEvents.length" style="display:flex;flex-direction:column;gap:6px;margin-top:10px;max-height:190px;overflow-y:auto">
          <div v-for="event in downtimeEvents" :key="`downtime-${event.id}`" style="display:flex;align-items:center;gap:8px;padding:7px 9px;background:var(--bg-hover);border-radius:var(--radius-sm);font-size:var(--text-xs)">
            <span style="font-weight:600;min-width:180px">{{ event.process_name || '-' }} · {{ event.node_code || '' }} · {{ event.node_name || `生产节点 #${event.production_node_id}` }}</span>
            <span style="white-space:nowrap">{{ event.start_at }} ~ {{ event.end_at }}</span>
            <span style="color:var(--text-secondary);overflow:hidden;text-overflow:ellipsis;white-space:nowrap;flex:1" :title="event.reason || ''">{{ event.reason || '未填写原因' }}</span>
            <button v-if="canManageDowntime" type="button" class="btn-default btn-sm" style="padding:2px 8px;color:var(--danger);font-size:var(--text-xs)" @click="cancelDowntime(event)">取消</button>
          </div>
        </div>
        <div v-else style="padding:10px 0 2px;font-size:var(--text-xs);color:var(--text-placeholder)">暂无有效停机记录</div>
      </div>
      <div v-if="capacityLoading" style="padding:36px;text-align:center;color:var(--text-placeholder)">⏳ 加载工序排程中...</div>
      <div v-else-if="!filteredOperations.length" style="padding:36px;text-align:center;color:var(--text-placeholder)">暂无工序排程数据，请选择订单生成排程</div>
      <div v-else style="overflow:auto;border:1px solid var(--border-light)">
        <table style="width:100%;border-collapse:collapse;min-width:1540px;font-size:var(--text-sm)">
          <thead><tr style="background:var(--bg-hover);text-align:left">
            <th style="padding:9px 10px">订单</th><th style="padding:9px 10px">工序</th><th style="padding:9px 10px">生产节点</th><th style="padding:9px 10px">拆分明细</th><th style="padding:9px 10px">预计时间</th><th style="padding:9px 10px">数量</th><th style="padding:9px 10px">标准工时</th><th style="padding:9px 10px">来源</th><th style="padding:9px 10px">难度系数</th><th style="padding:9px 10px">占用分钟</th><th style="padding:9px 10px">交期风险</th><th style="padding:9px 10px">状态</th><th style="padding:9px 10px">操作</th>
          </tr></thead>
          <tbody><tr v-for="row in filteredOperations" :key="row.id || `${row.order_id}-${row.order_process_id}`" style="border-top:1px solid var(--bg-hover)">
            <td style="padding:8px 10px;font-weight:600;color:var(--primary)">{{ row.order_no || row.order_id }}</td>
            <td style="padding:8px 10px">{{ row.process_name || '-' }}</td>
            <td style="padding:8px 10px">{{ nodeLabel(row) }}</td>
            <td style="padding:8px 10px;min-width:180px">
              <div v-if="row.allocations && row.allocations.length" style="display:flex;flex-direction:column;gap:3px">
                <span v-for="allocation in row.allocations" :key="allocation.id || `${allocation.production_node_id}-${allocation.quantity}`" style="font-size:var(--text-xs)">{{ allocationLabel(allocation) }}</span>
              </div>
              <span v-else style="color:var(--text-placeholder)">未拆分</span>
            </td>
            <td style="padding:8px 10px;white-space:nowrap">{{ row.planned_start_at || row.plan_start || '-' }}<span v-if="row.planned_end_at"> ~ {{ row.planned_end_at }}</span><span v-else-if="row.plan_end"> ~ {{ row.plan_end }}</span></td>
            <td style="padding:8px 10px">{{ row.quantity || row.scheduled_quantity || 0 }}</td>
            <td style="padding:8px 10px">{{ row.standard_minutes_per_unit || 0 }} / 件</td>
            <td style="padding:8px 10px;white-space:nowrap">{{ standardScopeLabel(row.standard_match_scope) }}</td>
            <td style="padding:8px 10px">{{ row.difficulty_factor || 1 }}</td>
            <td style="padding:8px 10px">{{ Math.round(row.occupied_minutes || row.planned_minutes || 0) }}</td>
            <td style="padding:8px 10px;white-space:nowrap"><span :style="{color:riskColor(operationRiskLevel(row)),fontWeight:700}" :title="operationRisk(row).risk_reason || ''">{{ riskIcon(operationRiskLevel(row)) }} {{ riskLabel(operationRiskLevel(row)) }}</span><span v-if="Number(operationRisk(row).delay_minutes)>0" style="display:block;font-size:10px;color:var(--danger)">+{{ formatRiskMinutes(operationRisk(row).delay_minutes) }}</span></td>
            <td style="padding:8px 10px;min-width:180px">
              <span v-if="row.schedule_status==='blocked'||row.status==='blocked'" :data-test="`blocked-code-${blockedCode(row) || 'UNKNOWN'}`" style="color:var(--danger);font-weight:600">阻断：{{ blockedMessage(row) }}</span>
              <span v-else style="color:var(--success);font-weight:600">{{ row.revision_status || '已排程' }}</span>
              <span v-if="row.locked" data-test="locked-task" style="display:block;margin-top:3px;color:var(--warning);font-size:var(--text-xs)">🔒 已锁定</span>
            </td>
            <td style="padding:8px 10px;min-width:250px">
              <div style="display:flex;gap:4px;flex-wrap:wrap">
                <button v-if="canAdjustSchedules && row.revision_item_id" type="button" class="btn-default btn-sm" @click="prepareAdjustment(row)">调整</button>
                <button v-if="canLockSchedules && row.revision_item_id && !row.locked" type="button" class="btn-default btn-sm" @click="lockOperation(row)">锁定</button>
                <button v-if="canUnlockSchedules && row.revision_item_id && row.locked" type="button" class="btn-default btn-sm" @click="unlockOperation(row)">解锁</button>
                <button v-if="canSubmitSchedules && row.schedule_revision_id && (!row.revision_status || row.revision_status==='draft')" type="button" class="btn-default btn-sm" @click="submitRevision(row)">提交</button>
                <button v-if="canApproveSchedules && row.schedule_revision_id && row.revision_status==='pending_approval'" type="button" class="btn-default btn-sm" @click="approveRevision(row)">批准</button>
                <button v-if="canRejectSchedules && row.schedule_revision_id && row.revision_status==='pending_approval'" type="button" class="btn-default btn-sm" style="color:var(--danger)" @click="rejectRevision(row)">驳回</button>
                <button v-if="canPublishSchedules && row.schedule_revision_id && row.revision_status==='approved'" type="button" class="btn-default btn-sm" style="color:var(--success)" @click="publishRevision(row)">发布</button>
              </div>
            </td>
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
                <span :style="{flexShrink:0,fontSize:'10px',textAlign:'left',color:riskColor(order)}" :title="riskTooltip(order)">{{ riskIcon(order) }}</span>
                <span v-if="riskLevel(order)!=='none'" class="gantt-risk-badge" :style="{color:riskColor(order)}" :title="riskTooltip(order)">{{ riskLabel(order) }}</span>
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
                  boxShadow: riskBarShadow(order),zIndex:1,
                  transition: dragTarget===order ? 'none' : 'box-shadow 0.15s',
                  userSelect:'none'
                }"
                @mousedown="onBarMouseDown($event, order)"
                @dblclick="editOrderDates(order)"
                :title="order.plan_start + ' ~ ' + order.plan_end + ' | 产量: ' + (order.completed_qty||0) + '/' + (order.quantity||0) + (riskTooltip(order) ? ' | ' + riskTooltip(order) : '') + (isCompleted(order) ? ' | 已完成订单只读' : '')" >
                <span v-if="order.quantity" style="margin-right:4px">{{ order.completed_qty||0 }}/{{ order.quantity }}</span>
                {{ statusLabel(order.status) }}
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
        </div>
        <div class="modal-footer">
          <button class="btn btn-default" @click="undoLastDrag">取消</button>
          <button class="btn btn-primary" @click="saveEditDates">保存</button>
        </div>
      </div>
    </div>

    <!-- Production Node Modal -->
    <div v-if="showNodeMgr" class="modal-overlay" @click.self="showNodeMgr=false">
      <div class="modal" style="max-width:900px">
        <div class="modal-header"><h3>⚙️ 生产节点管理</h3></div>
        <div class="modal-body">
          <form v-if="canManageNodes" style="display:grid;grid-template-columns:repeat(4,minmax(140px,1fr));gap:8px;margin-bottom:16px" @submit.prevent="saveNode">
            <select v-model="nodeForm.process_id" class="form-input" :disabled="Boolean(nodeForm.id)" required>
              <option value="">选择工序</option>
              <option v-for="process in processOptions" :key="`node-process-${process.id}`" :value="process.id">{{ process.name }}</option>
            </select>
            <input v-model="nodeForm.node_code" class="form-input" placeholder="节点编码，如 WELD-01" required>
            <input v-model="nodeForm.node_name" class="form-input" placeholder="节点名称，如 焊接-01" required>
            <select v-model="nodeForm.capacity_mode" class="form-input">
              <option value="exclusive">独占容量</option>
              <option value="batch">批处理容量</option>
            </select>
            <select v-model="nodeForm.calendar_id" class="form-input" required>
              <option value="">选择工作日历</option>
              <option v-for="calendar in productionCalendars" :key="`calendar-${calendar.id}`" :value="calendar.id">{{ calendar.calendar_name || calendar.name || `日历 #${calendar.id}` }}</option>
            </select>
            <select v-model="nodeForm.status" class="form-input">
              <option value="active">启用</option>
              <option value="maintenance">维护中</option>
              <option value="inactive">停用</option>
            </select>
            <input v-model="nodeForm.reason" class="form-input" placeholder="变更原因（必填）" required>
            <input v-model="nodeForm.idempotency_key" class="form-input" placeholder="幂等键" required>
            <div style="grid-column:1/-1;display:flex;justify-content:flex-end;gap:8px">
              <button type="button" class="btn-default btn-sm" @click="resetNodeForm()">新建节点</button>
              <button type="submit" class="btn btn-primary btn-sm">{{ nodeForm.id ? '保存节点修改' : '创建生产节点' }}</button>
            </div>
          </form>
          <div v-if="nodesLoading" style="padding:20px;text-align:center;color:var(--text-placeholder)">加载生产节点中...</div>
          <div v-else-if="nodesByProcess.length" style="max-height:300px;overflow-y:auto;border:1px solid var(--border-light);border-radius:var(--radius-sm)">
            <section v-for="group in nodesByProcess" :key="`node-group-${group.process_id}`" style="padding:10px 12px;border-bottom:1px solid var(--border-light)">
              <strong>{{ group.process_name }}</strong>
              <div v-for="node in group.nodes" :key="node.id" style="display:flex;align-items:center;gap:8px;padding:7px 0;border-top:1px solid var(--bg-hover);font-size:var(--text-sm)">
                <span style="font-weight:700;min-width:90px">{{ node.node_code }}</span>
                <span style="min-width:120px">{{ node.node_name }}</span>
                <span style="color:var(--text-secondary)">{{ node.capacity_mode === 'batch' ? '批处理容量' : '独占容量' }}</span>
                <span style="color:var(--text-secondary)">日容量 {{ node.capacity_minutes || 0 }} 分钟</span>
                <span style="color:var(--text-secondary)">状态 {{ node.status }}</span>
                <button v-if="canManageNodes" type="button" class="btn-default btn-sm" style="margin-left:auto" @click="editNode(node)">编辑</button>
                <button v-if="canManageCapabilities" type="button" class="btn-default btn-sm" :style="{marginLeft:canManageNodes?'0':'auto'}" @click="loadCapabilities(node)">能力限制</button>
                <button v-if="canManageCalendars" type="button" class="btn-default btn-sm" @click="prepareOverride(node)">日历例外</button>
              </div>
            </section>
          </div>
          <div v-else style="padding:18px;text-align:center;color:var(--text-placeholder)">暂无生产节点</div>
          <form v-if="canManageCalendars" style="margin-top:16px;padding:12px;border:1px solid var(--border-light);border-radius:var(--radius-sm)" @submit.prevent="createCalendarOverride">
            <strong style="display:block;margin-bottom:8px">节点日历例外</strong>
            <div style="display:grid;grid-template-columns:repeat(3,minmax(150px,1fr));gap:8px">
              <select v-model="overrideForm.production_node_id" class="form-input" required>
                <option value="">选择生产节点</option>
                <option v-for="node in productionNodes" :key="`override-node-${node.id}`" :value="node.id">{{ node.process_name }} · {{ node.node_code }} · {{ node.node_name }}</option>
              </select>
              <input v-model="overrideForm.start_at" type="datetime-local" class="form-input" required>
              <input v-model="overrideForm.end_at" type="datetime-local" class="form-input" required>
              <select v-model="overrideForm.override_type" class="form-input">
                <option value="unavailable">不可用</option>
                <option value="maintenance">维护</option>
                <option value="overtime">加班</option>
                <option value="holiday">停工假日</option>
              </select>
              <input v-model="overrideForm.reason" class="form-input" placeholder="日历调整原因（必填）" required>
              <input v-model="overrideForm.idempotency_key" class="form-input" placeholder="幂等键" required>
              <button type="submit" class="btn btn-primary btn-sm" style="grid-column:3">保存日历例外</button>
            </div>
          </form>
          <form v-if="canManageCapabilities && capabilityForm.production_node_id" style="margin-top:16px;padding:12px;border:1px solid var(--border-light);border-radius:var(--radius-sm)" @submit.prevent="saveCapabilities">
            <div style="display:flex;align-items:center;gap:8px;margin-bottom:8px">
              <strong>节点能力限制：{{ capabilityForm.node_label }}</strong>
              <span style="font-size:var(--text-xs);color:var(--text-secondary)">空列表表示仅按所属工序匹配，不附加产品或版本限制</span>
              <button type="button" class="btn-default btn-sm" style="margin-left:auto" @click="addCapability">新增限制</button>
            </div>
            <div v-if="capabilitiesLoading" style="padding:12px;text-align:center;color:var(--text-placeholder)">加载能力配置中...</div>
            <div v-for="(capability, index) in capabilityForm.capabilities" :key="`capability-${index}`" style="display:grid;grid-template-columns:repeat(5,minmax(120px,1fr));gap:6px;padding:8px 0;border-top:1px solid var(--bg-hover)">
              <input v-model.number="capability.product_id" type="number" min="1" class="form-input" placeholder="产品 ID（可空）">
              <input v-model="capability.product_family" class="form-input" placeholder="产品族（可空）">
              <input v-model="capability.material_code" class="form-input" placeholder="材料编码（可空）">
              <input v-model="capability.specification" class="form-input" placeholder="规格（可空）">
              <input v-model.number="capability.route_version_id" type="number" min="1" class="form-input" placeholder="路线版本 ID">
              <input v-model.number="capability.process_version_id" type="number" min="1" class="form-input" placeholder="工序版本 ID">
              <input v-model.number="capability.max_batch_quantity" type="number" min="1" class="form-input" placeholder="最大批量">
              <input v-model.number="capability.batch_minutes" type="number" min="0.01" step="0.01" class="form-input" placeholder="批次分钟">
              <input v-model.number="capability.changeover_minutes" type="number" min="0" step="0.01" class="form-input" placeholder="换型分钟">
              <div style="display:flex;align-items:center;gap:8px">
                <label style="font-size:var(--text-xs)"><input v-model="capability.allow_mixed_orders" type="checkbox"> 允许混单</label>
                <select v-model="capability.status" class="form-input" style="width:90px"><option value="active">启用</option><option value="inactive">停用</option></select>
                <button type="button" class="btn-default btn-sm" style="color:var(--danger)" @click="removeCapability(index)">移除</button>
              </div>
            </div>
            <div style="display:grid;grid-template-columns:2fr 2fr auto;gap:8px;margin-top:8px">
              <input v-model="capabilityForm.reason" class="form-input" placeholder="能力变更原因（必填）" required>
              <input v-model="capabilityForm.idempotency_key" class="form-input" placeholder="幂等键" required>
              <button type="submit" class="btn btn-primary btn-sm">保存能力配置</button>
            </div>
          </form>
        </div>
        <div class="modal-footer"><button class="btn btn-default" @click="showNodeMgr=false">关闭</button></div>
      </div>
    </div>

    <!-- Schedule Adjustment Modal -->
    <div v-if="showAdjustmentModal" class="modal-overlay" @click.self="showAdjustmentModal=false">
      <div class="modal" style="max-width:520px">
        <div class="modal-header"><h3>✏️ 调整生产节点排程</h3></div>
        <form @submit.prevent="saveOperationAdjustment">
          <div class="modal-body">
            <div class="form-group"><label>生产节点</label>
              <select v-model="adjustmentForm.production_node_id" class="form-input" required>
                <option value="">选择生产节点</option>
                <option v-for="node in capacityNodes" :key="`adjust-node-${node.id}`" :value="node.id">{{ node.process_name }} · {{ node.node_code }} · {{ node.node_name }}</option>
              </select>
            </div>
            <div class="form-group"><label>计划开始时间</label><input v-model="adjustmentForm.planned_start_at" type="datetime-local" class="form-input" required></div>
            <div class="form-group"><label>调整原因</label><input v-model="adjustmentForm.reason" class="form-input" required></div>
            <div class="form-group"><label>幂等键</label><input v-model="adjustmentForm.idempotency_key" class="form-input" required></div>
          </div>
          <div class="modal-footer">
            <button type="button" class="btn btn-default" @click="showAdjustmentModal=false">取消</button>
            <button type="submit" class="btn btn-primary">生成新草稿修订版</button>
          </div>
        </form>
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
