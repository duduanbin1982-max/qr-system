<!-- AuditLogs.vue -->
<template>
<div>
    <div>
      <div class="card">
        <div class="card-header"><h3>📋 操作日志</h3></div>
        <div class="card-body">
          <!-- 筛选栏 -->
          <div style="display:flex;gap:var(--space-2);margin-bottom:var(--space-3);align-items:center;flex-wrap:wrap">
            <input class="form-input" v-model="logFilterAction" placeholder="操作类型（如 create_order）" style="width:180px;padding:6px 10px;font-size:var(--text-sm)">
            <input class="form-input" v-model="logFilterKeyword" placeholder="🔍 搜索详情..." style="width:180px;padding:6px 10px;font-size:var(--text-sm)">
            <input class="form-input" type="date" v-model="logFilterDateFrom" style="width:140px;padding:6px 8px;font-size:var(--text-sm)" title="开始日期">
            <span style="color:var(--text-placeholder);font-size:var(--text-xs)">至</span>
            <input class="form-input" type="date" v-model="logFilterDateTo" style="width:140px;padding:6px 8px;font-size:var(--text-sm)" title="结束日期">
            <button class="btn btn-default btn-sm" @click="doSearch">🔍 搜索</button>
            <select class="form-input" v-model="logFilterCategory" @change="doSearch" style="width:150px;padding:6px 8px;font-size:var(--text-sm)">
              <option value="">全部分类</option>
              <option v-for="category in logCategories" :key="category.code" :value="category.code">{{ category.label }}</option>
            </select>
            <button class="btn btn-default btn-sm" @click="resetFilters">清除筛选</button>
            <button v-if="canClearLogs" class="btn btn-sm" style="background:var(--danger);color:#fff;margin-left:var(--space-1)" @click="clearLogs(1095)">🗑 申请清理三年前日志</button>
            <span style="color:var(--text-placeholder);font-size:var(--text-xs);margin-left:auto" v-if="logFilterAction||logFilterKeyword||logFilterDateFrom">筛选结果：{{ logsTotal }} 条</span>
          </div>
          <div v-if="logsLoading" style="text-align:center;padding:40px;color:var(--text-placeholder)">⏳ 加载中...</div>
          <div v-else>
            <div v-if="logs.length" class="table-wrap">
              <table class="data-table">
                <thead><tr><th style="width:40px;text-align:center">#</th><th>操作人</th><th>操作</th><th>对象类型</th><th>详情</th><th>时间</th></tr></thead>
                <tbody>
                  <tr v-for="(l, idx) in logs" :key="l.id">
                    <td style="text-align:center"><span class="badge" style="background:var(--primary-light);color:var(--primary-dark);min-width:28px;text-align:center">{{ (logsPage-1)*logsLimit + idx + 1 }}</span></td>
                    <td style="font-weight:500">{{ l.user_name || '系统' }}</td>
                    <td><span class="badge" style="background:var(--success-light);color:var(--success-dark)">{{ l.action }}</span></td>
                    <td>{{ l.target_type || '-' }}</td>
                    <td style="font-size:var(--text-xs);color:var(--text-placeholder);max-width:300px;cursor:pointer" @click="expandedLogId = (expandedLogId===l.id ? null : l.id)">
                      <span v-if="expandedLogId!==l.id" style="overflow:hidden;text-overflow:ellipsis;white-space:nowrap;display:block">{{ l.detail || '-' }}</span>
                      <span v-else style="word-break:break-all">{{ l.detail || '-' }}</span>
                    </td>
                    <td style="font-size:var(--text-xs);white-space:nowrap">{{ l.created_at }}</td>
                  </tr>
                </tbody>
              </table>
            </div>
            <div v-else class="empty"><div class="empty-text">{{ logFilterAction||logFilterKeyword||logFilterDateFrom||logFilterCategory ? '无匹配结果，请调整筛选条件' : '暂无操作日志' }}</div></div>
            <!-- Pagination -->
            <div v-if="logsTotal > logsLimit" style="display:flex;justify-content:space-between;align-items:center;margin-top:12px;padding-top:8px;border-top:1px solid var(--bg-hover)">
              <span style="color:var(--text-placeholder);font-size:var(--text-sm)">共 {{ logsTotal }} 条记录</span>
              <div style="display:flex;gap:var(--space-1)">
                <button class="btn btn-default btn-sm" @click="logsPrevPage" :disabled="logsPage<=1">◀ 上一页</button>
                <span style="padding:var(--space-1) 12px;font-size:var(--text-sm);color:var(--text-placeholder)">{{ logsPage }} / {{ Math.ceil(logsTotal/logsLimit) }}</span>
                <button class="btn btn-default btn-sm" @click="logsNextPage" :disabled="logsPage*logsLimit>=logsTotal">下一页 ▶</button>
              </div>
            </div>
          </div>
          <div v-if="canClearLogs && cleanupRequests.length" style="margin-top:var(--space-4);padding-top:var(--space-3);border-top:1px solid var(--border)">
            <h4 style="margin:0 0 var(--space-2);font-size:var(--text-sm)">日志清理申请</h4>
            <div class="table-wrap">
              <table class="data-table">
                <thead><tr><th>申请人</th><th>截止时间</th><th>理由</th><th>预计数量</th><th>状态</th><th>操作</th></tr></thead>
                <tbody>
                  <tr v-for="item in cleanupRequests" :key="item.id">
                    <td>{{ item.requested_by_name || item.requested_by }}</td>
                    <td>{{ item.before_at }}</td>
                    <td style="max-width:260px;word-break:break-word">{{ item.reason }}</td>
                    <td>{{ item.affected_count || 0 }}</td>
                    <td><span class="badge">{{ cleanupStatusText(item.status) }}</span></td>
                    <td>
                      <template v-if="canReviewCleanup(item)">
                        <button class="btn btn-primary btn-sm" @click="approveCleanup(item)">批准</button>
                        <button class="btn btn-default btn-sm" @click="rejectCleanup(item)">驳回</button>
                      </template>
                      <span v-else-if="item.status==='pending'" style="color:var(--text-placeholder);font-size:var(--text-xs)">需其他管理员复核</span>
                      <span v-else style="color:var(--text-placeholder);font-size:var(--text-xs)">{{ item.approved_by_name || '-' }}</span>
                    </td>
                  </tr>
                </tbody>
              </table>
            </div>
          </div>
        </div>
      </div>
    </div>
</div>
</template>

<script>
import { useAuditLogs } from '@/composables/settings/useAuditLogs.js'

export default {
  setup() {
    return useAuditLogs()
  }
}
</script>
