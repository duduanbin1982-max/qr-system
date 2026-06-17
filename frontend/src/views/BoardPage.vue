<!-- BoardPage.vue -->
<template>
<div class="board-container">
    <!-- Header -->
    <div class="board-header-v2">
      <div class="board-title-v2">📊 生产进度看板</div>
      <div class="board-cat">
        <button class="board-cat-btn" :class="{active: boardCategory===''}" @click="switchCategory('')">📋 全部</button>
        <button class="board-cat-btn" :class="{active: boardCategory==='结构件'}" @click="switchCategory('结构件')">🔩 结构件</button>
        <button class="board-cat-btn" :class="{active: boardCategory==='机加工'}" @click="switchCategory('机加工')">⚙️ 机加工</button>
      </div>
      <div class="board-time-v2">{{ currentTime }}</div>
    </div>

    <!-- Overdue Alert -->
    <div v-if="overdueOrders.length > 0" class="overdue-alert">
      <span>🚨</span>
      <span>有 <strong style="color:#ff6b6b;font-size:var(--text-xl)">{{ overdueOrders.length }}</strong> 个订单已超期！</span>
      <span style="color:rgba(255,255,255,0.5);font-size:var(--text-sm)">（最迟{{ overdueOrders[0] && overdueOrders[0].plan_end || '--' }}，已超{{ overdueOrders[0] && overdueOrders[0].overdue_days || 0 }}天）</span>
    </div>

    <!-- Stats Bar -->
    <div class="stats-bar">
      <div class="stat-card"><div class="stat-val blue">{{ stats.total_orders || 0 }}</div><div class="stat-label">总订单</div></div>
      <div class="stat-card"><div class="stat-val orange">{{ stats.producing_orders || 0 }}</div><div class="stat-label">生产中</div></div>
      <div class="stat-card"><div class="stat-val green">{{ stats.completed_orders || 0 }}</div><div class="stat-label">已完成</div></div>
      <div class="stat-card"><div class="stat-val purple">{{ today.today_output || 0 }}</div><div class="stat-label">今日产量</div></div>
      <div class="stat-card"><div class="stat-val yellow">{{ today.today_reports || 0 }}</div><div class="stat-label">今日报工</div></div>
      <div class="stat-card"><div class="stat-val pink">{{ today.today_rework || 0 }}</div><div class="stat-label">今日返工</div></div>
      <div class="stat-card"><div class="stat-val red">{{ today.today_scrap || 0 }}</div><div class="stat-label">今日报废</div></div>
    </div>

    <!-- Process Efficiency Summary -->
    <div class="board-charts-row">
      <div class="panel panel-chart">
        <div class="panel-title">📈 今日工序效率</div>
        <div class="panel-body" style="min-height:200px">
          <div v-if="processStats.length > 0" style="display:flex;flex-direction:column;gap:6px">
            <div v-for="ps in processStats" :key="ps.order_id" style="display:flex;align-items:center;gap:8px;font-size:var(--text-xs);color:var(--text-secondary)">
              <span style="width:120px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap">{{ ps.order_no }}</span>
              <span style="width:100px;font-size:var(--text-2xs);color:var(--text-placeholder)">{{ ps.product_name }}</span>
              <div style="flex:1;height:14px;background:rgba(255,255,255,0.06);border-radius:7px;overflow:hidden">
                <div :style="{width:(ps.total_processes>0?Math.round(ps.done_processes/ps.total_processes*100):0)+'%',height:'100%',background:'linear-gradient(90deg,#00d4ff,#0090ff)',borderRadius:'7px',transition:'width .3s'}"></div>
              </div>
              <span style="width:50px;text-align:right">{{ ps.done_processes }}/{{ ps.total_processes }}</span>
            </div>
          </div>
          <div v-else style="display:flex;flex-direction:column;align-items:center;justify-content:center;height:100%;color:rgba(255,255,255,0.3);gap:var(--space-2)">📊<div>暂无工序数据</div></div>
        </div>
      </div>
      <div class="panel panel-chart">
        <div class="panel-title">👷 今日工人产出 Top10</div>
        <div class="panel-body" style="min-height:200px">
          <div v-if="workerStats.length > 0" style="display:flex;flex-direction:column;gap:6px">
            <div v-for="(w, i) in workerStats" :key="w.worker_name" style="display:flex;align-items:center;gap:8px;font-size:var(--text-xs);color:var(--text-secondary)">
              <span style="width:24px;text-align:center;font-weight:700;color:var(--text-placeholder)">#{{ i + 1 }}</span>
              <span style="width:80px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;font-weight:500">{{ w.worker_name }}</span>
              <div style="flex:1;height:14px;background:rgba(255,255,255,0.06);border-radius:7px;overflow:hidden">
                <div :style="{width:getWorkerPercent(w)+'%',height:'100%',background:workerBarColor(i),borderRadius:'7px',transition:'width .3s'}"></div>
              </div>
              <span style="width:65px;text-align:right;font-weight:600">{{ w.output }} 件</span>
            </div>
          </div>
          <div v-else style="display:flex;flex-direction:column;align-items:center;justify-content:center;height:100%;color:rgba(255,255,255,0.3);gap:var(--space-2)">👷<div>暂无工人数据</div></div>
        </div>
      </div>
    </div>

    <!-- Main Content -->
    <div class="board-main">
      <!-- Left: Orders Progress -->
      <div class="panel">
        <div class="panel-title">在产订单进度</div>
        <div class="panel-body scroll-container" v-if="orders.length > 0">
          <div :class="{'scroll-content': orders.length > 8}">
            <table class="board-orders-table">
              <thead><tr><th>订单号</th><th>产品/客户</th><th>数量</th><th>进度</th><th>状态</th></tr></thead>
              <tbody>
                <tr v-for="order in scrollList" :key="order.id">
                  <td class="order-no">{{ order.order_no }}</td>
                  <td><div>{{ order.product_name || '--' }}</div><div class="order-customer">{{ order.customer || '--' }}</div></td>
                  <td><span style="font-weight:600;color:#a855f7">{{ order.completed }}</span><span style="color:rgba(255,255,255,0.3)">/</span><span>{{ order.quantity }}</span></td>
                  <td><div class="progress-bar"><div class="progress-fill" :class="order.status" :style="{ width: (order.progress_percent || 0) + '%' }"></div></div><div class="progress-text">{{ order.progress_percent || 0 }}%</div></td>
                  <td><span style="display:flex;align-items:center;flex-wrap:wrap;gap:var(--space-1)"><span class="status-badge" :class="order.status">{{ statusText[order.status] }}</span><span v-if="isOverdue(order)" class="overdue-tag">超期</span></span></td>
                </tr>
              </tbody>
            </table>
            <table v-if="orders.length > 8" class="board-orders-table" style="margin-top:1px">
              <tbody><tr v-for="order in scrollList" :key="'dup-'+order.id">
                <td class="order-no">{{ order.order_no }}</td>
                <td><div>{{ order.product_name || '--' }}</div><div class="order-customer">{{ order.customer || '--' }}</div></td>
                <td><span style="font-weight:600;color:#a855f7">{{ order.completed }}</span><span style="color:rgba(255,255,255,0.3)">/</span><span>{{ order.quantity }}</span></td>
                <td><div class="progress-bar"><div class="progress-fill" :class="order.status" :style="{ width: (order.progress_percent || 0) + '%' }"></div></div><div class="progress-text">{{ order.progress_percent || 0 }}%</div></td>
                <td><span style="display:flex;align-items:center;flex-wrap:wrap;gap:var(--space-1)"><span class="status-badge" :class="order.status">{{ statusText[order.status] }}</span><span v-if="isOverdue(order)" class="overdue-tag">超期</span></span></td>
              </tr></tbody>
            </table>
          </div>
        </div>
        <div v-else class="panel-body"><div style="display:flex;flex-direction:column;align-items:center;justify-content:center;height:100%;color:rgba(255,255,255,0.3);gap:var(--space-2)">📋<div>暂无在产订单</div></div></div>
      </div>

      <!-- Middle: Worker Ranking -->
      <div class="panel">
        <div class="panel-title">今日员工排行</div>
        <div class="panel-body">
          <div v-if="workerStats.length > 0">
            <div class="worker-item" v-for="(w, idx) in workerStats" :key="w.worker_name">
              <div class="worker-rank" :class="'rank-'+(idx+1)">{{ idx+1 }}</div>
              <div class="worker-avatar" :style="{background: avatarColor(w.worker_name)}">{{ ((w.worker_name||'?')[0] || '?') }}</div>
              <div class="worker-info">
                <div class="worker-name">{{ w.worker_name }}</div>
                <div class="worker-meta">报工{{ w.report_count || 0 }}次<span v-if="w.scrap > 0" style="color:#ff6b6b"> · 报废{{ w.scrap }}</span><span v-if="w.rework > 0" style="color:#ff9f43"> · 返工{{ w.rework }}</span></div>
                <div class="worker-bar-wrap"><div class="worker-bar" :style="{width: getWorkerPercent(w)+'%', background: workerBarColor(idx)}"></div></div>
              </div>
              <div class="worker-output">{{ w.output || 0 }}</div>
            </div>
          </div>
          <div v-else style="display:flex;flex-direction:column;align-items:center;justify-content:center;height:100%;color:rgba(255,255,255,0.3);gap:var(--space-2)">👷<div>今日暂无报工</div></div>
        </div>
      </div>

      <!-- Right: Process Stats + Recent Reports -->
      <div class="panel">
        <div class="panel-title">今日工序产量</div>
        <div class="panel-body">
          <div class="chart-container" v-if="processStats.length > 0">
            <div class="chart-item" v-for="item in processStats" :key="item.name">
              <div class="chart-label">{{ item.name }}</div>
              <div class="chart-bar-wrap"><div class="chart-bar" :style="{ width: getProcessPercent(item)+'%', background: procBarColor(item.category) }"></div></div>
              <div style="display:flex;gap:var(--space-2);align-items:center;flex-shrink:0">
                <div class="chart-value">{{ item.output || 0 }}</div>
                <div v-if="item.scrap > 0" class="chart-value scrap" style="font-size:var(--text-xs)">({{ item.scrap }})</div>
              </div>
            </div>
          </div>
          <div v-else style="display:flex;flex-direction:column;align-items:center;justify-content:center;height:100%;color:rgba(255,255,255,0.3);gap:var(--space-2)">🏭<div style="margin-top:8px">今日暂无工序产量</div></div>


        </div>
      </div>
    </div>

    <!-- Footer -->
    <div class="board-footer">
      更新于 {{ updateTime }} | 每30秒自动刷新
      <span style="margin-left:12px;cursor:pointer;color:#00d4ff" @click="loadData">🔄 刷新</span>
    </div>
  </div>
</template>

<script>
import { useBoard } from '@/composables/useBoard.js'

export default {
  setup() {
    return useBoard()
  }
}
</script>
