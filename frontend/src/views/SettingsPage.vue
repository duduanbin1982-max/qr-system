<!-- SettingsPage.vue -->
<template>
<div style="padding:var(--space-6)">
    <div class="card"><div class="card-header"><h3>⚙️ 系统设置</h3></div></div>
    <!-- Tab bar -->
    <div style="display:flex;gap:var(--space-1);margin-bottom:var(--space-5);border-bottom:2px solid var(--border-light);padding-bottom:0;overflow-x:auto">
      <button v-for="t in tabs" :key="t.key"
        class="tab-btn" :class="{active: activeTab===t.key}"
        @click="activeTab=t.key">
        {{ t.label }}
      </button>
    </div>

    <!-- ========== 公司资料 ========== -->
    <div v-if="activeTab==='company-info'">
      <div class="card" style="margin-bottom:var(--space-5)">
        <div class="card-header">
          <h3>🏢 公司资料</h3>
        </div>
        <div class="card-body">
          <div v-if="loading" style="text-align:center;padding:40px;color:var(--text-placeholder)">⏳ 加载中...</div>
          <div v-else style="max-width:640px">
            <div style="padding:var(--space-3) 0;border-bottom:1px solid var(--bg-hover)">
              <label style="display:block;font-size:var(--text-sm);font-weight:500;color:var(--text-secondary);margin-bottom:6px">公司名称</label>
              <input class="form-input" v-model="edits.company_name" placeholder="请输入公司名称" style="font-size:var(--text-base)">
            </div>
            <div style="padding:var(--space-3) 0;border-bottom:1px solid var(--bg-hover)">
              <label style="display:block;font-size:var(--text-sm);font-weight:500;color:var(--text-secondary);margin-bottom:6px">联系人</label>
              <input class="form-input" v-model="edits.contact" placeholder="请输入联系人" style="font-size:var(--text-base)">
            </div>
            <div style="padding:var(--space-3) 0;border-bottom:1px solid var(--bg-hover)">
              <label style="display:block;font-size:var(--text-sm);font-weight:500;color:var(--text-secondary);margin-bottom:6px">联系电话</label>
              <input class="form-input" v-model="edits.phone" placeholder="请输入联系电话" style="font-size:var(--text-base)">
            </div>
            <div style="padding:var(--space-3) 0;border-bottom:1px solid var(--bg-hover)">
              <label style="display:block;font-size:var(--text-sm);font-weight:500;color:var(--text-secondary);margin-bottom:6px">公司地址</label>
              <input class="form-input" v-model="edits.address" placeholder="请输入公司地址" style="font-size:var(--text-base)">
            </div>
            <div style="padding:var(--space-3) 0">
              <label style="display:block;font-size:var(--text-sm);font-weight:500;color:var(--text-secondary);margin-bottom:6px">公司简介</label>
              <textarea class="form-input" v-model="edits.description" placeholder="请输入公司简介" rows="3" style="font-size:var(--text-base)"></textarea>
            </div>
          </div>
        </div>
      </div>
      <div style="text-align:right">
        <button class="btn" @click="saveSettings" :disabled="saving"
          :style="{minWidth:'120px', background: companyInfoDirty ? 'var(--warning)' : 'var(--primary)', color:'var(--bg-surface)'}">
          {{ saving ? '⏳ 保存中...' : (companyInfoDirty ? '💾 保存设置 ●' : '💾 保存设置') }}
        </button>
      </div>
    </div>

    <!-- 添加设置项弹窗 -->
    <div v-if="showAddKeyModal" style="position:fixed;top:0;left:0;width:100%;height:100%;background:rgba(0,0,0,0.4);z-index:1000;display:flex;align-items:center;justify-content:center" >
      <div style="background:white;border-radius:12px;padding:24px;width:400px;max-width:90vw;box-shadow:0 8px 32px rgba(0,0,0,0.2)">
        <h4 style="margin:0 0 16px 0">添加设置项</h4>
        <div style="margin-bottom:12px">
          <label style="display:block;font-size:13px;color:var(--text-secondary);margin-bottom:6px">设置项名称（英文 key）</label>
          <input class="form-input" v-model="newSettingKey" placeholder="例如：company_name" @keyup.enter="confirmAddSetting" style="width:100%">
        </div>
        <div style="font-size:12px;color:var(--text-placeholder);margin-bottom:16px">可用设置项：company_name, contact, phone, address, description, default_password, approval_enabled, auto_order_no, page_size, process_order_mode, delivery_warning_days, limit_by_prev_process, limit_by_order_qty, session_timeout_hours, session_idle_minutes</div>
        <div style="display:flex;gap:8px;justify-content:flex-end">
          <button class="btn btn-default" @click="showAddKeyModal=false">取消</button>
          <button class="btn btn-primary" @click="confirmAddSetting">添加</button>
        </div>
      </div>
    </div>
    <!-- ========== 管理员管理 ========== -->
    <div v-if="activeTab==='admin-users'">
      <div class="summary-bar" style="margin-bottom:var(--space-4)">
        <div class="summary-item"><span class="s-icon">👥</span><div><div class="s-val">{{ filteredAdminList.length }}</div><div class="s-label">管理员总数</div></div></div>
        <div class="summary-item"><span class="s-icon">✅</span><div><div class="s-val text-success">{{ filteredAdminList.filter(u=>u.status==='active').length }}</div><div class="s-label">正常</div></div></div>
        <div class="summary-item"><span class="s-icon">⛔</span><div><div class="s-val text-danger">{{ filteredAdminList.filter(u=>u.status!=='active').length }}</div><div class="s-label">停用</div></div></div>
      </div>
      <div class="card">
        <div class="card-header">
          <div><h3>👥 管理员管理</h3><div style="font-size:var(--text-sm);color:var(--text-placeholder);margin-top:2px">一个管理员可以有多个角色组，左侧菜单根据权限自动生成</div></div>
          <div style="display:flex;gap:var(--space-2);align-items:center">
            <input class="form-input" v-model="adminSearch" placeholder="🔍 搜索..." style="width:160px;padding:6px 10px;font-size:var(--text-sm)">
            <button class="btn btn-default btn-sm" @click="loadAllUsers">🔄</button>
            <button class="btn btn-primary btn-sm" @click="openAddAdmin">+ 添加</button>
            <button v-if="selectedAdmins.length" class="btn btn-danger btn-sm" @click="batchDeleteAdmins">🗑️ 删除({{ selectedAdmins.length }})</button>
          </div>
        </div>
        <div class="card-body">
          <div v-if="adminLoading" style="text-align:center;padding:40px;color:var(--text-placeholder)">⏳ 加载中...</div>
          <div v-else>
            <div v-if="filteredAdminList.length" class="table-wrap">
              <table class="data-table">
                <thead><tr>
                  <th style="width:36px;text-align:center"><input type="checkbox" v-model="adminSelectAll" @change="toggleSelectAllAdmins"></th>
                  <th style="width:40px;text-align:center">#</th>
                  <th>用户名</th><th>昵称</th><th>所属组别</th><th>电子邮箱</th><th>手机号</th><th style="width:70px">工号</th><th style="width:80px">状态</th><th>最后登录</th><th style="width:80px;text-align:center;white-space:nowrap">操作</th>
                </tr></thead>
                <tbody>
                  <tr v-for="(u, idx) in filteredAdminList" :key="u.id">
                    <td style="text-align:center"><input type="checkbox" :value="u.id" v-model="selectedAdmins"></td>
                    <td style="text-align:center"><span class="badge" style="background:var(--primary-light);color:var(--primary-dark);min-width:28px;text-align:center">{{ idx+1 }}</span></td>
                    <td style="font-weight:500">{{ u.username }}</td>
                    <td>{{ u.nickname || u.name || '-' }}</td>
                    <td><span class="group-tag">{{ u.group_name || '超级管理组' }}</span></td>
                    <td style="color:var(--text-placeholder)">{{ u.email || '-' }}</td>
                    <td>{{ u.phone || '-' }}</td>
                    <td>{{ u.employee_no || '-' }}</td>
                    <td><span class="badge" :class="u.status==='active'?'completed':'pending'">{{ u.status==='active'?'正常':'停用' }}</span></td>
                    <td style="font-size:var(--text-xs);color:var(--text-placeholder)">{{ u.last_active || '无' }}</td>
                    <td style="text-align:center;white-space:nowrap">
                      <button class="o-abtn edit" @click="openEditAdmin(u)">✏️</button>
                      <button v-if="u.username!=='admin'" class="o-abtn del" @click="deleteAdminUser(u.id)">🗑️</button>
                    </td>
                  </tr>
                </tbody>
              </table>
            </div>
            <div v-else class="empty"><div class="empty-text">暂无管理员</div></div>
          </div>
        </div>
      </div>
    </div>

    <!-- ========== 操作日志 ========== -->
    <div v-if="activeTab==='audit-logs'">
      <div class="card">
        <div class="card-header"><h3>📋 操作日志</h3></div>
        <div class="card-body">
          <!-- 筛选栏 -->
          <div style="display:flex;gap:var(--space-2);margin-bottom:var(--space-3);align-items:center;flex-wrap:wrap">
            <input class="form-input" v-model="logFilterAction" placeholder="操作类型（如 create_order）" style="width:180px;padding:6px 10px;font-size:var(--text-sm)">
            <input class="form-input" v-model="logFilterKeyword" placeholder="🔍 搜索详情..." style="width:180px;padding:6px 10px;font-size:var(--text-sm)">
            <button class="btn btn-default btn-sm" @click="loadLogs">🔍 搜索</button>
            <button class="btn btn-sm" :class="{ 'btn-perm-active': logFilterCategory==='permission' }" @click="logFilterCategory = logFilterCategory==='permission' ? '' : 'permission'; loadLogs()" style="border:1px solid var(--border)">🔐 权限变更</button>
            <button class="btn btn-default btn-sm" @click="logFilterAction='';logFilterKeyword='';logFilterCategory='';loadLogs()">清除筛选</button>
            <button class="btn btn-sm" style="background:var(--danger);color:#fff;margin-left:var(--space-1)" @click="clearLogs(90)">🗑 清除90天前日志</button>
            <span style="color:var(--text-placeholder);font-size:var(--text-xs);margin-left:auto" v-if="logFilterAction||logFilterKeyword">筛选结果：{{ logsTotal }} 条</span>
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
            <div v-else class="empty"><div class="empty-text">{{ logFilterAction||logFilterKeyword||logFilterCategory ? '无匹配结果，请调整筛选条件' : '暂无操作日志' }}</div></div>
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
        </div>
      </div>
    </div>

    <!-- ========== 工艺管理 ========== -->
    <div v-if="activeTab==='process-config'">
      <div class="card" style="margin-bottom:var(--space-5)">
        <div class="card-header"><h3>⚙️ 工艺配置</h3></div>
        <div class="card-body">
          <div v-if="processConfigLoading" style="text-align:center;padding:40px;color:var(--text-placeholder)">⏳ 加载中...</div>
          <div v-else style="display:grid;grid-template-columns:1fr 1fr;gap:24px">
            <!-- 工序报工顺序 -->
            <div>
              <label style="display:block;font-weight:600;font-size:var(--text-base);margin-bottom:var(--space-2)">工序报工顺序</label>
              <div style="display:flex;gap:var(--space-4)">
                <label style="display:flex;align-items:center;gap:var(--space-2);cursor:pointer;font-size:var(--text-base)">
                  <input type="radio" v-model="processConfig.process_order_mode" value="sequential"> 按顺序报工
                </label>
                <label style="display:flex;align-items:center;gap:var(--space-2);cursor:pointer;font-size:var(--text-base)">
                  <input type="radio" v-model="processConfig.process_order_mode" value="out_of_order"> 允许乱序报工
                </label>
              </div>
            </div>
            <!-- 交期预警天数 -->
            <div>
              <label style="display:block;font-weight:600;font-size:var(--text-base);margin-bottom:var(--space-2)">交期预警天数</label>
              <div style="display:flex;align-items:center;gap:var(--space-2)">
                <input class="form-input" type="number" v-model.number="processConfig.delivery_warning_days" min="0" max="365" style="width:100px">
                <span style="color:var(--text-placeholder);font-size:var(--text-base)">天</span>
              </div>
            </div>
            <!-- 报工数量上限 -->
            <div>
              <label style="display:block;font-weight:600;font-size:var(--text-base);margin-bottom:var(--space-3)">报工数量上限</label>
              <div style="display:flex;flex-direction:column;gap:var(--space-3)">
                <label style="display:flex;align-items:center;justify-content:space-between;cursor:pointer;padding:var(--space-2) 12px;background:var(--bg-table-header);border-radius:var(--radius-md)">
                  <span style="font-size:var(--text-base)">上道工序累计上限</span>
                  <span @click.prevent="processConfig.limit_by_prev_process = processConfig.limit_by_prev_process ? 0 : 1" :style="{display:'inline-block',width:'44px',height:'24px',borderRadius:'12px',background:processConfig.limit_by_prev_process?'var(--success)':'var(--border)',position:'relative',transition:'background .2s',cursor:'pointer'}">
                    <span :style="{display:'block',width:'20px',height:'20px',borderRadius:'50%',background:'var(--bg-surface)',position:'absolute',top:'2px',left:processConfig.limit_by_prev_process?'22px':'2px',transition:'left .2s',boxShadow:'0 1px 3px rgba(0,0,0,.2)'}"></span>
                  </span>
                </label>
                <label style="display:flex;align-items:center;justify-content:space-between;cursor:pointer;padding:var(--space-2) 12px;background:var(--bg-table-header);border-radius:var(--radius-md)">
                  <span style="font-size:var(--text-base)">订单总数上限</span>
                  <span @click.prevent="processConfig.limit_by_order_qty = processConfig.limit_by_order_qty ? 0 : 1" :style="{display:'inline-block',width:'44px',height:'24px',borderRadius:'12px',background:processConfig.limit_by_order_qty?'var(--success)':'var(--border)',position:'relative',transition:'background .2s',cursor:'pointer'}">
                    <span :style="{display:'block',width:'20px',height:'20px',borderRadius:'50%',background:'var(--bg-surface)',position:'absolute',top:'2px',left:processConfig.limit_by_order_qty?'22px':'2px',transition:'left .2s',boxShadow:'0 1px 3px rgba(0,0,0,.2)'}"></span>
                  </span>
                </label>
              </div>
            </div>
            <!-- 列表每页条数 -->
            <div>
              <label style="display:block;font-weight:600;font-size:var(--text-base);margin-bottom:var(--space-2)">列表每页条数</label>
              <div style="display:flex;align-items:center;gap:var(--space-2)">
                <input class="form-input" type="number" v-model.number="processConfig.page_size" min="5" max="200" style="width:100px">
                <span style="color:var(--text-placeholder);font-size:var(--text-base)">条/页</span>
              </div>
            </div>
            <!-- 审批设置 -->
            <div>
              <label style="display:block;font-weight:600;font-size:var(--text-base);margin-bottom:var(--space-3)">审批设置</label>
              <label style="display:flex;align-items:center;justify-content:space-between;cursor:pointer;padding:var(--space-2) 12px;background:var(--bg-table-header);border-radius:var(--radius-md)">
                <span style="font-size:var(--text-base)">启用报工审批</span>
                <span @click.prevent="processConfig.approval_enabled = processConfig.approval_enabled ? 0 : 1" :style="{display:'inline-block',width:'44px',height:'24px',borderRadius:'12px',background:processConfig.approval_enabled?'var(--success)':'var(--border)',position:'relative',transition:'background .2s',cursor:'pointer'}">
                  <span :style="{display:'block',width:'20px',height:'20px',borderRadius:'50%',background:'var(--bg-surface)',position:'absolute',top:'2px',left:processConfig.approval_enabled?'22px':'2px',transition:'left .2s',boxShadow:'0 1px 3px rgba(0,0,0,.2)'}"></span>
                </span>
              </label>
            </div>
            <!-- 订单号前缀 -->
            <div>
              <label style="display:block;font-weight:600;font-size:var(--text-base);margin-bottom:var(--space-2)">自动生成订单号前缀</label>
              <input class="form-input" v-model="processConfig.auto_order_no" placeholder="如 YYMMDD 或 PO-" style="width:100%">
            </div>
          </div>
        </div>
      </div>
      <div style="text-align:right;margin-bottom:var(--space-6)">
        <button class="btn btn-primary" @click="saveProcessConfig" :disabled="processConfigSaving" style="min-width:120px">
          {{ processConfigSaving ? '⏳ 保存中...' : '💾 保存配置' }}
        </button>
      </div>
    </div>

    <div v-if="activeTab==='role-groups'">
      <div class="card">
        <div class="card-header">
          <h3>👔 角色组管理</h3>
          <button class="btn btn-primary btn-sm" @click="openAddGroup">+ 新增角色组</button>
        </div>
        <div class="card-body">
          <div v-if="groupLoading" style="text-align:center;padding:40px;color:var(--text-placeholder)">⏳ 加载中...</div>
          <div v-else>
            <div v-if="groups.length" class="table-wrap">
              <table class="data-table">
                <thead><tr><th style="width:40px;text-align:center">#</th><th>名称</th><th>描述</th><th style="width:80px">状态</th><th style="width:120px;text-align:center">操作</th></tr></thead>
                <tbody>
                  <template v-for="(g, idx) in groups" :key="g.id">
                    <tr @click="toggleGroup(g.id)" style="cursor:pointer">
                      <td style="text-align:center"><span class="badge" style="background:var(--primary-light);color:var(--primary-dark);min-width:28px;text-align:center">{{ idx+1 }}</span></td>
                      <td style="font-weight:500">{{ g.name }} <span style="font-size:var(--text-xs-alt);color:var(--text-placeholder)">({{ roleCountByGroup[g.id] || 0 }} 个角色)</span></td>
                      <td style="color:var(--text-placeholder)">{{ g.description || '-' }}</td>
                      <td><span class="badge" :class="g.status==='active'?'completed':'pending'">{{ g.status==='active'?'启用':'停用' }}</span></td>
                      <td style="text-align:center" @click.stop>
                        <button class="o-abtn edit" @click="openEditGroup(g)">✏️</button>
                        <button class="o-abtn del" @click="deleteGroup(g.id)">🗑️</button>
                      </td>
                    </tr>
                    <!-- Expanded: roles within this group -->
                    <tr v-if="expandedGroup===g.id">
                      <td :colspan="5" style="padding:0;background:var(--bg-input)">
                        <div style="padding:var(--space-3) 20px">
                          <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:var(--space-2)">
                            <span style="font-weight:600;font-size:var(--text-sm)">角色列表</span>
                            <button class="btn btn-primary btn-sm" @click="openAddRole(g.id)">+ 添加角色</button>
                          </div>
                          <table v-if="groupRoles.length" class="data-table" style="background:white">
                            <thead><tr><th style="width:40px;text-align:center">#</th><th>名称</th><th>编码</th><th style="width:80px">级别</th><th style="width:80px">状态</th><th style="width:100px;text-align:center">操作</th></tr></thead>
                            <tbody>
                              <tr v-for="(r, ri) in groupRoles" :key="r.id">
                                <td style="text-align:center"><span class="badge" style="background:var(--primary-light);color:var(--primary-dark);min-width:28px;text-align:center">{{ ri+1 }}</span></td>
                                <td style="font-weight:500">{{ r.name }}</td>
                                <td><code style="font-size:var(--text-xs)">{{ r.code }}</code></td>
                                <td>{{ r.level }}</td>
                                <td><span class="badge" :class="r.status==='active'?'completed':'pending'">{{ r.status==='active'?'启用':'停用' }}</span></td>
                                <td style="text-align:center">
                                  <button class="o-abtn edit" @click="openEditRole(r)">✏️</button>
                                  <button class="o-abtn del" @click="deleteRole(r.id)">🗑️</button>
                                </td>
                              </tr>
                            </tbody>
                          </table>
                          <p v-if="!groupRoles.length" style="text-align:center;color:var(--text-placeholder);padding:var(--space-4);font-size:var(--text-sm)">该组暂无角色，点击"添加角色"创建</p>
                        </div>
                      </td>
                    </tr>
                  </template>
                </tbody>
              </table>
            </div>
            <div v-else class="empty"><div class="empty-text">暂无角色组，点击"新增角色组"创建</div></div>
          </div>
        </div>
      </div>
    </div>

    <!-- ========== 角色管理（独立列表） ========== -->
    <div v-if="activeTab==='role-manage'">
      <div class="card">
        <div class="card-header">
          <h3>👥 角色管理</h3>
          <div style="display:flex;gap:var(--space-2);align-items:center">
            <input class="form-input" v-model="roleSearch" placeholder="🔍 搜索名称/编码..." style="width:160px;padding:6px 10px;font-size:var(--text-sm)">
            <select class="form-input" v-model.number="roleAddGroup" style="border:1px solid var(--border);border-radius:var(--radius-md);padding:var(--space-2) 12px;font-size:var(--text-base);background:white;width:150px">
              <option v-for="g in groups" :key="g.id" :value="g.id">{{ g.name }}</option>
            </select>
            <button class="btn btn-primary btn-sm" @click="openAddRole(roleAddGroup)">+ 添加角色</button>
          </div>
        </div>
        <div class="card-body">
          <div v-if="roleLoading" style="text-align:center;padding:40px;color:var(--text-placeholder)">⏳ 加载中...</div>
          <div v-else-if="!filteredRoles.length" style="text-align:center;padding:40px;color:var(--text-placeholder)">{{ roleSearch ? '无匹配角色' : '暂无角色，点击"+ 添加角色"创建' }}</div>
          <div v-else class="table-wrap">
            <table class="data-table" style="min-width:1000px">
              <thead>
                <tr>
                  <th style="width:40px;text-align:center">#</th>
                  <th style="min-width:100px">名称</th>
                  <th style="min-width:120px">编码</th>
                  <th style="min-width:90px">所属组</th>
                  <th style="width:50px">级别</th>
                  <th style="width:85px;white-space:nowrap">状态</th>
                  <th>权限</th>
                  <th style="width:100px;text-align:center;white-space:nowrap">操作</th>
                </tr>
              </thead>
              <tbody>
                <tr v-for="(r, idx) in filteredRoles" :key="r.id">
                  <td style="text-align:center">{{ idx+1 }}</td>
                  <td style="font-weight:500">{{ r.name }}</td>
                  <td><code style="font-size:var(--text-xs)">{{ r.code }}</code></td>
                  <td style="color:var(--text-placeholder);font-size:var(--text-sm)">{{ getGroupName(r.group_id) }}</td>
                  <td>{{ r.level }}</td>
                  <td style="white-space:nowrap"><span class="badge" :class="r.status==='active'?'completed':'pending'">{{ r.status==='active'?'启用':'停用' }}</span></td>
                  <td>
                    <span style="display:flex;flex-wrap:wrap;gap:var(--space-1)">
                      <span v-for="p in formatPerms(r.permissions).slice(0,4)" :key="p" class="badge" style="background:var(--primary-light);color:var(--primary-dark);font-size:var(--text-2xs);border:1px solid var(--primary-light)">{{ p }}</span>
                      <span v-if="formatPerms(r.permissions).length>4" class="badge" style="background:var(--bg-hover);color:var(--text-placeholder);font-size:var(--text-2xs)">+{{ formatPerms(r.permissions).length-4 }}</span>
                    </span>
                  </td>
                  <td style="text-align:center;white-space:nowrap">
                    <button class="o-abtn edit" @click="openEditRole(r)">✏️</button>
                    <button class="o-abtn del" @click="deleteRole(r.id)">🗑️</button>
                  </td>
                </tr>
              </tbody>
            </table>
          </div>
        </div>
      </div>
    </div>

    <!-- ========== 岗位管理 ========== -->
    <div v-if="activeTab==='positions'">
      <div class="card">
        <div class="card-header">
          <h3>💼 岗位管理</h3>
          <button class="btn btn-primary btn-sm" @click="openAddPosition">+ 新增岗位</button>
        </div>
        <div class="card-body">
          <div v-if="positionLoading" style="text-align:center;padding:40px;color:var(--text-placeholder)">⏳ 加载中...</div>
          <div v-else>
            <div v-if="positions.length" class="table-wrap">
              <table class="data-table">
<thead><tr>
  <th style="width:50px">#</th>
  <th>岗位名称</th>
  <th>描述</th>
  <th>关联工序</th>
  <th style="width:80px">状态</th>
  <th style="width:100px;text-align:center;white-space:nowrap">操作</th>
</tr></thead>
                <tbody>
                  <tr v-for="(p, idx) in positions" :key="p.id">
                    <td style="text-align:center"><span class="badge" style="background:var(--primary-light);color:var(--primary-dark);min-width:28px;text-align:center">{{ idx+1 }}</span></td>
                    <td style="font-weight:500">{{ p.name }}</td>
                    <td style="color:var(--text-placeholder)">{{ p.description || '-' }}</td>
                    <td>
                      <span v-if="p.processes && p.processes.length">
                        <span v-for="proc in p.processes" :key="proc.process_id">
                          <span class="badge" style="background:var(--success-light);color:var(--success-dark);border:1px solid var(--success-lighter);margin-right:4px;margin-bottom:3px;display:inline-block;font-size:var(--text-xs-alt)">{{ proc.process_name }}</span>
                        </span>
                      </span>
                      <span v-else style="color:var(--text-placeholder);font-size:var(--text-xs)">未设置</span>
                    </td>
                    <td><span class="badge" :class="p.status==='active'?'completed':'pending'">{{ p.status==='active'?'启用':'停用' }}</span></td>
                    <td style="text-align:center;white-space:nowrap">
                      <button class="o-abtn edit" @click="openEditPosition(p)">✏️</button>
                      <button class="o-abtn del" @click="deletePosition(p.id)">🗑️</button>
                    </td>
                  </tr>
                </tbody>
              </table>
            </div>
            <div v-else class="empty"><div class="empty-text">暂无岗位，点击"新增岗位"创建</div></div>
          </div>
        </div>
      </div>
    </div>


    <!-- ========== 审批配置 ========== -->
    <div v-if="activeTab==='approval-config'">
      <div class="card" style="margin-bottom:var(--space-5)">
        <div class="card-header">
          <h3>✅ 审批工序配置</h3>
          <span style="font-size:var(--text-xs);color:var(--text-placeholder);margin-left:var(--space-3)">
            开启后，对应工序的报工需管理员审批通过才计入完成量
          </span>
        </div>
        <div class="card-body">
          <div v-if="approvalConfigLoading" style="text-align:center;padding:40px;color:var(--text-placeholder)">⏳ 加载中...</div>
          <div v-else-if="!approvalProcesses.length" style="text-align:center;padding:40px;color:var(--text-placeholder)">暂无工序数据</div>
          <div v-else class="table-wrap">
            <table class="data-table">
              <thead>
                <tr>
                  <th style="width:60px">序号</th>
                  <th>工序名称</th>
                  <th style="width:100px">分类</th>
                  <th style="width:120px">审批状态</th>
                  <th style="width:100px">操作</th>
                </tr>
              </thead>
              <tbody>
                <tr v-for="(proc, idx) in approvalProcesses" :key="proc.id">
                  <td>{{ idx + 1 }}</td>
                  <td>
                    <span style="font-weight:600">{{ proc.process_name || proc.name }}</span>
                  </td>
                  <td>
                    <span style="font-size:var(--text-xs);color:var(--text-placeholder)">
                      {{ proc.category || '通用' }}
                    </span>
                  </td>
                  <td>
                    <span v-if="isApprovalRequired(proc.id)" style="color:var(--success);font-weight:600">✅ 需审批</span>
                    <span v-else style="color:var(--text-placeholder)">— 直接通过</span>
                  </td>
                  <td>
                    <button
                      class="btn btn-sm"
                      @click="toggleApproval(proc.id)"
                      :disabled="approvalConfigSaving"
                      :style="{
                        background: isApprovalRequired(proc.id) ? 'var(--danger-light)' : 'var(--success-light)',
                        color: isApprovalRequired(proc.id) ? 'var(--danger)' : 'var(--success)',
                        border: 'none', borderRadius:'var(--radius-md)', padding:'4px 12px',
                        cursor:'pointer', fontWeight:500
                      }"
                    >
                      {{ isApprovalRequired(proc.id) ? '🔓 关闭审批' : '🔒 开启审批' }}
                    </button>
                  </td>
                </tr>
              </tbody>
            </table>
          </div>
        </div>
      </div>
    </div>

    <!-- ========== 权限总览 ========== -->

    <div v-if="activeTab==='perm-matrix'">
      <div v-if="selectedUsers.length" class="card" style="margin-bottom:var(--space-3);background:var(--primary-light);border:1px solid var(--primary-light)">
        <div class="card-body" style="padding:var(--space-3) 16px;display:flex;align-items:center;gap:var(--space-3);flex-wrap:wrap">
          <span style="font-weight:600;font-size:var(--text-sm);color:var(--primary-dark)">已选 {{ selectedUsers.length }} 个用户</span>
          <select v-model="batchAction" class="form-input" style="width:100px;padding:var(--space-1) 8px;font-size:var(--text-sm)">
            <option value="add">追加角色</option>
            <option value="remove">移除角色</option>
            <option value="set">设置为</option>
          </select>
          <select v-model="batchRoleIds" multiple class="form-input" style="min-width:200px;max-height:100px;padding:var(--space-1) 8px;font-size:var(--text-sm)">
            <option v-for="r in allRoles" :key="r.id" :value="r.id">{{ r.name }} ({{ r.group_name || '无组' }})</option>
          </select>
          <button class="btn btn-primary btn-sm" @click="executeBatchRole">执行</button>
          <button class="btn btn-default btn-sm" @click="selectedUsers=[]">取消</button>
        </div>
      </div>
      <div class="card">
        <div class="card-header">
          <h3>🔐 权限总览</h3>
          <div style="display:flex;gap:var(--space-2);align-items:center;flex-wrap:wrap">
            <input class="form-input" v-model="matrixSearch" placeholder="🔍 搜索用户/权限..." style="width:160px;padding:6px 10px;font-size:var(--text-sm)">
            <select class="form-input" v-model="matrixRoleFilter" @change="matrixRoleFilter && loadPermMatrix()" style="width:140px;padding:6px 8px;font-size:var(--text-sm)">
              <option :value="null">全部角色</option>
              <option v-for="r in allRoles" :key="r.id" :value="r.id">{{ r.name }}</option>
            </select>
            <select class="form-input" v-model="matrixPermFilter" @change="matrixPermFilter && loadPermMatrix()" style="width:140px;padding:6px 8px;font-size:var(--text-sm)">
              <option value="">全部权限</option>
              <option v-for="p in allPermissions" :key="p.code" :value="p.code">{{ p.label }}</option>
            </select>
            <button class="btn btn-default btn-sm" @click="matrixRoleFilter=null;matrixPermFilter='';loadPermMatrix()">🔄 全部</button>
          </div>
        </div>
        <div class="card-body">
          <div v-if="matrixLoading" style="text-align:center;padding:40px;color:var(--text-placeholder)">⏳ 加载中...</div>
          <div v-else-if="!filteredMatrix.length" style="text-align:center;padding:40px;color:var(--text-placeholder)">暂无数据</div>
          <div v-else>
            <div style="margin-bottom:var(--space-3);font-size:var(--text-sm);color:var(--text-placeholder)">
              共 {{ filteredMatrix.length }} 个用户
              <span v-if="matrixRoleFilter || matrixPermFilter" style="color:var(--primary-accent)">（已筛选）</span>
            </div>
            <div class="table-wrap">
              <table class="data-table" style="min-width:700px">
                <thead><tr>
                  <th style="width:30px"><input type="checkbox" @change="selectAllUsers"></th>
                  <th style="width:40px">#</th>
                  <th style="min-width:100px">用户</th>
                  <th style="min-width:180px">角色</th>
                  <th style="width:60px">权限数</th>
                  <th style="width:80px">操作</th>
                </tr></thead>
                <tbody>
                  <template v-for="(m, idx) in filteredMatrix" :key="m.user.id">
                    <tr :style="{cursor:'pointer',background:matrixExpandUser===m.user.id?'var(--bg-table-header)':''}" @click="matrixExpandUser = matrixExpandUser===m.user.id ? null : m.user.id">
                      <td><input type="checkbox" :checked="selectedUsers.includes(m.user.id)" @click.stop @change="toggleUserSelect(m.user.id)"></td>
                      <td>{{ idx+1 }}</td>
                      <td><div style="font-weight:500">{{ m.user.name || m.user.username }}</div><div style="font-size:var(--text-xs-alt);color:var(--text-placeholder)">{{ m.user.username }}</div></td>
                      <td><span style="display:flex;flex-wrap:wrap;gap:var(--space-1)"><span v-for="r in m.roles" :key="r.id" class="badge" style="background:var(--primary-light);color:var(--primary-dark);font-size:var(--text-2xs);border:1px solid var(--primary-light)">{{ r.name }}</span></span></td>
                      <td><span class="badge" style="background:var(--success-light);color:var(--success-dark)">{{ m.perm_count }}</span></td>
                      <td><button class="btn btn-default btn-sm" @click.stop="matrixExpandUser = matrixExpandUser===m.user.id ? null : m.user.id">{{ matrixExpandUser===m.user.id ? '收起' : '详情' }}</button></td>
                    </tr>
                    <tr v-if="matrixExpandUser===m.user.id">
                      <td :colspan="6" style="padding:var(--space-3) 20px;background:var(--bg-input)">
                        <div style="font-weight:600;font-size:var(--text-sm);margin-bottom:10px">权限明细 ({{ m.permissions.length }} 项) — 按资源分组</div>
                        <div v-for="g in groupSources(m.permission_sources)" :key="g.label" class="perm-resource-group">
                          <div class="perm-resource-title">📂 {{ g.label }}</div>
                          <div v-for="s in g.items" :key="s.permission" class="perm-item">
                            <span class="perm-item-name">{{ s.permission }}</span>
                            <span :class="sourceBadge(s).cls">{{ sourceBadge(s).label }}: {{ s.source_name }}</span>
                          </div>
                        </div>
                      </td>
                    </tr>
                  </template>
                </tbody>
              </table>
            </div>
          </div>
        </div>
      </div>
    </div>

    <!-- ========== 菜单配置 ========== -->
    <div v-if="activeTab==='menu-config'">
      <div class="card">
        <div class="card-header">
          <h3>📋 菜单权限映射</h3>
          <div style="display:flex;gap:var(--space-2);align-items:center">
            <span v-if="menuPermDirty" style="font-size:var(--text-xs);color:var(--warning);font-weight:600">⚠️ 有未保存的修改</span>
            <button class="btn btn-primary btn-sm" @click="saveAllMenuPerms" :disabled="menuConfigSaving">{{ menuConfigSaving ? '保存中...' : '💾 全部保存' }}</button>
            <button class="btn btn-default btn-sm" @click="openAddMenu">➕ 添加菜单</button>
            <button class="btn btn-default btn-sm" @click="loadMenuPerms">🔄 刷新</button>
          </div>
        </div>
        <div class="card-body">
          <div v-if="menuConfigLoading" style="text-align:center;padding:40px;color:var(--text-placeholder)">⏳ 加载中...</div>
          <div v-else class="table-wrap">
            <table class="data-table">
              <thead><tr>
                <th style="width:30px">#</th>
                <th style="min-width:120px">菜单</th>
                <th style="min-width:200px">所需权限</th>
                <th style="width:70px">状态</th>
                <th style="width:100px">操作</th>
              </tr></thead>
              <tbody>
                <tr v-for="(m, idx) in menuPerms" :key="m.id">
                  <td style="color:var(--text-placeholder);font-size:var(--text-xs)">{{ m.sort_order || idx+1 }}</td>
                  <td style="font-weight:500">{{ m.icon }} {{ m.label || m.page }}</td>
                  <td>
                    <select class="form-input" v-model="m.permission" @change="markMenuDirty()" style="font-size:var(--text-xs);padding:var(--space-1) 8px;width:100%">
                      <option value="">— 公开（所有人可见）—</option>
                      <option v-for="p in permOptions" :key="p" :value="p">{{ p }}</option>
                    </select>
                  </td>
                  <td style="text-align:center"><span class="badge" :class="getMenuStatus(m).cls" style="font-size:var(--text-2xs)">{{ getMenuStatus(m).label }}</span></td>
                  <td style="text-align:center;white-space:nowrap">
                    <button class="btn btn-default btn-sm" @click="markMenuDirty()" style="font-size:var(--text-xs-alt)" title="标记为已修改以便批量保存">✏️</button>
                    <button class="btn btn-danger btn-sm" @click="deleteMenuPerm(m.page)" style="font-size:var(--text-xs-alt)" title="删除">🗑️</button>
                  </td>
                </tr>
              </tbody>
            </table>
          </div>
        </div>
      </div>

      <!-- Add Menu Modal -->
      <div v-if="showMenuModal" class="modal-overlay" >
        <div class="modal" style="max-width:420px">
          <div class="modal-header"><span>添加菜单条目</span><span class="modal-close" @click="showMenuModal=false">&times;</span></div>
          <div class="modal-body">
            <div class="form-group"><label>菜单标识 (page) *</label><input class="form-input" v-model="menuForm.page" placeholder="如 my_menu"></div>
            <div class="form-group"><label>显示名称</label><input class="form-input" v-model="menuForm.label" placeholder="如 我的菜单"></div>
            <div class="form-group"><label>图标 (emoji)</label><input class="form-input" v-model="menuForm.icon" placeholder="如 📋"></div>
            <div class="form-group"><label>排序</label><input class="form-input" v-model.number="menuForm.sort_order" type="number" placeholder="999"></div>
            <div class="form-group"><label>所需权限</label>
              <select class="form-input" v-model="menuForm.permission" style="font-size:var(--text-sm)">
                <option value="">— 公开 —</option>
                <option v-for="p in permOptions" :key="p" :value="p">{{ p }}</option>
              </select>
            </div>
          </div>
          <div class="modal-footer" style="display:flex;justify-content:flex-end;gap:var(--space-2)">
            <button class="btn btn-default" @click="showMenuModal=false">取消</button>
            <button class="btn btn-primary" @click="saveAddMenu">添加</button>
          </div>
        </div>
      </div>
    </div>

    <!-- ========== MODALS ========== -->

    <!-- Admin Add/Edit Modal -->
    <div v-if="showAdminModal" class="modal-overlay" >
      <div class="modal">
        <div class="modal-header"><span>{{ adminModalEdit ? '编辑管理员' : '新增管理员' }}</span><span class="modal-close" @click="showAdminModal=false">&times;</span></div>
        <div class="modal-body">
          <div class="form-group"><label>用户名 *</label><input class="form-input" v-model="adminForm.username" :disabled="adminModalEdit"></div>
          <div class="form-group"><label>姓名 *</label><input class="form-input" v-model="adminForm.name"></div>
          <div class="form-group"><label>昵称</label><input class="form-input" v-model="adminForm.nickname"></div>
          <div class="form-group"><label>所属组别</label><input class="form-input" v-model="adminForm.group_name"></div>
          <div class="form-group"><label>状态</label><select class="form-input" v-model="adminForm.status"><option value="active">启用</option><option value="inactive">停用</option></select></div>
          <div class="form-group"><label>{{ adminModalEdit ? '新密码（留空不修改）' : '密码' }}</label><input class="form-input" v-model="adminForm.password" type="password"></div>
          <div class="form-group"><label>电子邮箱</label><input class="form-input" v-model="adminForm.email"></div>
          <div class="form-group"><label>手机号</label><input class="form-input" v-model="adminForm.phone"></div>
          <div class="form-group"><label>工号</label><input class="form-input" v-model="adminForm.employee_no"></div>
          <div v-if="adminModalEdit" class="form-group">
            <label>角色分配</label>
            <div style="display:flex;flex-wrap:wrap;gap:var(--space-2);margin-top:6px;max-height:180px;overflow-y:auto">
              <label v-for="r in allRoles" :key="r.id" style="display:flex;align-items:center;gap:var(--space-1);padding:var(--space-1) 10px;background:var(--bg-table-header);border:1px solid var(--border-light);border-radius:var(--radius-sm);cursor:pointer;font-size:var(--text-sm);user-select:none">
                <input type="checkbox" :value="r.id" @change="toggleUserRole(r.id)" :checked="userRoleIds.includes(r.id)" style="accent-color:var(--primary);margin:0">
                {{ r.name }}
                <span style="font-size:var(--text-2xs);color:var(--text-placeholder)">({{ r.group_name || '无组' }})</span>
              </label>
              <span v-if="!allRoles.length" style="color:var(--text-placeholder);font-size:var(--text-xs)">暂无角色</span>
            </div>
            <div style="margin-top:6px;display:flex;gap:var(--space-2);align-items:center">
              <span style="font-size:var(--text-xs-alt);color:var(--text-placeholder)">已选 {{ userRoleIds.length }} 项</span>
              <button class="btn btn-primary btn-sm" @click="saveUserRoles(adminForm._id)">💾 保存角色</button>
            </div>
          </div>
        </div>
        <div class="modal-footer">
          <button class="btn btn-default" @click="showAdminModal=false">取消</button>
          <button class="btn btn-primary" @click="saveAdmin">💾 保存</button>
        </div>
      </div>
    </div>

    <!-- Role Group Modal -->
    <div v-if="showGroupModal" class="modal-overlay" >
      <div class="modal">
        <div class="modal-header"><span>{{ groupModalEdit ? '编辑角色组' : '新增角色组' }}</span><span class="modal-close" @click="showGroupModal=false">&times;</span></div>
        <div class="modal-body">
          <div class="form-group"><label>名称 *</label><input class="form-input" v-model="groupForm.name"></div>
          <div class="form-group"><label>父级角色组</label>
            <select class="form-input" v-model.number="groupForm.parent_id">
              <option :value="null">无（顶级）</option>
              <option v-for="g in groups" :key="g.id" :value="g.id" :disabled="groupModalEdit && g.id===groupForm._id">{{ g.name }}</option>
            </select>
          </div>
          <div class="form-group"><label>描述</label><textarea class="form-input" v-model="groupForm.description" rows="2"></textarea></div>
          <div class="form-group"><label>权限配置</label><input class="form-input" v-model="groupForm.permissions" placeholder="JSON格式，如 [&quot;*&quot;]"><div style="font-size:var(--text-2xs);color:var(--text-placeholder);margin-top:2px">* = 全部权限，多个用英文逗号分隔</div></div>
          <div class="form-group"><label>状态</label><select class="form-input" v-model="groupForm.status"><option value="active">启用</option><option value="inactive">停用</option></select></div>
        </div>
        <div class="modal-footer">
          <button class="btn btn-default" @click="showGroupModal=false">取消</button>
          <button class="btn btn-primary" @click="saveGroup">💾 保存</button>
        </div>
      </div>
    </div>

    <!-- Role Modal -->
    <div v-if="showRoleModal" class="modal-overlay" >
      <div class="modal">
        <div class="modal-header"><span>{{ roleModalEdit ? '编辑角色' : '新增角色' }}</span><span class="modal-close" @click="showRoleModal=false">&times;</span></div>
        <div class="modal-body">
          <div class="form-group"><label>名称 *</label><input class="form-input" v-model="roleForm.name"></div>
          <div class="form-group"><label>编码 *</label><input class="form-input" v-model="roleForm.code"></div>
          <div class="form-group"><label>描述</label><input class="form-input" v-model="roleForm.description"></div>
          <div class="form-group">
            <label>所属角色组</label>
            <select class="form-input" v-model.number="roleForm.group_id">
              <option v-for="g in groups" :key="g.id" :value="g.id">{{ g.name }}</option>
            </select>
          </div>
          <div class="form-group"><label>级别</label><input class="form-input" v-model.number="roleForm.level" type="number"></div>
          <div class="form-group">
            <label>权限配置</label>
            <div style="max-height:320px;overflow-y:auto;border:1px solid var(--border-light);border-radius:var(--radius-md)">
              <table style="width:100%;font-size:var(--text-xs);border-collapse:collapse">
                <thead><tr style="background:var(--bg-table-header);position:sticky;top:0;z-index:1">
                  <th style="text-align:left;padding:6px 10px;font-size:var(--text-xs-alt);color:var(--text-placeholder)">资源</th>
                  <th v-for="act in permActionLabels" :key="act.key" style="width:44px;text-align:center;padding:var(--space-1) 2px;font-size:var(--text-2xs);color:var(--text-placeholder)">{{ act.label }}</th>
                </tr></thead>
                <tbody>
                  <tr v-for="p in allPermissions" :key="p.code" style="border-bottom:1px solid var(--bg-hover)">
                    <td style="padding:var(--space-1) 10px;font-weight:500">{{ p.label }}</td>
                    <td v-for="act in (p.actions||[])" :key="act" style="text-align:center;padding:var(--space-1)">
                      <label style="display:block;cursor:pointer;padding:var(--space-1) 0">
                        <input type="checkbox" :value="p.code+':'+act" v-model="selectedPerms" style="accent-color:var(--primary)">
                      </label>
                    </td>
                    <td v-for="n in (6 - (p.actions||[]).length)" :key="'empty'+n" style="text-align:center;color:var(--border-light)">·</td>
                  </tr>
                </tbody>
              </table>
            </div>
            <div style="margin-top:4px;font-size:var(--text-xs-alt);color:var(--text-placeholder)">
              已选 {{ selectedPerms.length }} 项
              <span v-if="selectedPerms.length > 0" style="color:var(--primary);cursor:pointer;margin-left:8px" @click="selectedPerms=[]">清空</span>
            </div>
          </div>
          <div class="form-group"><label>状态</label><select class="form-input" v-model="roleForm.status"><option value="active">启用</option><option value="inactive">停用</option></select></div>
        </div>
        <div class="modal-footer">
          <button class="btn btn-default" @click="showRoleModal=false">取消</button>
          <button class="btn btn-primary" @click="saveRole">💾 保存</button>
        </div>
      </div>
    </div>

    <!-- Position Modal -->
    <div v-if="showPositionModal" class="modal-overlay" >
      <div class="modal">
        <div class="modal-header"><span>{{ positionModalEdit ? '编辑岗位' : '新增岗位' }}</span><span class="modal-close" @click="showPositionModal=false">&times;</span></div>
        <div class="modal-body">
          <div class="form-group"><label>岗位名称 *</label><input class="form-input" v-model="positionForm.name" placeholder="如：焊接工、质检员"></div>
          <div class="form-group"><label>描述</label><input class="form-input" v-model="positionForm.description" placeholder="岗位职责描述"></div>
          <div class="form-group"><label>状态</label><select class="form-input" v-model="positionForm.status"><option value="active">启用</option><option value="inactive">停用</option></select></div>
          <div class="form-group"><label>可报工工序</label>
            <div style="display:flex;flex-wrap:wrap;gap:var(--space-2);margin-top:8px">
              <label v-for="proc in allProcesses" :key="proc.id"
                :style="{display:'flex',alignItems:'center',gap:'6px',padding:'6px 12px',borderRadius:'6px',cursor:'pointer',fontSize:'13px',border:'1px solid '+(positionForm.process_ids.includes(proc.id)?'var(--primary)':'var(--border-light)'),background:positionForm.process_ids.includes(proc.id)?'var(--primary-light)':'var(--bg-surface)',color:positionForm.process_ids.includes(proc.id)?'var(--primary-dark)':'var(--text-secondary)'}">
                <input type="checkbox" :checked="positionForm.process_ids.includes(proc.id)" @change="toggleProcessInPosition(proc.id)" style="accent-color:var(--primary)">
                {{ proc.process_name || proc.name }}
              </label>
            </div>
          </div>
        </div>
        <div class="modal-footer">
          <button class="btn btn-default" @click="showPositionModal=false">取消</button>
          <button class="btn btn-primary" @click="savePosition">💾 保存</button>
        </div>
      </div>
    </div>
  </div>
</template>

<script>
import { useSettings } from '@/composables/useSettings.js'

export default {
  setup() {
    return useSettings()
  }
}
</script>
