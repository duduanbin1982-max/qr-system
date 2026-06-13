<!-- ReportsPage.vue -->
<template>
<div style="padding:var(--space-6)">
  <div class="card"><div class="card-header"><h3>&#x1F4CA; 数据分析报表</h3></div></div>

  <!-- Tab Bar -->
  <div style="display:flex;flex-wrap:wrap;gap:0;margin-bottom:var(--space-5);background:var(--bg-hover);border-radius:var(--radius-lg);padding:var(--space-1)">
    <div v-for="t in TABS" :key="t.k"
      @click="switchTab(t.k)" style="flex:1;min-width:90px;text-align:center;padding:var(--space-3) 4px;border-radius:var(--radius-md);cursor:pointer;font-size:var(--text-base);line-height:1.5;font-weight:500;transition:all 0.2s"
      :style="{background: tab===t.k?'var(--bg-surface)':'transparent',color: tab===t.k?'var(--primary)':'var(--text-placeholder)',boxShadow: tab===t.k?'0 1px 3px rgba(0,0,0,0.1)':'none'}">
      {{ t.l }}
    </div>
  </div>

  <!-- ========== Date Range (shared for most tabs) ========== -->
  <div v-if="tab!=='trend' && tab!=='dashboard'" class="card" style="margin-bottom:var(--space-4)">
    <div class="card-header">
      <h3>{{ TABS.find(t=>t.k===tab)?.l || '' }}</h3>
      <div style="display:flex;gap:var(--space-2);align-items:center">
        <input type="date" class="form-input" v-model="reportStart" style="width:140px">
        <span style="color:var(--text-placeholder)">&#x81F3;</span>
        <input type="date" class="form-input" v-model="reportEnd" style="width:140px">
        <button class="btn btn-primary btn-sm" @click="loadData">&#x67E5;&#x8BE2;</button>
      </div>
    </div>
  </div>

  <!-- ========== Dashboard KPI ========== -->
  <div v-if="tab==='dashboard'">
    <div class="card" style="margin-bottom:var(--space-4)">
      <div class="card-header"><h3>&#x1F4CA; &#x7EFC;&#x5408;KPI&#x770B;&#x677F;</h3></div>
    </div>
    <!-- KPI Cards -->
    <div class="summary-bar" style="margin-bottom:var(--space-4);display:grid;grid-template-columns:repeat(auto-fit,minmax(160px,1fr));gap:var(--space-3)">
      <div class="summary-item"><span class="s-icon">&#x1F4CB;</span><div><div class="s-val text-primary">{{ kpi.active_orders || 0 }}</div><div class="s-label">&#x5728;&#x4EA7;&#x8BA2;&#x5355;</div></div></div>
      <div class="summary-item"><span class="s-icon">&#x2705;</span><div><div class="s-val text-success">{{ kpi.completed_month || 0 }}</div><div class="s-label">&#x672C;&#x6708;&#x5B8C;&#x6210;</div></div></div>
      <div class="summary-item"><span class="s-icon">&#x1F4E6;</span><div><div class="s-val" style="color:var(--primary)">{{ kpi.output_month || 0 }}</div><div class="s-label">&#x672C;&#x6708;&#x4EA7;&#x91CF;</div></div></div>
      <div class="summary-item"><span class="s-icon">&#x26A0;&#xFE0F;</span><div><div class="s-val text-danger">{{ kpi.scrap_rate || 0 }}%</div><div class="s-label">&#x62A5;&#x5E9F;&#x7387;</div></div></div>
      <div class="summary-item"><span class="s-icon">&#x1F477;</span><div><div class="s-val" style="color:var(--primary)">{{ kpi.active_workers_today || 0 }}</div><div class="s-label">&#x4ECA;&#x65E5;&#x5728;&#x5C97;</div></div></div>
      <div class="summary-item"><span class="s-icon">&#x1F69A;</span><div><div class="s-val text-warning">{{ kpi.pending_shipments || 0 }}</div><div class="s-label">&#x5F85;&#x53D1;&#x8D27;</div></div></div>
      <div class="summary-item"><span class="s-icon">&#x1F4C9;</span><div><div class="s-val text-danger">{{ kpi.low_stock_count || 0 }}</div><div class="s-label">&#x4F4E;&#x5E93;&#x5B58;&#x7269;&#x6599;</div></div></div>
    </div>
    <!-- Weekly Trend -->
    <div class="card">
      <div class="card-header"><h3>&#x1F4C5; &#x8FD1;7&#x5929;&#x4EA7;&#x91CF;&#x8D8B;&#x52BF;</h3></div>
      <div class="card-body">
        <div v-if="weeklyData.length" style="overflow-x:auto">
          <div style="min-width:500px">
            <div v-for="d in weeklyData" :key="d.date" style="display:flex;align-items:center;gap:var(--space-2);margin-bottom:6px">
              <span style="width:70px;font-size:var(--text-xs-alt);color:var(--text-placeholder);text-align:right;flex-shrink:0">{{ d.date.slice(5) }}</span>
              <div style="flex:1;display:flex;gap:0;height:22px;border-radius:var(--radius-sm);overflow:hidden;background:var(--bg-hover)">
                <div :style="{width:(d.output/weeklyMax*100).toFixed(1)+'%',background:'linear-gradient(90deg,var(--primary),var(--primary-light))',minWidth:d.output?'12px':'0',borderRadius:'3px'}" :title="'\u4EA7\u91CF:'+d.output"></div>
              </div>
              <span style="width:40px;font-size:var(--text-xs);font-weight:600;text-align:right;flex-shrink:0">{{ d.output }}</span>
            </div>
          </div>
        </div>
        <p v-else class="empty"><span class="empty-text">&#x6682;&#x65E0;&#x6570;&#x636E;</span></p>
      </div>
    </div>
  </div>

  <!-- ========== Production Trend ========== -->
  <div v-if="tab==='trend'">
    <div class="card" style="margin-bottom:var(--space-4)">
      <div class="card-header">
        <h3>&#x1F4C8; &#x751F;&#x4EA7;&#x8D8B;&#x52BF;</h3>
        <div style="display:flex;gap:var(--space-2);align-items:center">
          <select class="form-input" v-model.number="trendDays" @change="loadData" style="width:120px">
            <option :value="7">&#x6700;&#x8FD1;7&#x5929;</option>
            <option :value="14">&#x6700;&#x8FD1;14&#x5929;</option>
            <option :value="30">&#x6700;&#x8FD1;30&#x5929;</option>
            <option :value="60">&#x6700;&#x8FD1;60&#x5929;</option>
            <option :value="90">&#x6700;&#x8FD1;90&#x5929;</option>
          </select>
          <button class="btn btn-outline btn-sm" @click="exportTrend" :disabled="!trendData.length">&#x1F4E5; CSV</button>
        </div>
      </div>
    </div>
    <!-- Summary -->
    <div class="summary-bar" style="margin-bottom:var(--space-4)" v-if="trendSummary.days">
      <div class="summary-item"><span class="s-icon">&#x1F4E6;</span><div><div class="s-val">{{ trendSummary.total_output }}</div><div class="s-label">&#x603B;&#x4EA7;&#x51FA;</div></div></div>
      <div class="summary-item"><span class="s-icon">&#x1F5D1;&#xFE0F;</span><div><div class="s-val text-danger">{{ trendSummary.total_scrap }}</div><div class="s-label">&#x603B;&#x62A5;&#x5E9F;</div></div></div>
      <div class="summary-item"><span class="s-icon">&#x1F527;</span><div><div class="s-val text-warning">{{ trendSummary.total_rework }}</div><div class="s-label">&#x603B;&#x8FD4;&#x5DE5;</div></div></div>
      <div class="summary-item"><span class="s-icon">&#x1F4CA;</span><div><div class="s-val text-danger">{{ trendSummary.scrap_rate }}%</div><div class="s-label">&#x62A5;&#x5E9F;&#x7387;</div></div></div>
      <div class="summary-item"><span class="s-icon">&#x1F4C9;</span><div><div class="s-val text-warning">{{ trendSummary.rework_rate }}%</div><div class="s-label">&#x8FD4;&#x5DE5;&#x7387;</div></div></div>
    </div>
    <!-- Bar Chart -->
    <div class="card">
      <div class="card-header"><h3>&#x1F4CA; &#x65E5;&#x4EA7;&#x91CF;&#x8D8B;&#x52BF;&#xFF08;&#x6700;&#x8FD1;{{ trendDays }}&#x5929;&#xFF09;</h3></div>
      <div class="card-body">
        <div v-if="trendData.length" style="overflow-x:auto">
          <div style="min-width:600px">
            <div v-for="d in trendData" :key="d.date" style="display:flex;align-items:center;gap:var(--space-2);margin-bottom:6px">
              <span style="width:80px;font-size:var(--text-xs-alt);color:var(--text-placeholder);text-align:right;flex-shrink:0">{{ d.date.slice(5) }}</span>
              <div style="flex:1;display:flex;gap:var(--space-1);height:18px;border-radius:var(--radius-sm);overflow:hidden;background:var(--bg-hover)">
                <div :style="{width:(d.output/trendMaxVal*100).toFixed(1)+'%',background:'linear-gradient(90deg,var(--primary),var(--primary))',minWidth:d.output?'12px':'0',borderRadius:'3px 0 0 3px'}" :title="'\u4EA7\u51FA:'+d.output"></div>
                <div :style="{width:(d.scrap/trendMaxVal*100).toFixed(1)+'%',background:'var(--danger-lighter)',minWidth:d.scrap?'8px':'0'}" :title="'\u62A5\u5E9F:'+d.scrap"></div>
                <div :style="{width:(d.rework/trendMaxVal*100).toFixed(1)+'%',background:'var(--warning-lighter)',minWidth:d.rework?'8px':'0',borderRadius:'0 3px 3px 0'}" :title="'\u8FD4\u5DE5:'+d.rework"></div>
              </div>
              <span style="width:40px;font-size:var(--text-xs);font-weight:600;text-align:right;flex-shrink:0">{{ d.output }}</span>
            </div>
          </div>
          <div style="display:flex;gap:var(--space-4);margin-top:12px;font-size:var(--text-xs);color:var(--text-placeholder)">
            <span>&#x1F7E6; &#x4EA7;&#x51FA;</span><span>&#x1F7E5; &#x62A5;&#x5E9F;</span><span>&#x1F7E8; &#x8FD4;&#x5DE5;</span>
          </div>
        </div>
        <p v-else class="empty"><span class="empty-text">&#x65E0;&#x8D8B;&#x52BF;&#x6570;&#x636E;</span></p>
      </div>
    </div>
  </div>

  <!-- ========== Worker Efficiency ========== -->
  <div v-if="tab==='worker'">
    <div class="card" style="margin-bottom:var(--space-4)">
      <div class="card-header" style="display:flex;justify-content:space-between;align-items:center">
        <span style="font-weight:600">&#x5171; {{ workerStats.length }} &#x4EBA;</span>
        <button class="btn btn-outline btn-sm" @click="exportWorker" :disabled="!workerStats.length">&#x1F4E5; CSV</button>
      </div>
    </div>
    <div class="card">
      <div class="card-body"><div class="table-wrap"><table v-if="workerStats.length" class="data-table">
        <thead><tr><th>#</th><th>&#x59D3;&#x540D;</th><th>&#x5DE5;&#x53F7;</th><th>&#x603B;&#x4EA7;&#x51FA;</th><th>&#x65E5;&#x5747;</th><th>&#x5DE5;&#x4F5C;&#x5929;&#x6570;</th><th>&#x62A5;&#x5DE5;&#x6B21;&#x6570;</th><th>&#x62A5;&#x5E9F;</th><th>&#x62A5;&#x5E9F;&#x7387;</th><th>&#x8FD4;&#x5DE5;</th><th>&#x8FD4;&#x5DE5;&#x7387;</th></tr></thead>
        <tbody>
          <tr v-for="(w,i) in workerStats" :key="w.id">
            <td>{{ i+1 }}</td>
            <td style="font-weight:500">{{ w.name }}</td>
            <td>{{ w.employee_no }}</td>
            <td style="color:var(--success);font-weight:600">{{ w.output }}</td>
            <td>{{ w.daily_avg }}</td>
            <td>{{ w.work_days }}</td>
            <td>{{ w.report_count }}</td>
            <td style="color:var(--danger)">{{ w.scrap }}</td>
            <td><span :style="{color:w.scrap_rate>5?'var(--danger)':'var(--text-placeholder)'}">{{ w.scrap_rate }}%</span></td>
            <td style="color:var(--warning)">{{ w.rework }}</td>
            <td><span :style="{color:w.rework_rate>5?'var(--warning)':'var(--text-placeholder)'}">{{ w.rework_rate }}%</span></td>
          </tr>
        </tbody>
      </table><p v-else class="empty"><span class="empty-text">&#x65E0;&#x6570;&#x636E;</span></p></div></div>
    </div>
  </div>

  <!-- ========== Quality Analysis ========== -->
  <div v-if="tab==='quality'">
    <div class="card" style="margin-bottom:var(--space-4)">
      <div class="card-header" style="display:flex;justify-content:space-between;align-items:center">
        <span style="font-weight:600">&#x5171; {{ qualityProcess.length }} &#x5DE5;&#x5E8F;</span>
        <button class="btn btn-outline btn-sm" @click="exportQuality" :disabled="!qualityProcess.length">&#x1F4E5; CSV</button>
      </div>
    </div>
    <div style="display:grid;grid-template-columns:1fr 1fr;gap:var(--space-4)">
      <div class="card">
        <div class="card-header"><h3>&#x2699;&#xFE0F; &#x6309;&#x5DE5;&#x5E8F;&#x5206;&#x6790; (Top 20)</h3></div>
        <div class="card-body"><div class="table-wrap"><table v-if="qualityProcess.length" class="data-table" style="font-size:var(--text-sm)">
          <thead><tr><th>&#x5DE5;&#x5E8F;</th><th>&#x5206;&#x7C7B;</th><th>&#x4EA7;&#x51FA;</th><th>&#x62A5;&#x5E9F;</th><th>&#x8FD4;&#x5DE5;</th><th>&#x4E0D;&#x826F;&#x7387;</th></tr></thead>
          <tbody>
            <tr v-for="p in qualityProcess" :key="p.id">
              <td style="font-weight:500">{{ p.name }}</td>
              <td>{{ p.category }}</td>
              <td style="color:var(--success);font-weight:600">{{ p.output }}</td>
              <td style="color:var(--danger)">{{ p.scrap }}</td>
              <td style="color:var(--warning)">{{ p.rework }}</td>
              <td><span class="badge" :style="{background:p.defect_rate>10?'var(--danger-light)':'var(--success-light)',color:p.defect_rate>10?'var(--danger)':'var(--success-dark)'}">{{ p.defect_rate }}%</span></td>
            </tr>
          </tbody>
        </table><p v-else class="empty"><span class="empty-text">&#x65E0;&#x6570;&#x636E;</span></p></div></div>
      </div>
      <div class="card">
        <div class="card-header"><h3>&#x1F464; &#x6309;&#x5DE5;&#x4EBA;&#x5206;&#x6790; (Top 10)</h3></div>
        <div class="card-body"><div class="table-wrap"><table v-if="qualityWorker.length" class="data-table" style="font-size:var(--text-sm)">
          <thead><tr><th>&#x5DE5;&#x4EBA;</th><th>&#x4EA7;&#x51FA;</th><th>&#x62A5;&#x5E9F;</th><th>&#x8FD4;&#x5DE5;</th><th>&#x4E0D;&#x826F;&#x7387;</th></tr></thead>
          <tbody>
            <tr v-for="w in qualityWorker" :key="w.name">
              <td style="font-weight:500">{{ w.name }}</td>
              <td style="color:var(--success);font-weight:600">{{ w.output }}</td>
              <td style="color:var(--danger)">{{ w.scrap }}</td>
              <td style="color:var(--warning)">{{ w.rework }}</td>
              <td><span class="badge" :style="{background:w.defect_rate>10?'var(--danger-light)':'var(--success-light)',color:w.defect_rate>10?'var(--danger)':'var(--success-dark)'}">{{ w.defect_rate }}%</span></td>
            </tr>
          </tbody>
        </table><p v-else class="empty"><span class="empty-text">&#x65E0;&#x6570;&#x636E;</span></p></div></div>
      </div>
    </div>
  </div>

  <!-- ========== Order Analysis ========== -->
  <div v-if="tab==='order'">
    <div class="card" style="margin-bottom:var(--space-4)">
      <div class="card-header" style="display:flex;justify-content:space-between;align-items:center">
        <span style="font-weight:600">&#x5171; {{ orderStatus.length }} &#x72B6;&#x6001;</span>
        <button class="btn btn-outline btn-sm" @click="exportOrder" :disabled="!orderStatus.length">&#x1F4E5; CSV</button>
      </div>
    </div>
    <div style="display:grid;grid-template-columns:1fr 1fr;gap:var(--space-4)">
      <div class="card">
        <div class="card-header"><h3>&#x1F4CA; &#x72B6;&#x6001;&#x5206;&#x5E03;</h3></div>
        <div class="card-body">
          <div v-if="orderStatus.length">
            <div v-for="s in orderStatus" :key="s.status" style="display:flex;align-items:center;gap:var(--space-3);margin-bottom:10px;padding:var(--space-2) 12px;background:var(--bg-table-header);border-radius:var(--radius-md)">
              <span class="badge" style="min-width:70px;text-align:center" :class="s.status==='completed'?'badge-success':s.status==='producing'?'badge-warning':'badge-info'">{{ statusLabel(s.status) }}</span>
              <span style="font-weight:600;font-size:var(--text-base);color:var(--primary)">{{ s.count }} &#x5355;</span>
              <span style="font-size:var(--text-sm);color:var(--text-placeholder)">&#x6570;&#x91CF; {{ s.qty }}</span>
              <span style="font-size:var(--text-sm);color:var(--success)">&#x5B8C;&#x6210; {{ s.done }}</span>
              <span style="font-size:var(--text-sm);color:var(--text-placeholder)">{{ s.qty ? Math.round(s.done/s.qty*100) : 0 }}%</span>
            </div>
          </div>
          <p v-else class="empty"><span class="empty-text">&#x65E0;&#x72B6;&#x6001;&#x6570;&#x636E;</span></p>
        </div>
      </div>
      <div class="card">
        <div class="card-header"><h3>&#x1F4C5; &#x6708;&#x5EA6;&#x8D8B;&#x52BF;</h3></div>
        <div class="card-body"><div class="table-wrap"><table v-if="orderMonthly.length" class="data-table" style="font-size:var(--text-sm)">
          <thead><tr><th>&#x6708;&#x4EFD;</th><th>&#x8BA2;&#x5355;&#x6570;</th><th>&#x603B;&#x6570;&#x91CF;</th><th>&#x5DF2;&#x5B8C;&#x6210;</th><th>&#x5B8C;&#x6210;&#x7387;</th></tr></thead>
          <tbody>
            <tr v-for="m in orderMonthly" :key="m.month">
              <td style="font-weight:500">{{ m.month }}</td>
              <td style="font-weight:600;color:var(--primary)">{{ m.count }}</td>
              <td>{{ m.total_qty }}</td>
              <td style="color:var(--success)">{{ m.total_done }}</td>
              <td>{{ m.total_qty ? Math.round(m.total_done/m.total_qty*100) : 0 }}%</td>
            </tr>
          </tbody>
        </table><p v-else class="empty"><span class="empty-text">&#x65E0;&#x6708;&#x5EA6;&#x6570;&#x636E;</span></p></div></div>
      </div>
    </div>
  </div>

  <!-- ========== Product Stats (NEW) ========== -->
  <div v-if="tab==='product'">
    <div class="card" style="margin-bottom:var(--space-4)">
      <div class="card-header" style="display:flex;justify-content:space-between;align-items:center">
        <span style="font-weight:600">&#x5171; {{ productSummary.product_count || 0 }} &#x4EA7;&#x54C1;&#xFF0C;{{ productSummary.order_count || 0 }} &#x8BA2;&#x5355;</span>
        <button class="btn btn-outline btn-sm" @click="exportProduct" :disabled="!productList.length">&#x1F4E5; CSV</button>
      </div>
    </div>
    <div class="card">
      <div class="card-header"><h3>&#x1F3F7;&#xFE0F; &#x4EA7;&#x54C1;&#x4EA7;&#x91CF;&#x6392;&#x540D;</h3></div>
      <div class="card-body"><div class="table-wrap"><table v-if="productList.length" class="data-table">
        <thead><tr><th>#</th><th>&#x4EA7;&#x54C1;&#x540D;&#x79F0;</th><th>&#x7F16;&#x7801;</th><th>&#x578B;&#x53F7;</th><th>&#x89C4;&#x683C;</th><th>&#x5206;&#x7C7B;</th><th>&#x4EA7;&#x91CF;</th><th>&#x62A5;&#x5E9F;</th><th>&#x8FD4;&#x5DE5;</th><th>&#x6D89;&#x53CA;&#x8BA2;&#x5355;</th></tr></thead>
        <tbody>
          <tr v-for="(p,i) in productList" :key="p.id">
            <td>{{ i+1 }}</td>
            <td style="font-weight:500">{{ p.product_name }}</td>
            <td>{{ p.product_code }}</td>
            <td>{{ p.model }}</td>
            <td>{{ p.spec }}</td>
            <td><span class="badge badge-info">{{ p.category }}</span></td>
            <td style="color:var(--success);font-weight:600">{{ p.output }}</td>
            <td style="color:var(--danger)">{{ p.scrap }}</td>
            <td style="color:var(--warning)">{{ p.rework }}</td>
            <td>{{ p.order_count }}</td>
          </tr>
        </tbody>
      </table><p v-else class="empty"><span class="empty-text">&#x65E0;&#x4EA7;&#x54C1;&#x6570;&#x636E;</span></p></div></div>
    </div>
  </div>

  <!-- ========== Material Usage (NEW) ========== -->
  <div v-if="tab==='material'">
    <div class="card" style="margin-bottom:var(--space-4)">
      <div class="card-header" style="display:flex;justify-content:space-between;align-items:center">
        <span style="font-weight:600">&#x5171; {{ materialSummary.material_count || 0 }} &#x7269;&#x6599;&#xFF0C;&#x7D2F;&#x8BA1;&#x6D88;&#x8017; {{ materialSummary.total_consumed || 0 }}</span>
        <button class="btn btn-outline btn-sm" @click="exportMaterial" :disabled="!materialList.length">&#x1F4E5; CSV</button>
      </div>
    </div>
    <div class="card">
      <div class="card-header"><h3>&#x1F4E6; &#x7269;&#x6599;&#x6D88;&#x8017;&#x6392;&#x884C;</h3></div>
      <div class="card-body"><div class="table-wrap"><table v-if="materialList.length" class="data-table">
        <thead><tr><th>#</th><th>&#x7269;&#x6599;&#x540D;&#x79F0;</th><th>&#x89C4;&#x683C;</th><th>&#x6750;&#x8D28;</th><th>&#x5E93;&#x5B58;</th><th>&#x6700;&#x4F4E;&#x5E93;&#x5B58;</th><th>&#x5DF2;&#x6D88;&#x8017;</th><th>&#x6D89;&#x53CA;&#x8BA2;&#x5355;</th></tr></thead>
        <tbody>
          <tr v-for="(m,i) in materialList" :key="m.id" :style="{background: m.safe_stock>0 && m.stock_qty<=m.safe_stock ? 'var(--danger-lighter)' : ''}">
            <td>{{ i+1 }}</td>
            <td style="font-weight:500">{{ m.name }}</td>
            <td>{{ m.spec }}</td>
            <td>{{ m.material_type }}</td>
            <td :style="{color: m.safe_stock>0 && m.stock_qty<=m.safe_stock ? 'var(--danger)' : ''}">{{ m.stock_qty }} {{ m.unit }}</td>
            <td>{{ m.safe_stock }} {{ m.unit }}</td>
            <td style="color:var(--primary);font-weight:600">{{ m.total_used }} {{ m.unit }}</td>
            <td>{{ m.order_count }}</td>
          </tr>
        </tbody>
      </table><p v-else class="empty"><span class="empty-text">&#x65E0;&#x7269;&#x6599;&#x6D88;&#x8017;&#x6570;&#x636E;</span></p></div></div>
    </div>
  </div>

  <!-- ========== Shipment Stats (NEW) ========== -->
  <div v-if="tab==='shipment'">
    <div class="card" style="margin-bottom:var(--space-4)">
      <div class="card-header" style="display:flex;justify-content:space-between;align-items:center">
        <span style="font-weight:600">&#x53D1;&#x8D27;&#x7EDF;&#x8BA1;</span>
        <button class="btn btn-outline btn-sm" @click="exportShipment" :disabled="!shipmentByStatus.length">&#x1F4E5; CSV</button>
      </div>
    </div>
    <div style="display:grid;grid-template-columns:1fr 1fr;gap:var(--space-4)">
      <div class="card">
        <div class="card-header"><h3>&#x1F4CA; &#x72B6;&#x6001;&#x5206;&#x5E03;</h3></div>
        <div class="card-body">
          <div v-if="shipmentByStatus.length">
            <div v-for="s in shipmentByStatus" :key="s.status" style="display:flex;align-items:center;gap:var(--space-3);margin-bottom:10px;padding:var(--space-2) 12px;background:var(--bg-table-header);border-radius:var(--radius-md)">
              <span class="badge" style="min-width:70px;text-align:center" :class="s.status==='completed'?'badge-success':s.status==='pending'?'badge-warning':'badge-info'">{{ statusLabel(s.status) }}</span>
              <span style="font-weight:600;font-size:var(--text-base);color:var(--primary)">{{ s.count }} &#x6279;</span>
              <span style="font-size:var(--text-sm);color:var(--text-placeholder)">&#x6570;&#x91CF; {{ s.total_qty }}</span>
            </div>
          </div>
          <p v-else class="empty"><span class="empty-text">&#x65E0;&#x53D1;&#x8D27;&#x6570;&#x636E;</span></p>
        </div>
      </div>
      <div class="card">
        <div class="card-header"><h3>&#x1F3E2; &#x6309;&#x5BA2;&#x6237;&#x5206;&#x6790;</h3></div>
        <div class="card-body"><div class="table-wrap"><table v-if="shipmentByCustomer.length" class="data-table" style="font-size:var(--text-sm)">
          <thead><tr><th>&#x5BA2;&#x6237;</th><th>&#x53D1;&#x8D27;&#x6279;&#x6B21;</th><th>&#x603B;&#x6570;&#x91CF;</th></tr></thead>
          <tbody>
            <tr v-for="c in shipmentByCustomer" :key="c.customer">
              <td style="font-weight:500">{{ c.customer }}</td>
              <td style="color:var(--primary);font-weight:600">{{ c.shipment_count }}</td>
              <td>{{ c.total_qty }}</td>
            </tr>
          </tbody>
        </table><p v-else class="empty"><span class="empty-text">&#x65E0;&#x6570;&#x636E;</span></p></div></div>
      </div>
    </div>
    <div class="card" style="margin-top:var(--space-4)">
      <div class="card-header"><h3>&#x1F4C5; &#x6708;&#x5EA6;&#x53D1;&#x8D27;&#x8D8B;&#x52BF;</h3></div>
      <div class="card-body"><div class="table-wrap"><table v-if="shipmentMonthly.length" class="data-table">
        <thead><tr><th>&#x6708;&#x4EFD;</th><th>&#x53D1;&#x8D27;&#x6279;&#x6B21;</th><th>&#x603B;&#x6570;&#x91CF;</th></tr></thead>
        <tbody>
          <tr v-for="m in shipmentMonthly" :key="m.month">
            <td style="font-weight:500">{{ m.month }}</td>
            <td style="color:var(--primary);font-weight:600">{{ m.count }}</td>
            <td>{{ m.total_qty }}</td>
          </tr>
        </tbody>
      </table><p v-else class="empty"><span class="empty-text">&#x65E0;&#x6708;&#x5EA6;&#x6570;&#x636E;</span></p></div></div>
    </div>
  </div>

  <div v-if="loading" style="text-align:center;padding:40px;color:var(--text-placeholder)">&#x23F3; &#x52A0;&#x8F7D;&#x4E2D;...</div>
</div>
</template>

<script>
import { ref, computed, onMounted } from 'vue'
import { api } from '@/lib/api.js'
import { showToast } from '@/lib/store.js'

export default {
  setup() {
    const tab = ref('dashboard')
    const loading = ref(false)
    const updateTime = ref('')
    const ctx = { tab, loading, updateTime }

    const reportStart = ref('')
    const reportEnd = ref('')

    function initDates() {
      const now = new Date()
      const local = d => d.getFullYear() + '-' + String(d.getMonth() + 1).padStart(2, '0') + '-' + String(d.getDate()).padStart(2, '0')
      reportEnd.value = local(now)
      reportStart.value = local(new Date(now - 30 * 86400000))
      updateTime.value = now.toLocaleString('zh-CN')
    }

    // ---- Dashboard ----
    const kpi = ref({})
    const weeklyData = ref([])
    const weeklyMax = computed(() => Math.max(...weeklyData.value.map(d => d.output || 0), 1))
    const loadDashboard = createLoader(ctx, async () => {
      const d = await api.dashboardKpi()
      kpi.value = d
      weeklyData.value = d.weekly_trend || []
    })

    // ---- Trend ----
    const trendDays = ref(30)
    const trendData = ref([])
    const trendSummary = ref({})
    const trendMaxVal = computed(() =>
      Math.max(...trendData.value.map(t => Math.max(t.output, t.scrap, t.rework)), 1)
    )
    const loadTrend = createLoader(ctx, async () => {
      const d = await api.productionTrend({ days: trendDays.value })
      trendData.value = d.trend || []
      trendSummary.value = d.summary || {}
    })
    const exportTrend = createExporter(trendData,
      ['\u65E5\u671F', '\u4EA7\u91CF', '\u62A5\u5E9F', '\u62A5\u5E9F\u7387%', '\u8FD4\u5DE5', '\u8FD4\u5DE5\u7387%', '\u62A5\u5DE5\u6B21\u6570'],
      d => [d.date, d.output, d.scrap, d.output > 0 ? (d.scrap / d.output * 100).toFixed(1) : 0, d.rework, d.output > 0 ? (d.rework / d.output * 100).toFixed(1) : 0, d.report_count],
      '\u751F\u4EA7\u8D8B\u52BF'
    )

    // ---- Worker ----
    const workerStats = ref([])
    const loadWorker = createLoader(ctx, async () => {
      const d = await api.workerEfficiency(buildParams(reportStart, reportEnd))
      workerStats.value = d.workers || []
    })
    const exportWorker = createExporter(workerStats,
      ['\u6392\u540D', '\u59D3\u540D', '\u5DE5\u53F7', '\u603B\u4EA7\u51FA', '\u65E5\u5747', '\u5DE5\u4F5C\u5929\u6570', '\u62A5\u5DE5\u6B21\u6570', '\u62A5\u5E9F', '\u62A5\u5E9F\u7387%', '\u8FD4\u5DE5', '\u8FD4\u5DE5\u7387%'],
      (w, i) => [i + 1, w.name, w.employee_no || '', w.output, w.daily_avg, w.work_days, w.report_count, w.scrap, w.scrap_rate, w.rework, w.rework_rate],
      '\u5DE5\u4EBA\u6548\u7387'
    )

    // ---- Quality ----
    const qualityProcess = ref([])
    const qualityWorker = ref([])
    const loadQuality = createLoader(ctx, async () => {
      const d = await api.qualityAnalysis(buildParams(reportStart, reportEnd))
      qualityProcess.value = d.by_process || []
      qualityWorker.value = d.by_worker || []
    })
    const exportQuality = createExporter(qualityProcess,
      ['\u5DE5\u5E8F', '\u5206\u7C7B', '\u4EA7\u51FA', '\u62A5\u5E9F', '\u62A5\u5E9F\u7387%', '\u8FD4\u5DE5', '\u8FD4\u5DE5\u7387%', '\u4E0D\u826F\u5408\u8BA1'],
      p => [p.name, p.category || '', p.output || 0, p.scrap || 0, p.defect_rate || 0, p.rework || 0, (p.scrap || 0) + (p.rework || 0)],
      '\u54C1\u8D28\u5206\u6790'
    )

    // ---- Order ----
    const orderStatus = ref([])
    const orderMonthly = ref([])
    const loadOrder = createLoader(ctx, async () => {
      const d = await api.orderAnalysis(buildParams(reportStart, reportEnd))
      orderStatus.value = d.status_distribution || []
      orderMonthly.value = d.monthly_trend || []
    })
    const exportOrder = createExporter(orderStatus,
      ['\u72B6\u6001', '\u8BA2\u5355\u6570', '\u603B\u91CF', '\u5DF2\u5B8C\u6210', '\u5B8C\u6210\u7387%', '\u5269\u4F59'],
      s => [statusLabel(s.status), s.count, s.qty || 0, s.done || 0, (s.qty || 0) > 0 ? ((s.done || 0) / s.qty * 100).toFixed(1) : 0, Math.max(0, (s.qty || 0) - (s.done || 0))],
      '\u8BA2\u5355\u5206\u6790'
    )

    // ---- Product ----
    const productList = ref([])
    const productSummary = ref({})
    const loadProduct = createLoader(ctx, async () => {
      const d = await api.productStats(buildParams(reportStart, reportEnd))
      productList.value = d.by_product || []
      productSummary.value = d.summary || {}
    })
    const exportProduct = createExporter(productList,
      ['\u4EA7\u54C1\u540D\u79F0', '\u4EA7\u54C1\u7F16\u7801', '\u578B\u53F7', '\u89C4\u683C', '\u5206\u7C7B', '\u4EA7\u91CF', '\u62A5\u5E9F', '\u8FD4\u5DE5', '\u6D89\u53CA\u8BA2\u5355\u6570'],
      p => [p.product_name, p.product_code || '', p.model || '', p.spec || '', p.category || '', p.output, p.scrap, p.rework, p.order_count],
      '\u4EA7\u54C1\u7EDF\u8BA1'
    )

    // ---- Material ----
    const materialList = ref([])
    const materialSummary = ref({})
    const loadMaterial = createLoader(ctx, async () => {
      const d = await api.materialUsage(buildParams(reportStart, reportEnd))
      materialList.value = d.by_material || []
      materialSummary.value = d.summary || {}
    })
    const exportMaterial = createExporter(materialList,
      ['\u7269\u6599\u540D\u79F0', '\u89C4\u683C', '\u6750\u8D28', '\u5355\u4F4D', '\u5E93\u5B58', '\u6700\u4F4E\u5E93\u5B58', '\u5DF2\u6D88\u8017', '\u6D89\u53CA\u8BA2\u5355\u6570'],
      m => [m.name, m.spec || '', m.material_type || '', m.unit || '', m.stock_qty, m.safe_stock, m.total_used, m.order_count],
      '\u7269\u6599\u6D88\u8017'
    )

    // ---- Shipment ----
    const shipmentByStatus = ref([])
    const shipmentByCustomer = ref([])
    const shipmentMonthly = ref([])
    const loadShipment = createLoader(ctx, async () => {
      const d = await api.shipmentStats(buildParams(reportStart, reportEnd))
      shipmentByStatus.value = d.by_status || []
      shipmentByCustomer.value = d.by_customer || []
      shipmentMonthly.value = d.monthly_trend || []
    })
    const exportShipment = createExporter(shipmentByStatus,
      ['\u72B6\u6001', '\u53D1\u8D27\u6570', '\u603B\u6570\u91CF'],
      s => [statusLabel(s.status), s.count, s.total_qty],
      '\u53D1\u8D27\u7EDF\u8BA1'
    )

    // ---- Tab switch ----
    const loadMap = { dashboard: loadDashboard, trend: loadTrend, worker: loadWorker, quality: loadQuality,
      order: loadOrder, product: loadProduct, material: loadMaterial, shipment: loadShipment }

    function switchTab(t) { tab.value = t; if (loadMap[t]) loadMap[t]() }

    onMounted(() => { initDates(); loadDashboard() })

    return {
      tab, switchTab, loading, updateTime, TABS,
      reportStart, reportEnd,
      kpi, weeklyData, weeklyMax,
      trendDays, trendData, trendSummary, trendMaxVal, exportTrend,
      workerStats, exportWorker,
      qualityProcess, qualityWorker, exportQuality,
      orderStatus, orderMonthly, exportOrder,
      productList, productSummary, exportProduct,
      materialList, materialSummary, exportMaterial,
      shipmentByStatus, shipmentByCustomer, shipmentMonthly, exportShipment,
      statusLabel,
    }
  }
}
</script>
