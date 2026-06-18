<!-- DashboardPage.vue -->
<template>
<div class="dashboard-root">
    <!-- Loading -->
    <div v-if="loading" class="dash-state dash-loading">
      <p>⏳ 加载中...</p>
    </div>
    
    <!-- Error -->
    <div v-else-if="error" class="dash-state dash-error">
      <p>❌ {{ error }}</p>
      <button class="btn btn-primary btn-sm dash-retry" @click="load">重试</button>
    </div>
    
    <!-- Data -->
    <div v-else>
      <!-- 欢迎栏 -->
      <div class="welcome-bar">
        <div class="welcome-icon">👋</div>
        <div class="welcome-text">欢迎<span class="welcome-name"> {{ auth.user?.nickname || auth.user?.name || '用户' }}</span></div>
        <div class="welcome-time">{{ now }}</div>
      </div>
      
      <div v-if="companyName" class="company-header">
        <h2 class="company-title">🏭 {{ companyName }}</h2>
      </div>
      
      <!-- Hero Stats -->
      <div class="hero-stats">
        <div class="hs-card hs-blue" @click="navigate('orders')">
          <div class="hs-icon">📋</div>
          <div class="hs-val">{{ stats?.total_orders || 0 }}</div>
          <div class="hs-label">总订单</div>
        </div>
        <div class="hs-card hs-green" @click="navigate('scan')">
          <div class="hs-icon">📊</div>
          <div class="hs-val">{{ stats?.today_output || 0 }}</div>
          <div class="hs-label">今日产量</div>
        </div>
        <div class="hs-card hs-orange" @click="navigate('orders')">
          <div class="hs-icon">⏳</div>
          <div class="hs-val">{{ stats?.pending || 0 }}</div>
          <div class="hs-label">待生产</div>
        </div>
        <div class="hs-card hs-pink" @click="navigate('stats')">
          <div class="hs-icon">⚠️</div>
          <div class="hs-val">{{ stats?.today_scrap || 0 }}</div>
          <div class="hs-label">今日报废</div>
        </div>
        <div class="hs-card hs-purple" @click="navigate('approvals')" :class="{ 'hs-pulse': (stats?.pending_approvals || 0) > 0 }">
          <div class="hs-icon">📋</div>
          <div class="hs-val" :style="{color: (stats?.pending_approvals||0) > 0 ? 'var(--danger)' : ''}">{{ stats?.pending_approvals || 0 }}</div>
          <div class="hs-label">待审批</div>
        </div>
        <div class="hs-card" @click="navigate('inventory')" :class="(stats?.low_stock?.length||0) > 0 ? 'hs-danger' : 'hs-success'" :style="(stats?.low_stock?.length||0) > 0 ? 'border: 2px solid var(--danger); animation: hsPulse 2s infinite;' : 'border: 2px solid var(--success);'">
          <div class="hs-icon">📦</div>
          <div class="hs-val" :style="{color: (stats?.low_stock?.length||0) > 0 ? 'var(--danger)' : 'var(--success)'}">{{ stats?.low_stock?.length || 0 }}</div>
          <div class="hs-label">低库存预警</div>
        </div>
      </div>
      
      <!-- Secondary Stats -->
      <div class="sec-stats">
        <div class="ss-card" @click="navigate('orders')">
          <div class="ss-icon">🔄</div>
          <div class="ss-val">{{ stats?.producing || 0 }}</div>
          <div class="ss-label">生产中订单</div>
        </div>
        <div class="ss-card" @click="navigate('orders')">
          <div class="ss-icon">✅</div>
          <div class="ss-val">{{ stats?.completed || 0 }}</div>
          <div class="ss-label">已完成订单</div>
        </div>
        <div class="ss-card" @click="navigate('approvals')">
          <div class="ss-icon">📋</div>
          <div class="ss-val" :style="{color: (stats?.pending_approvals||0) > 0 ? 'var(--danger)' : ''}">{{ stats?.pending_approvals || 0 }}</div>
          <div class="ss-label">待审批报工</div>
        </div>
        <div class="ss-card" @click="navigate('scan')">
          <div class="ss-icon">📝</div>
          <div class="ss-val">{{ stats?.today_rework || 0 }}</div>
          <div class="ss-label">今日返工</div>
        </div>
      </div>

      <!-- 交期预警 -->
      <div v-if="deliveryWarnings && ((deliveryWarnings.overdue||[]).length || (deliveryWarnings.approaching||[]).length)" class="delivery-alerts">
        <div v-if="(deliveryWarnings.overdue||[]).length" class="alert alert-danger">
          <strong>🚨 已逾期订单 ({{ deliveryWarnings.overdue.length }})</strong>
          <div v-for="o in deliveryWarnings.overdue" :key="o.id" class="alert-item">
            <span class="alert-order-no">{{ o.order_no }}</span>
            <span>{{ o.product_name }}</span>
            <span class="alert-overdue">逾期 {{ o.overdue_days }} 天</span>
            <span class="alert-meta">计划: {{ o.plan_end }}</span>
          </div>
        </div>
        <div v-if="(deliveryWarnings.approaching||[]).length" class="alert alert-warning">
          <strong>⏰ 即将到期 ({{ deliveryWarnings.approaching.length }})，预警天数: {{ deliveryWarnings.warning_days }}天</strong>
          <div v-for="o in deliveryWarnings.approaching" :key="o.id" class="alert-item">
            <span class="alert-order-no">{{ o.order_no }}</span>
            <span>{{ o.product_name }}</span>
            <span class="alert-approaching">剩余 {{ o.days_left }} 天</span>
            <span class="alert-meta">计划: {{ o.plan_end }}</span>
          </div>
        </div>
      </div>
      
      <!-- 快捷操作 -->
      <div class="section-title">🚀 快捷操作</div>
      <div class="quick-actions">
        <div class="qa-item" v-for="q in quickActions" :key="q.page" @click="goAction(q)">
          <div class="qa-icon">{{ q.icon }}</div>
          <div class="qa-text">{{ q.text }}</div>
          <div class="qa-desc">{{ q.desc }}</div>
        </div>
      </div>
      
      <!-- 登录安全卡片 -->
      <div v-if="security" class="section-title dash-security-title">🛡️ 登录安全</div>
      <div v-if="security" class="sec-stats sec-stats-4col">
        <div class="ss-card" :class="{ 'ss-card-alert': security.locked_users > 0 }" @click="navigate('users')">
          <div class="ss-icon">{{ security.locked_users > 0 ? '🔒' : '🟢' }}</div>
          <div class="ss-val" :class="{ 'ss-val-danger': security.locked_users > 0 }">{{ security.locked_users }}</div>
          <div class="ss-label">锁定账户</div>
        </div>
        <div class="ss-card" :class="{ 'ss-card-warn': security.today_failed_logins > 10 }">
          <div class="ss-icon">⚠️</div>
          <div class="ss-val" :class="{ 'ss-val-warning': security.today_failed_logins > 10 }">{{ security.today_failed_logins }}</div>
          <div class="ss-label">今日失败登录</div>
        </div>
        <div class="ss-card">
          <div class="ss-icon">✅</div>
          <div class="ss-val">{{ security.today_success_logins }}</div>
          <div class="ss-label">今日成功登录</div>
        </div>
        <div class="ss-card" :class="{ 'ss-card-alert': security.suspicious_ips > 0 }">
          <div class="ss-icon">{{ security.suspicious_ips > 0 ? '🌍' : '🏠' }}</div>
          <div class="ss-val" :class="{ 'ss-val-danger': security.suspicious_ips > 0 }">{{ security.suspicious_ips }}</div>
          <div class="ss-label">新IP登录</div>
        </div>
      </div>

      <!-- 最近报工 -->
      <div class="section-title">📝 最近报工记录</div>
      <table class="data-table" v-if="records.length">
        <thead>
          <tr><th>订单号</th><th>工序</th><th>工人</th><th>数量</th><th>时间</th><th>状态</th></tr>
        </thead>
        <tbody>
          <tr v-for="r in records.slice(0,10)" :key="r.id">
            <td><code class="order-code">{{ r.order_no }}</code></td>
            <td>{{ r.process_name }}</td>
            <td>{{ r.worker_name }}</td>
            <td class="td-qty">{{ r.quantity }}</td>
            <td class="td-time">{{ r.created_at }}</td>
            <td><span class="badge" :class="r.status==='approved'?'badge-success':r.status==='pending'?'badge-warning':'badge-danger'">{{ r.status === 'approved' ? '已审批' : r.status === 'pending' ? '待审批' : '已拒绝' }}</span></td>
          </tr>
        </tbody>
      </table>
      <p v-else class="dash-empty">暂无报工记录</p>
    </div>
  </div>
</template>

<script>
import { ref, onMounted, onUnmounted } from 'vue'
import { api } from '@/lib/api.js'
import { navigate } from '@/lib/router.js'
import { auth, getBoardToken } from '@/lib/auth.js'

export default {
  setup() {
    const stats = ref(null)
    const security = ref(null)
    const records = ref([])
    const companyName = ref('')
    const deliveryWarnings = ref(null)
    const loading = ref(true)
    const error = ref('')
    
    // 当前时间
    const now = ref('')
    function updateTime() {
      const d = new Date()
      const h = d.getHours()
      const g = h < 6 ? '凌晨好' : h < 9 ? '早上好' : h < 12 ? '上午好' : h < 14 ? '中午好' : h < 18 ? '下午好' : '晚上好'
      now.value = g + '，' + d.toLocaleString('zh-CN', { month:'long', day:'numeric', weekday:'long' })
    }
    // 快捷操作（从后端API动态获取）
    const quickActions = ref([])

    // 立即显示时间（不等60s定时器触发）
    updateTime()

    async function load() {
      loading.value = true
      error.value = ''
      try {
        const d = await api.dashboard()
        stats.value = d.stats
        security.value = d.security || null
        records.value = d.recent_records || []
        companyName.value = d.company_name || ''
        deliveryWarnings.value = d.delivery_warnings || null
        quickActions.value = (d.quick_actions || []).filter(q => q && q.page).map(q => ({ page: q.page, icon: q.icon || '📋', text: q.label || q.page, desc: q.desc || '', external: q.external || null }))
      } catch(e) {
        error.value = e.message || '加载失败'
      } finally {
        loading.value = false
      }
    }
    
    let _timer = null
    let _clock = null

    onMounted(() => {
      load()
      updateTime()
      // 每60秒自动刷新 + 每分钟更新时钟
      _timer = setInterval(load, 60000)
      _clock = setInterval(updateTime, 60000)
    })

    onUnmounted(() => {
      if (_timer) clearInterval(_timer)
      if (_clock) clearInterval(_clock)
    })
    
    function goAction(q) { if (q.external) { getBoardToken(); window.open(q.external, '_blank'); } else { navigate(q.page); } }
    return { stats, security, records, loading, error, load, now, companyName, deliveryWarnings, quickActions, navigate, auth, goAction }
  }
}
</script>
