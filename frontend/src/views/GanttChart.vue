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
        <select v-if="viewMode==='orders'" v-model="riskFilter" class="form-input" style="width:150px;padding:5px 9px;font-size:var(--text-xs)" aria-label="交期风险筛选">
          <option value="all">全部风险</option>
          <option value="critical">逾期 / 高风险</option>
          <option value="medium">中风险</option>
          <option value="low">低风险</option>
          <option value="conflict">存在节点冲突</option>
          <option value="blocked">存在排程阻断</option>
        </select>
        <button v-if="canViewNodes" class="btn btn-sm" style="background:var(--teal);color:#fff" @click="showNodeMgr=true">⚙️ 生产节点管理</button>
        <button @click="zoomOut" title="缩小" class="btn-default btn-sm">−</button>
        <button @click="zoomIn" title="放大" class="btn-default btn-sm">+</button>
        <button class="btn btn-sm" style="background:var(--success);color:#fff" @click="exportImage" title="导出PNG">📥 导出</button>
        <button class="btn-default btn-sm" @click="exportScheduleCsv(viewMode==='operations' ? filteredOperations : filteredOrders, viewMode==='operations' ? 'operations' : 'orders')" title="导出当前筛选结果 CSV">CSV</button>
        <span class="schedule-plan-actual-legend" title="甘特图同时显示计划和实际报工时间"><i class="plan"></i>计划 <i class="actual"></i>实际</span>
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

    <section v-if="viewMode==='orders'" class="schedule-filter-workbench" data-test="schedule-filter-workbench" aria-label="排程筛选">
      <div class="schedule-filter-workbench__row">
        <label>订单号 <input v-model="orderKeyword" class="form-input" type="search" placeholder="订单号或 ID" aria-label="订单号筛选"></label>
        <label>产品 <input v-model="productKeyword" class="form-input" type="search" placeholder="产品编码/名称" aria-label="产品筛选"></label>
        <label>优先级
          <select v-model="priorityFilter" class="form-input" aria-label="优先级筛选">
            <option value="all">全部优先级</option><option value="1">P1</option><option value="2">P2</option><option value="3">P3</option><option value="4">P4</option><option value="5">P5</option>
          </select>
        </label>
        <label>状态
          <select v-model="statusFilter" class="form-input" aria-label="订单状态筛选">
            <option value="all">全部状态</option><option value="pending">待生产</option><option value="producing">生产中</option><option value="completed">已完成</option>
          </select>
        </label>
        <label>风险
          <select v-model="riskFilter" class="form-input" aria-label="交期风险筛选">
            <option value="all">全部风险</option><option value="critical">逾期 / 高风险</option><option value="medium">中风险</option><option value="low">低风险</option><option value="conflict">节点冲突</option><option value="blocked">排程阻断</option>
          </select>
        </label>
        <label>锁定
          <select v-model="lockedFilter" class="form-input" aria-label="锁定状态筛选">
            <option value="all">全部任务</option><option value="locked">含锁定任务</option><option value="unlocked">未锁定任务</option>
          </select>
        </label>
      </div>
      <div class="schedule-filter-workbench__row schedule-filter-workbench__row--secondary">
        <label>交期从 <input v-model="deadlineFrom" class="form-input" type="date" aria-label="交期起始筛选"></label>
        <label>交期至 <input v-model="deadlineTo" class="form-input" type="date" aria-label="交期结束筛选"></label>
        <button type="button" class="btn-default btn-sm" @click="resetFilters">清空筛选</button>
        <span class="schedule-filter-workbench__count">当前显示 {{ filteredOrders.length }} / {{ orders.length }} 单</span>
        <span class="schedule-filter-workbench__divider"></span>
        <select v-model="activeSavedFilter" class="form-input" aria-label="已保存筛选" @change="applySavedFilterFromUi">
          <option value="">选择已保存筛选</option>
          <option v-for="item in savedFilters" :key="item.name" :value="item.name">{{ item.name }}</option>
        </select>
        <input v-model="savedFilterName" class="form-input" type="text" maxlength="40" placeholder="保存为…" aria-label="保存筛选名称" @keyup.enter="saveCurrentFilter">
        <button type="button" class="btn-default btn-sm" :disabled="!savedFilterName.trim()" @click="saveCurrentFilter">保存筛选</button>
        <button v-if="activeSavedFilter" type="button" class="btn-default btn-sm" title="删除当前保存的筛选" @click="removeSavedFilter">删除方案</button>
      </div>
    </section>

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
        <select v-model="capacityOrderFilter" class="form-input" style="width:170px;padding:6px 10px;font-size:var(--text-sm)">
          <option value="">全部订单</option>
          <option v-for="order in capacityOrders" :key="`capacity-order-${order.id}`" :value="String(order.id)">{{ order.order_no }}</option>
        </select>
        <select v-model="capacityRiskFilter" class="form-input" style="width:150px;padding:6px 10px;font-size:var(--text-sm)" aria-label="工序冲突风险筛选">
          <option value="all">全部状态</option>
          <option value="conflict">存在节点冲突</option>
          <option value="blocked">存在排程阻断</option>
          <option value="critical">逾期 / 高风险</option>
        </select>
        <span style="font-size:var(--text-xs);color:var(--text-secondary)">共 {{ capacitySummary.total }} 道工序 · 已排 {{ capacitySummary.planned }} · 阻断 {{ capacitySummary.blocked }} · 冲突 {{ capacitySummary.conflicts || 0 }} · {{ Math.round(capacitySummary.minutes) }} 分钟</span>
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
      <ScheduleCapacityDashboard
        :operations="operationSchedules"
        :nodes="capacityNodes"
        :orders="capacityOrders"
        :audit="conflictAudit"
        :downtime="downtimeEvents"
        @filter-node="capacityNodeFilter=String($event)"
        @filter-order="capacityOrderFilter=String($event)"
        @open-order="openOrderDrawer"
        @refresh="loadCapacity"
      />
      <div v-if="selectedReplanOrder?.schedule_replan_required && !replanResult" data-test="pending-replan-reason" style="margin:-6px 0 14px;padding:8px 10px;background:#fff7ed;border:1px solid #fed7aa;border-radius:var(--radius-sm);font-size:var(--text-xs);color:#9a3412">
        <b>{{ selectedReplanOrder.order_no }} 待重排：</b>{{ selectedReplanOrder.schedule_replan_reason || '生产事实发生变化' }}
      </div>
      <div v-if="replanResult" data-test="dynamic-replan-evidence" class="card" style="margin:0 0 14px;padding:12px 14px;border:1px solid #fde68a;background:#fffbeb">
        <div style="display:flex;gap:10px;align-items:center;flex-wrap:wrap">
          <strong style="color:#92400e">🔄 动态重排已生成草稿</strong>
          <span style="font-size:var(--text-xs);color:var(--text-secondary)">正式排程与报工事实未改变，必须审批并发布后才生效</span>
          <span v-if="replanResult.replan_summary" style="margin-left:auto;font-size:var(--text-xs)">变化 <b>{{ replanResult.replan_summary.changed_operation_count || 0 }}</b> 道 · 换节点 <b>{{ replanResult.replan_summary.node_change_count || 0 }}</b> 道 · 风险 <b>{{ replanResult.replan_summary.risk_change || 'unchanged' }}</b></span>
        </div>
        <div v-if="replanResult.replan_summary?.trigger_reasons?.length" style="margin-top:8px;font-size:var(--text-xs);color:#78350f">
          <b>为什么需要重排：</b>{{ replanResult.replan_summary.trigger_reasons.join('；') }}
        </div>
        <div v-if="replanResult.differences?.length" style="display:grid;grid-template-columns:repeat(auto-fit,minmax(260px,1fr));gap:6px;margin-top:8px">
          <div v-for="difference in replanResult.differences.filter(item => item.change_type !== 'unchanged').slice(0,8)" :key="`replan-diff-${difference.order_process_id}`" style="padding:7px 9px;background:#fff;border:1px solid #fef3c7;border-radius:var(--radius-sm);font-size:var(--text-xs)">
            <b>{{ difference.after?.process_id || difference.before?.process_id ? `订单工序 #${difference.order_process_id}` : '工序变化' }}</b>
            <span style="display:block;margin-top:2px">类型 {{ difference.change_type }} · 数量 {{ Number(difference.quantity_delta || 0) >= 0 ? '+' : '' }}{{ difference.quantity_delta || 0 }} · 占用 {{ Number(difference.occupied_minutes_delta || 0) >= 0 ? '+' : '' }}{{ Math.round(difference.occupied_minutes_delta || 0) }} 分钟</span>
            <span v-if="difference.node_changed" style="display:block;color:#b45309">生产节点已变更</span>
            <span v-if="difference.end_delta_minutes" :style="{display:'block',color:Number(difference.end_delta_minutes)>0?'var(--danger)':'var(--success)'}">预计结束 {{ Number(difference.end_delta_minutes)>0?'延后':'提前' }} {{ Math.abs(difference.end_delta_minutes) }} 分钟</span>
          </div>
        </div>
      </div>
      <div v-if="Number(conflictAudit.line_conflicts || 0)" class="card" data-test="schedule-conflict-workbench" style="margin:0 0 14px;padding:12px 14px;border:1px solid #fecaca;background:#fff7f7">
        <div style="display:flex;gap:10px;align-items:center;flex-wrap:wrap;margin-bottom:8px">
          <strong style="color:var(--danger)">⛔ 生产节点冲突 {{ conflictAudit.line_conflicts }} 处</strong>
          <span style="font-size:var(--text-xs);color:var(--text-secondary)">发布前必须完成换节点、错峰或停机避让；冲突版本将被门禁阻断</span>
          <button type="button" class="btn-default btn-sm" style="margin-left:auto" @click="capacityRiskFilter='conflict'">只看冲突工序</button>
        </div>
        <div style="display:grid;grid-template-columns:repeat(auto-fit,minmax(300px,1fr));gap:6px">
          <div v-for="(conflict,index) in (conflictAudit.conflicts || []).slice(0,6)" :key="`conflict-${index}`" style="padding:8px 10px;background:#fff;border-radius:var(--radius-sm);font-size:var(--text-xs);border:1px solid #fee2e2">
            <b>{{ conflict.node_name || `生产资源 #${conflict.resource_id || '-'}` }}</b>
            <span style="display:block;margin-top:3px">{{ conflict.first_start_at }} ~ {{ conflict.first_end_at }}</span>
            <span style="display:block;color:var(--danger)">与 {{ conflict.second_start_at }} ~ {{ conflict.second_end_at }} 重叠 {{ conflict.overlap_minutes || 0 }} 分钟</span>
            <span v-if="conflict.locked" style="display:block;color:#a16207">涉及已锁定任务，需授权复核</span>
          </div>
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
            <th style="padding:9px 10px">订单</th><th style="padding:9px 10px">工序</th><th style="padding:9px 10px">生产节点</th><th style="padding:9px 10px">拆分明细</th><th style="padding:9px 10px">计划时间</th><th style="padding:9px 10px">实际时间</th><th style="padding:9px 10px">数量</th><th style="padding:9px 10px">标准工时</th><th style="padding:9px 10px">来源</th><th style="padding:9px 10px">难度系数</th><th style="padding:9px 10px">占用分钟</th><th style="padding:9px 10px">交期风险</th><th style="padding:9px 10px">状态</th><th style="padding:9px 10px">操作</th>
          </tr></thead>
          <tbody><tr v-for="row in filteredOperations" :key="row.id || `${row.order_id}-${row.order_process_id}`" style="border-top:1px solid var(--bg-hover)">
            <td style="padding:8px 10px;font-weight:600;color:var(--primary)">{{ row.order_no || row.order_id }}</td>
            <td style="padding:8px 10px">{{ row.process_name || '-' }}</td>
            <td style="padding:8px 10px">{{ nodeLabel(row) }}</td>
            <td style="padding:8px 10px;min-width:180px">
              <div v-if="(row.segments && row.segments.length) || (row.allocations && row.allocations.length)" style="display:flex;flex-direction:column;gap:3px">
                <span v-for="segment in operationSegments(row)" :key="segment.key" style="font-size:var(--text-xs)">{{ [segment.node_code, segment.node_name].filter(Boolean).join(' · ') || `生产节点 #${segment.production_node_id || '-'}` }} × {{ segment.quantity || 0 }} · {{ segment.planned_start_at || '-' }} ~ {{ segment.planned_end_at || '-' }}</span>
              </div>
              <span v-else style="color:var(--text-placeholder)">未拆分</span>
            </td>
            <td style="padding:8px 10px;white-space:nowrap">{{ row.planned_start_at || row.plan_start || '-' }}<span v-if="row.planned_end_at"> ~ {{ row.planned_end_at }}</span><span v-else-if="row.plan_end"> ~ {{ row.plan_end }}</span></td>
            <td style="padding:8px 10px;white-space:nowrap"><span v-if="row.actual_start_at || row.actual_start">{{ row.actual_start_at || row.actual_start }}</span><span v-if="row.actual_end_at || row.actual_end"> ~ {{ row.actual_end_at || row.actual_end }}（完成）</span><span v-else-if="row.actual_last_report_at"> ~ {{ row.actual_last_report_at }}（最近报工）</span><span v-if="!row.actual_start_at && !row.actual_start && !row.actual_last_report_at && !row.actual_end_at && !row.actual_end" style="color:var(--text-placeholder)">未报工</span></td>
            <td style="padding:8px 10px">{{ row.quantity || row.scheduled_quantity || 0 }}</td>
            <td style="padding:8px 10px">{{ row.standard_minutes_per_unit || 0 }} / 件</td>
            <td style="padding:8px 10px;white-space:nowrap">{{ standardScopeLabel(row.standard_match_scope) }}</td>
            <td style="padding:8px 10px">{{ row.difficulty_factor || 1 }}</td>
            <td style="padding:8px 10px">{{ Math.round(row.occupied_minutes || row.planned_minutes || 0) }}</td>
            <td style="padding:8px 10px;white-space:nowrap"><span :style="{color:riskColor(operationRiskLevel(row)),fontWeight:700}" :title="operationRisk(row).risk_reason || ''">{{ riskIcon(operationRiskLevel(row)) }} {{ riskLabel(operationRiskLevel(row)) }}</span><span v-if="Number(operationRisk(row).delay_minutes)>0" style="display:block;font-size:10px;color:var(--danger)">+{{ formatRiskMinutes(operationRisk(row).delay_minutes) }}</span><span v-if="Number(row.conflict_count)>0" data-test="operation-conflict-badge" style="display:block;font-size:10px;color:var(--danger)" :title="row.conflict_reason || ''">⛔ 节点冲突 {{ row.conflict_count }} 处</span></td>
            <td style="padding:8px 10px;min-width:180px">
              <span v-if="row.schedule_status==='blocked'||row.status==='blocked'" :data-test="`blocked-code-${blockedCode(row) || 'UNKNOWN'}`" style="color:var(--danger);font-weight:600">阻断：{{ blockedMessage(row) }}</span>
              <span v-else style="color:var(--success);font-weight:600">{{ revisionStatusLabel(row) }}</span>
              <span v-if="row.locked" data-test="locked-task" style="display:block;margin-top:3px;color:var(--warning);font-size:var(--text-xs)">🔒 已锁定</span>
            </td>
            <td style="padding:8px 10px;min-width:250px">
              <div style="display:flex;gap:4px;flex-wrap:wrap">
                <button v-if="canAdjustSchedules && row.revision_item_id" type="button" class="btn-default btn-sm" @click="prepareAdjustment(row)">调整</button>
                <button v-if="canLockSchedules && row.revision_item_id && !row.locked" type="button" class="btn-default btn-sm" @click="lockOperation(row)">锁定</button>
                <button v-if="canUnlockSchedules && row.revision_item_id && row.locked" type="button" class="btn-default btn-sm" @click="unlockOperation(row)">解锁</button>
                <button v-if="canSubmitSchedules && row.schedule_revision_id && ['draft','rejected'].includes(revisionState(row))" type="button" class="btn-default btn-sm" @click="submitRevision(row)">提交</button>
                <button v-if="canApproveSchedules && row.schedule_revision_id && revisionState(row)==='pending_approval'" type="button" class="btn-default btn-sm" @click="approveRevision(row)">批准</button>
                <button v-if="canRejectSchedules && row.schedule_revision_id && revisionState(row)==='pending_approval'" type="button" class="btn-default btn-sm" style="color:var(--danger)" @click="rejectRevision(row)">驳回</button>
                <button v-if="canPublishSchedules && row.schedule_revision_id && revisionState(row)==='approved'" type="button" class="btn-default btn-sm" style="color:var(--success)" @click="publishRevision(row)">发布</button>
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
          <div style="display:flex;min-height:60px;align-items:stretch">
            <!-- Order Info Card -->
            <div style="min-width:360px;max-width:360px;padding:6px 14px;border-right:1px solid var(--border-light);display:flex;flex-direction:column;justify-content:center;gap:4px">
              <!-- 第一行：复选框 + 订单号 + 客户 + 状态 + 交期 -->
              <div style="display:flex;align-items:center;gap:10px">
                <input v-if="canEdit" type="checkbox" :checked="selectedOrderIds.includes(order.id)" :disabled="isCompleted(order)" @change="toggleOrder(order)" style="width:18px;flex-shrink:0" :title="isCompleted(order) ? '已完成订单只读，不参与批量调整' : ''"><span v-else style="width:18px;flex-shrink:0"></span>
              <button type="button" class="gantt-order-link" :title="`打开 ${order.order_no} 详情`" @click.stop="openOrderDrawer(order)">{{ order.order_no }}</button>
                <span style="flex-shrink:0;font-size:var(--text-xs);color:var(--text-secondary);white-space:nowrap;overflow:hidden;text-overflow:ellipsis;width:80px;text-align:left" :title="order.customer_name||''">{{ order.customer_name || '-' }}</span>
                <span :style="{flexShrink:0,fontSize:'12px',padding:'1px 6px',borderRadius:'3px',textAlign:'left',minWidth:'56px',background:order.status==='producing'?'var(--primary-light)':order.status==='completed'?'var(--success-light)':'var(--bg-hover)',color:order.status==='producing'?'var(--primary)':order.status==='completed'?'var(--success)':'var(--text-placeholder)'}">{{ statusLabel(order.status) }}</span>
                <span :style="{flexShrink:0,fontSize:'10px',textAlign:'left',color:riskColor(order)}" :title="riskTooltip(order)">{{ riskIcon(order) }}</span>
                <span v-if="riskLevel(order)!=='none'" class="gantt-risk-badge" :style="{color:riskColor(order)}" :title="riskTooltip(order)">{{ riskLabel(order) }}</span>
                <span style="flex-shrink:0;font-size:9px;color:var(--text-placeholder);width:50px;text-align:left" :title="order.deadline||''">{{ order.deadline ? order.deadline.slice(5) : '-' }}</span>
              </div>
              <!-- 第二行：产品编码 + 进度条 -->
              <div style="display:flex;align-items:center;gap:10px">
                <span style="font-size:9px;color:var(--text-secondary);font-weight:400;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;flex:1" :title="order.product_code||order.product_name||''">{{ order.product_code || order.product_name || '-' }}</span>
                <span v-if="order.actual_start_at || order.actual_start || order.actual_last_report_at || order.actual_end_at || order.actual_end" style="font-size:9px;color:var(--text-secondary);white-space:nowrap" :title="`实际：${order.actual_start_at || order.actual_start || '-'} ~ ${order.actual_end_at || order.actual_end || order.actual_last_report_at || '-'}`">实际 {{ order.actual_end_at || order.actual_end ? '已完成' : '进行中' }}</span>
                <span style="flex-shrink:0;display:flex;align-items:center;gap:4px;min-width:60px">
                  <span style="display:inline-block;width:40px;height:4px;background:var(--bg-hover);border-radius:2px">
                    <span :style="{display:'inline-block',height:'100%',borderRadius:'2px',background:order.progress>=100?'var(--success)':order.progress>=60?'var(--primary)':order.progress>=30?'var(--warning)':'var(--danger)',width:Math.min(order.progress,100)+'%'}"></span>
                  </span>
                  <span style="font-size:9px;color:var(--text-placeholder);min-width:24px;text-align:right">{{ order.completed_qty||0 }}/{{ order.quantity||0 }}</span>
                </span>
              </div>
            </div>
            <!-- Gantt Bar Area -->
            <div :style="{flex:1,position:'relative',minHeight:'60px'}">
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
                @click.stop="openOrderDrawer(order)"
                @dblclick="editOrderDates(order)"
                :title="order.plan_start + ' ~ ' + order.plan_end + ' | 产量: ' + (order.completed_qty||0) + '/' + (order.quantity||0) + (riskTooltip(order) ? ' | ' + riskTooltip(order) : '') + (isCompleted(order) ? ' | 已完成订单只读' : '')" >
                <span v-if="order.quantity" style="margin-right:4px">{{ order.completed_qty||0 }}/{{ order.quantity }}</span>
                {{ statusLabel(order.status) }}
              </div>
              <div v-if="dragTarget===order"
                :style="{position:'absolute',left:dragPreviewLeft+'px',top:'12px',width:dragPreviewWidth+'px',height:'28px',background:'rgba(37,99,235,0.3)',border:'2px dashed #2563eb',borderRadius:'6px',zIndex:3,pointerEvents:'none'}">
              </div>
              <div v-if="order.actual_start_at || order.actual_start" class="gantt-actual-bar" :style="{left:actualBarLeft(order)+'px',width:actualBarWidth(order)+'px'}" :title="`实际：${order.actual_start_at || order.actual_start} ~ ${order.actual_end_at || order.actual_end || order.actual_last_report_at || '进行中'}`"></div>
            </div>
          </div>
        </div>
      </div>
    </div>

    <ScheduleCommandDrawer
      :open="showEditModal"
      mode="edit"
      :form="editForm"
      :nodes="capacityNodes"
      @close="undoLastDrag"
      @save="saveEditDates"
    />

    <ProductionNodeWorkbench
      v-model="showNodeMgr"
      :manager="productionNodeManager"
      :process-options="processOptions"
      @closed="loadCapacity"
    />

    <ScheduleCommandDrawer
      :open="showAdjustmentModal"
      mode="adjust"
      :form="adjustmentForm"
      :nodes="capacityNodes"
      @close="showAdjustmentModal=false"
      @save="saveOperationAdjustment"
    />

    <OrderScheduleDrawer
      :open="orderDrawerOpen"
      :order="selectedScheduleOrder"
      :operations="selectedOrderOperations"
      :revisions="selectedOrderRevisions"
      :loading="orderDrawerLoading"
      :error="orderDrawerError"
      :can-adjust-priority="canAdjustSchedules"
      @close="closeOrderDrawer"
      @retry="openOrderDrawer(selectedScheduleOrder)"
      @action="handleOrderDrawerAction"
    />

    <SchedulePriorityDrawer
      :open="priorityDrawerOpen"
      :order="priorityOrder"
      :saving="prioritySaving"
      @close="priorityDrawerOpen=false"
      @save="savePriorityChange"
    />
  </div>
</div>
</template>

<script>
import { ref } from 'vue'
import ProductionNodeWorkbench from '@/components/production-nodes/ProductionNodeWorkbench.vue'
import ScheduleCapacityDashboard from '@/components/schedule/ScheduleCapacityDashboard.vue'
import OrderScheduleDrawer from '@/components/schedule/OrderScheduleDrawer.vue'
import ScheduleCommandDrawer from '@/components/schedule/ScheduleCommandDrawer.vue'
import SchedulePriorityDrawer from '@/components/schedule/SchedulePriorityDrawer.vue'
import { useGantt } from '@/composables/useGantt.js'
import { api } from '@/lib/api.js'
import { showToast } from '@/lib/store.js'

export default {
  components: { ProductionNodeWorkbench, ScheduleCapacityDashboard, OrderScheduleDrawer, ScheduleCommandDrawer, SchedulePriorityDrawer },
  setup() {
    const gantt = useGantt()
    const savedFilterName = ref('')
    const activeSavedFilter = ref('')
    const priorityDrawerOpen = ref(false)
    const priorityOrder = ref(null)
    const prioritySaving = ref(false)
    function saveCurrentFilter() {
      if (gantt.saveFilter?.(savedFilterName.value)) {
        activeSavedFilter.value = savedFilterName.value.trim()
        savedFilterName.value = ''
      }
    }
    function applySavedFilterFromUi() {
      if (activeSavedFilter.value) gantt.applySavedFilter?.(activeSavedFilter.value)
    }
    function removeSavedFilter() {
      if (!activeSavedFilter.value) return
      gantt.deleteSavedFilter?.(activeSavedFilter.value)
      activeSavedFilter.value = ''
    }
    function handleOrderDrawerAction(event) {
      if (event?.action === 'replan' && event.order?.id) {
        gantt.replanOrderId.value = event.order.id
        gantt.prepareDynamicReplan(event.order.id)
      }
      if (event?.action === 'operation') gantt.viewMode.value = 'operations'
      if (event?.action === 'priority' && event.order?.id) {
        priorityOrder.value = event.order
        gantt.closeOrderDrawer?.()
        priorityDrawerOpen.value = true
      }
    }
    async function savePriorityChange(payload) {
      if (!priorityOrder.value?.id || prioritySaving.value) return
      prioritySaving.value = true
      try {
        await api.domains.production.updateScheduleOrderPriority(priorityOrder.value.id, {
          ...payload,
          expected_priority_version: Number(priorityOrder.value.priority_version || 1),
        })
        priorityDrawerOpen.value = false
        showToast('订单优先级已更新，已标记为待重新排程')
        await Promise.all([gantt.load(), gantt.loadCapacity?.()])
      } catch (error) {
        showToast(error.message || '调整优先级失败', 'error')
      } finally {
        prioritySaving.value = false
      }
    }
    return { ...gantt, handleOrderDrawerAction, savePriorityChange, priorityDrawerOpen, priorityOrder, prioritySaving, savedFilterName, activeSavedFilter, saveCurrentFilter, applySavedFilterFromUi, removeSavedFilter }
  }
}
</script>

<style scoped>
.gantt-order-link { width:85px; flex-shrink:0; overflow:hidden; border:0; padding:0; background:transparent; color:var(--primary); font-size:var(--text-sm); font-weight:600; text-align:left; text-overflow:ellipsis; white-space:nowrap; cursor:pointer; }
.gantt-order-link:hover { text-decoration:underline; }
.schedule-filter-workbench { display:grid; gap:8px; padding:10px 20px; border-bottom:1px solid var(--border-light); background:var(--bg-surface); }
.schedule-filter-workbench__row { display:flex; align-items:end; gap:8px; flex-wrap:wrap; }
.schedule-filter-workbench__row label { display:flex; flex-direction:column; gap:4px; color:var(--text-secondary); font-size:var(--text-xs); }
.schedule-filter-workbench__row .form-input { min-width:116px; padding:5px 8px; font-size:var(--text-xs); }
.schedule-filter-workbench__row label:first-child .form-input { min-width:150px; }
.schedule-filter-workbench__row--secondary { align-items:center; }
.schedule-filter-workbench__count { color:var(--text-secondary); font-size:var(--text-xs); }
.schedule-filter-workbench__divider { width:1px; height:22px; background:var(--border-light); }
.schedule-plan-actual-legend { display:inline-flex; align-items:center; gap:4px; color:var(--text-secondary); font-size:10px; white-space:nowrap; }
.schedule-plan-actual-legend i { display:inline-block; width:12px; height:5px; border-radius:3px; }
.schedule-plan-actual-legend i.plan { background:#2563eb; }
.schedule-plan-actual-legend i.actual { background:#0f766e; }
.gantt-actual-bar { position:absolute; top:45px; z-index:2; height:7px; min-width:4px; border-radius:4px; background:#0f766e; box-shadow:0 1px 2px rgb(15 118 110 / 30%); pointer-events:none; }
@media (max-width: 700px) {
  .schedule-filter-workbench { padding:10px 12px; }
  .schedule-filter-workbench__row > label { flex:1 1 135px; }
  .schedule-filter-workbench__row .form-input { width:100%; min-width:0; }
  .schedule-filter-workbench__divider { display:none; }
}
</style>
