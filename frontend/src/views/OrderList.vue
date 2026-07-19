<!-- OrderList.vue -->
<template>
<div style="padding:var(--space-6)">
    <div class="summary-bar">
      <div class="summary-item"><span class="s-icon">📋</span><div><div class="s-val">{{ total }}</div><div class="s-label">订单总数</div></div></div>
      <div class="summary-item"><span class="s-icon">⏳</span><div><div class="s-val" style="color:var(--warning)">{{ pendingCount }}</div><div class="s-label">待生产</div></div></div>
      <div class="summary-item"><span class="s-icon">🔄</span><div><div class="s-val text-primary">{{ producingCount }}</div><div class="s-label">生产中</div></div></div>
      <div class="summary-item"><span class="s-icon">✅</span><div><div class="s-val text-success">{{ completedCount }}</div><div class="s-label">已完成</div></div></div>
    </div>

    <div class="card">
      <div class="card-header">
        <h3>📋 订单管理</h3>
        <div class="filter-bar">
          <select class="filter-select" v-model="archiveFilter" @change="archiveChange">
            <option value="active">未完成订单</option>
            <option value="completed">已完成订单</option>
            <option value="all">全部订单</option>
          </select>
          <select class="filter-select" v-model="filterStatus" @change="statusChange">
            <option value="">全部状态</option>
            <option value="pending">待生产</option>
            <option value="producing">生产中</option>
            <option value="completed">已完成</option>
            <option value="cancelled">已取消</option>
            <option value="paused">已暂停</option>
          </select>
          <select class="filter-select" v-model="filterCustomer" @change="customerChange">
            <option value="">全部客户</option>
            <option v-for="cust in customers" :key="cust.id" :value="cust.name">{{ cust.name }}</option>
          </select>
          <div class="search-box">
            <span>🔍</span>
            <input v-model="searchKeyword" placeholder="搜索订单号/产品/客户..." @input="debouncedSearch" @keyup.enter="searchAndLoad">
          </div>
          <button class="btn btn-default btn-sm" @click="searchAndLoad">搜索</button>
          <button class="btn btn-warning btn-sm" @click="openCompletionFocus">🎯 集中完工</button>
          <button class="btn btn-primary btn-sm" @click="openAdd">+ 新建订单</button>
          <button class="btn btn-sm trash-btn" @click="showTrash=true;loadTrash()">🗑️ 回收站</button>
        </div>
      </div>
      <div class="card-body">
        <div class="table-wrap">
          <table v-if="orders.length" class="data-table order-table">
            <thead>
              <tr>
                <th class="td-expand"></th>
                <th class="td-order-no">订单号</th>
                <th class="td-customer">客户</th>
                <th class="td-product">产品</th>
                <th class="td-progress">进度</th>
                <th class="td-qty">数量</th>
                <th class="td-status">状态</th>
                <th class="td-deadline">交期</th>
                <th class="td-actions">操作</th>
              </tr>
            </thead>
            <tbody>
              <template v-for="o in orders" :key="o.id">
                <tr @click="toggleExpandAndLoad(o.id)" style="cursor:pointer" :class="{ 'row-expanded': expandedId === o.id }">
                  <td class="td-expand">{{ expandedId === o.id ? '▼' : '▶' }}</td>
                  <td class="td-order-no"><code>{{ o.order_no }}</code></td>
                  <td class="td-customer">{{ o.customer_name || o.customer || '-' }}</td>
                  <td class="td-product">{{ o.product_name }}<span v-if="o.product_code" class="td-product-code">({{ o.product_code }})</span></td>
                  <td class="td-progress">
                    <div class="progress-wrap">
                      <div class="progress-bar">
                        <div class="progress-bar-fill" :style="{width:pct(o)+'%',background:pct(o)===100?'var(--success)':pct(o)>50?'var(--primary)':'var(--warning)'}"></div>
                      </div>
                      <span class="progress-pct">{{ pct(o) }}%</span>
                      <span v-if="o.scrapped" class="progress-scrap">废{{ scrapPct(o) }}%</span>
                    </div>
                  </td>
                  <td class="td-qty">{{ o.quantity }}</td>
                  <td style="text-align:center;white-space:nowrap"><span class="badge" :class="statusMap[o.status]?.cls||'badge-info'" style="font-size:var(--text-xs-alt)">{{ statusMap[o.status]?.label||o.status }}</span></td>
                  <td style="font-size:var(--text-xs);white-space:nowrap">{{ o.deadline || '-' }}</td>
                  <td style="text-align:center">
                    <div class="o-actions" style="justify-content:center" @click.stop>
                      <span class="o-abtn" style="color:var(--primary-accent)" @click="openProgress(o)" title="工件进度">📊</span>
                      <span v-if="!isCompletedOrder(o)" class="o-abtn o-edit" @click="openEdit(o)" title="编辑">✏️</span>
                      <span class="o-abtn text-success" @click="openQrPrint(o)" title="打印二维码">🖨️</span>
                      <span v-if="!isCompletedOrder(o)" class="o-abtn" style="color:var(--warning)" @click="openRework(o)" title="申请返工">🔧</span>
                      <span v-if="!isCompletedOrder(o)" class="o-abtn o-del" @click="del(o)" title="删除">🗑️</span>
                      <span v-else class="o-abtn" style="color:var(--primary)" @click="reopenOrder(o)" title="重新打开">🔓</span>
                    </div>
                  </td>
                </tr>
                <!-- 展开详情 -->
                <tr v-if="expandedId === o.id" style="background:var(--bg-table-header)">
                  <td colspan="9" style="padding:var(--space-3) 16px">
                    <div style="display:flex;gap:var(--space-4);flex-wrap:wrap;align-items:center">
                      <span v-if="o.processes && o.processes.length" style="font-size:var(--text-sm);color:var(--text-placeholder)">工序:</span>
                      <span v-for="p in (o.processes||[])" :key="p.id" class="badge" style="font-size:var(--text-xs-alt)"
                        :class="p.status==='completed'?'badge-success':p.status==='producing'?'badge-warning':'badge-secondary'">
                        {{ p.seq_order }}.{{ p.process_name }}
                        <template v-if="p.completed"> ✓{{ p.completed }}</template>
                      </span>
                      <span v-if="!o.processes || !o.processes.length" style="font-size:var(--text-sm);color:var(--text-placeholder)">暂无工序</span>
                    </div>
                    <div v-if="o.route_name" style="font-size:var(--text-xs);color:var(--text-placeholder);margin-top:4px">路线：{{ o.route_name }}</div>
                    <div v-if="o.remark" style="font-size:var(--text-xs);color:var(--text-placeholder);margin-top:2px">备注：{{ o.remark }}</div>
                    
                    <!-- 附件区 -->
                    <div style="margin-top:12px;padding-top:12px;border-top:1px solid var(--border-light)">
                      <div style="display:flex;align-items:center;justify-content:space-between;margin-bottom:var(--space-2)">
                        <span style="font-size:var(--text-sm);font-weight:600;color:var(--text-secondary)">📎 附件 ({{ getAttachments(o.id).length }})</span>
                        <label v-if="!isCompletedOrder(o)" style="cursor:pointer;display:inline-flex;align-items:center;gap:var(--space-1);padding:var(--space-1) 10px;font-size:var(--text-xs);border-radius:var(--radius-sm);background:var(--primary-light);color:var(--primary);border:1px solid var(--primary-light);white-space:nowrap">
                          + 上传
                          <input type="file" ref="uploadInputRef" style="display:none" @change="handleAttachmentUpload(o.id, $event)" accept="image/*,.pdf,.doc,.docx,.xls,.xlsx,.dwg,.dxf,.zip,.rar">
                        </label>
                        <span v-else style="font-size:var(--text-xs);color:var(--text-placeholder)">已归档只读</span>
                      </div>
                      <div v-if="isAttachmentsLoading(o.id)" style="font-size:var(--text-xs);color:var(--text-placeholder);padding:var(--space-2)">⏳ 加载中...</div>
                      <div v-else-if="getAttachments(o.id).length" style="display:flex;flex-wrap:wrap;gap:var(--space-2)">
                        <div v-for="att in getAttachments(o.id)" :key="att.id"
                          style="display:flex;align-items:center;gap:var(--space-2);padding:6px 10px;background:white;border:1px solid var(--border-light);border-radius:var(--radius-md);font-size:var(--text-xs);white-space:nowrap">
                          <span style="font-size:var(--text-lg)">{{ getFileIcon(att.file_type) }}</span>
                          <div style="min-width:0">
                            <span @click.stop="downloadAttachment(att.id)" style="color:var(--primary);cursor:pointer;font-weight:500;display:block;overflow:hidden;text-overflow:ellipsis;max-width:200px" :title="att.file_name">{{ att.file_name }}</span>
                            <span style="font-size:var(--text-2xs);color:var(--text-placeholder)">{{ formatFileSize(att.file_size) }} · {{ att.created_at?.slice(0,16) }}</span>
                          </div>
                          <span v-if="!isCompletedOrder(o)" @click.stop="delAttachment(att.id, o.id)" title="删除" style="cursor:pointer;opacity:0.5;font-size:var(--text-base);flex-shrink:0">🗑️</span>
                        </div>
                      </div>
                      <div v-else style="font-size:var(--text-xs);color:var(--text-placeholder);padding:var(--space-2)">暂无附件</div>
                    </div>
                  </td>
                </tr>
              </template>
            </tbody>
          </table>
          <div v-else class="empty"><div class="empty-icon">📋</div><div class="empty-text">暂无订单数据</div></div>
        </div>
        <!-- 分页 -->
        <div v-if="total > limit" style="display:flex;justify-content:center;align-items:center;gap:var(--space-3);padding:var(--space-4) 0">
          <button class="btn btn-default btn-sm" @click="prevPage" :disabled="page <= 1">上一页</button>
          <span style="font-size:var(--text-sm);color:var(--text-placeholder)">第 {{ page }} / {{ Math.ceil(total/limit) }} 页，共 {{ total }} 条</span>
          <button class="btn btn-default btn-sm" @click="nextPage" :disabled="page * limit >= total">下一页</button>
        </div>
      </div>
    </div>

    <!-- 新增/编辑模态框 -->
    <div v-if="showModal" class="modal-overlay" >
      <div class="modal" style="max-width:780px">
        <div class="modal-header">
          <span>{{ modalEdit ? '编辑订单' : '新建订单' }}</span>
          <span class="modal-close" @click="showModal=false">&times;</span>
        </div>
        <div class="modal-body">
          <div class="form-row">
            <div class="form-col" style="flex:2">
              <div class="form-group"><label>订单号</label><input class="form-input" v-model="form.order_no" placeholder="自动生成" :disabled="!modalEdit"></div>
            </div>
            <div class="form-col" style="flex:2">
              <div class="form-group"><label>客户</label>
                <select class="form-input" v-model="form.customer_id" @change="onCustomerChange">
                  <option value="">-- 请选择客户 --</option>
                  <option v-for="c in customers" :key="c.id" :value="c.id">{{ c.name }}</option>
                </select>
              </div>
            </div>
          </div>
          <div class="form-row">
            <div class="form-col"><div class="form-group"><label>产品名称 *</label><input class="form-input" v-model="form.product_name" placeholder="如：底壳"></div></div>
            <div class="form-col"><div class="form-group"><label>数量 *</label><input class="form-input" v-model.number="form.quantity" type="number" min="1" placeholder="生产数量"></div></div>
          </div>
          <!-- 产品编码搜索 — 独占整行 -->
          <div class="form-group" style="margin-bottom:12px"><label>产品编码搜索</label>
            <div class="combobox" ref="cbContainer" style="width:100%">
              <input class="form-input combobox-input" v-model="productSearch" 
                placeholder="🔍 输入编码或产品名搜索，支持键盘 ↑↓ 选择，Enter 确认..."
                style="font-size:15px;padding:12px 14px"
                @focus="onProductSearchFocus"
                @input="onProductSearchInput"
                @keydown.escape="showProductDropdown=false"
                @keydown.enter.prevent="selectProductByEnter"
                @keydown.down.prevent="moveProductCursor(1)"
                @keydown.up.prevent="moveProductCursor(-1)"
                autocomplete="off">
              <span v-if="productSearch" class="combobox-clear" @click="clearProductSearch">✕</span>
              <div class="combobox-dropdown" v-if="showProductDropdown && productSearchResults.length" 
                @mousedown.prevent>
                <div v-for="(p, i) in productSearchResults" :key="p.id"
                  class="combobox-item"
                  :class="{ active: productCursor === i }"
                  @click="selectProduct(p)"
                  @mouseenter="productCursor = i">
                  <code style="font-size:var(--text-xs);font-weight:600;color:var(--primary);min-width:130px">{{ p.product_code }}</code>
                  <span style="flex:1;font-size:var(--text-sm)">{{ p.product_name }} <span style="color:var(--text-placeholder);font-size:var(--text-2xs)">{{ p.model||'' }} {{ p.spec||'' }}</span></span>
                  <span class="badge" style="font-size:var(--text-2xs)" :class="p.category==='结构件'?'badge-info':'badge-warning'">{{ p.category }}</span>
                </div>
              </div>
              <div class="combobox-dropdown" v-if="showProductDropdown && !productSearch && recentProducts.length" 
                @mousedown.prevent>
                <div class="combobox-group-label">📌 最近使用</div>
                <div v-for="(p, i) in recentProducts" :key="'r'+p.id"
                  class="combobox-item" :class="{ active: productCursor === i }"
                  @click="selectProduct(p)" @mouseenter="productCursor = i">
                  <code style="font-size:var(--text-xs);font-weight:600;color:var(--primary);min-width:130px">{{ p.product_code }}</code>
                  <span style="flex:1;font-size:var(--text-sm)">{{ p.product_name }} <span style="color:var(--text-placeholder);font-size:var(--text-2xs)">{{ p.model||'' }} {{ p.spec||'' }}</span></span>
                  <span class="badge" style="font-size:var(--text-2xs)" :class="p.category==='结构件'?'badge-info':'badge-warning'">{{ p.category }}</span>
                </div>
              </div>
            </div>
          </div>
          <!-- 产品确认卡片 -->
          <div v-if="form.product_code" style="background:#ECFDF5;border:1px solid #6EE7B7;border-radius:12px;padding:12px 16px;margin-bottom:14px;display:flex;flex-wrap:wrap;align-items:center;gap:8px 16px">
            <span style="font-weight:700;color:#059669;font-size:15px">✅ 已选择：<code style="background:#D1FAE5;padding:2px 8px;border-radius:4px;font-size:14px">{{ form.product_code }}</code></span>
            <span v-if="form.model" style="font-size:13px;color:#374151"><b>型号</b> {{ form.model }}</span>
            <span v-if="form.spec" style="font-size:13px;color:#374151"><b>规格</b> {{ form.spec }}</span>
            <span v-if="form.style" style="font-size:13px;color:#374151"><b>类型</b> {{ form.style }}</span>
            <span v-if="form.upper_opening" style="font-size:13px;color:#374151"><b>上开</b> {{ form.upper_opening }}</span>
            <span v-if="form.plate_thickness" style="font-size:13px;color:#374151"><b>板厚</b> {{ form.plate_thickness }}mm</span>
            <span v-if="form.category" class="badge" style="font-size:11px" :class="form.category==='结构件'?'badge-info':'badge-warning'">{{ form.category }}</span>
            <span v-if="form.price" style="font-size:13px;color:#374151"><b>工价</b> ¥{{ form.price }}</span>
            <span v-if="form.weight" style="font-size:13px;color:#374151"><b>重量</b> {{ form.weight }}kg</span>
          </div>
          <div class="form-row">
            <div class="form-col"><div class="form-group"><label>计划开始</label><input class="form-input" v-model="form.plan_start" type="date"></div></div>
            <div class="form-col"><div class="form-group"><label>计划结束</label><input class="form-input" v-model="form.plan_end" type="date"></div></div>
          </div>
          <div class="form-row">
            <div class="form-col"><div class="form-group"><label>交期</label><input class="form-input" v-model="form.deadline" type="date"></div></div>
            <div class="form-col"><div class="form-group"><label>工序路线</label>
              <div class="combobox" style="width:100%">
                <input class="form-input combobox-input" v-model="routeSearch"
                  placeholder="&#128269; 输入路线名称搜索..."
                  @focus="onRouteSearchFocus"
                  @input="onRouteSearchInput"
                  @keydown.escape="showRouteDropdown=false"
                  @keydown.enter.prevent="selectRouteByEnter"
                  @keydown.down.prevent="moveRouteCursor(1)"
                  @keydown.up.prevent="moveRouteCursor(-1)"
                  autocomplete="off">
                <span v-if="routeSearch" class="combobox-clear" @click="clearRouteSearch">&#10005;</span>
                <div class="combobox-dropdown" v-if="showRouteDropdown && filteredRoutes.length"
                  @mousedown.prevent>
                  <div v-for="(r, i) in filteredRoutes" :key="r.id"
                    class="combobox-item"
                    :class="{ active: routeCursor === i }"
                    @click="selectRoute(r)"
                    @mouseenter="routeCursor = i">
                    <code style="font-size:var(--text-sm);font-weight:600;color:var(--primary);min-width:60px">#{{ r.id }}</code>
                    <span style="flex:1;font-size:var(--text-sm)">{{ r.name }}</span>
                  </div>
                </div>
                <div class="combobox-dropdown" v-if="showRouteDropdown && !routeSearch && !filteredRoutes.length"
                  @mousedown.prevent>
                  <div class="combobox-item" style="color:var(--text-placeholder);justify-content:center">暂无工序路线数据</div>
                </div>
              </div>
            </div></div>
          </div>
          <div class="form-row">
            <div class="form-col"><div class="form-group"><label>产线</label>
              <select class="form-input" v-model="form.production_line_id">
                <option value="">-- 自动分配 --</option>
                <option v-for="pl in productionLines" :key="pl.id" :value="pl.id">{{ pl.name }} (日产能: {{ pl.capacity_per_day || '-' }})</option>
              </select>
            </div></div>
            <div class="form-col" v-if="modalEdit">
              <div class="form-group"><label>状态</label>
                <select class="form-input" v-model="form.status">
                  <option value="pending">待生产</option>
                  <option value="producing">生产中</option>
                  <option value="completed">已完成</option>
                  <option value="cancelled">已取消</option>
                  <option value="paused">已暂停</option>
                </select>
              </div>
            </div>
          </div>
          <div class="form-group"><label>备注</label><textarea class="form-input" v-model="form.remark" rows="2" placeholder="备注信息"></textarea></div>

          <!-- 订单物料配方（编辑模式） - 创建时无需操作，系统会自动从产品BOM复制 -->
          <div v-if="modalEdit" style="margin-top:16px;padding-top:16px;border-top:1px solid var(--border-light)">
            <label style="font-weight:600;font-size:var(--text-sm);margin-bottom:8px;display:block">📦 物料配方 <span style="font-weight:normal;color:var(--text-muted);font-size:var(--text-xs)">（每件用量，可覆盖产品默认BOM）</span></label>
            <div v-if="orderMaterials.length" style="margin-bottom:8px">
              <div v-for="om in orderMaterials" :key="om.id" style="display:flex;align-items:center;gap:6px;padding:4px 0;font-size:13px">
                <span style="flex:1">{{ om.material_name }} {{ om.material_spec || '' }}</span>
                <span style="color:var(--text-muted);white-space:nowrap">x{{ om.quantity_per_unit }}/件</span>
                <span v-if="om.process_name" style="color:var(--primary);white-space:nowrap">@{{ om.process_name }}</span>
                <button @click="removeOrderMaterial(om.id)" style="border:none;background:none;color:var(--danger);cursor:pointer;font-size:16px">&times;</button>
              </div>
            </div>
            <div v-else style="color:var(--text-muted);font-size:var(--text-xs);margin-bottom:8px">暂无物料配方（可从对应产品的BOM自动继承）</div>
            <div style="display:flex;gap:6px;align-items:center">
              <select v-model="orderMatForm.material_id" style="flex:1;padding:4px;border:1px solid var(--border-light);border-radius:4px;font-size:13px">
                <option value="">- 选择物料 -</option>
                <option v-for="m in materialOptions" :key="m.id" :value="m.id">{{ m.name }} {{ m.spec||'' }} [{{ m.material_type||'' }}]</option>
              </select>
              <input v-model="orderMatForm.quantity_per_unit" type="number" step="0.1" min="0.1" placeholder="用量/件" style="width:70px;padding:4px;border:1px solid var(--border-light);border-radius:4px;font-size:13px">
              <button @click="addOrderMaterial" class="btn btn-sm" style="background:var(--primary);color:#fff;border:none;padding:4px 8px;border-radius:4px;cursor:pointer;white-space:nowrap">+ 添加</button>
            </div>
          </div>
        </div>
        <div class="modal-footer">
          <button class="btn btn-default" @click="showModal=false">取消</button>
          <button class="btn btn-primary" @click="save">保存</button>
        </div>
      </div>
    </div>

    <!-- 集中完工看板 -->
    <div v-if="showCompletionFocus" class="modal-overlay" >
      <div class="modal" style="max-width:1100px;width:96%">
        <div class="modal-header">
          <span>🎯 集中完工看板 — 先下达先收尾</span>
          <span class="modal-close" @click="showCompletionFocus=false">&times;</span>
        </div>
        <div class="modal-body" style="max-height:72vh;overflow:auto">
          <div v-if="completionFocusLoading" style="text-align:center;padding:40px;color:var(--text-placeholder)">⏳ 加载中...</div>
          <div v-else>
            <div class="summary-bar" style="margin-bottom:var(--space-4);flex-wrap:wrap">
              <div class="summary-item"><span class="s-icon">📋</span><div><div class="s-val">{{ completionFocusData.summary?.total || 0 }}</div><div class="s-label">未完工订单</div></div></div>
              <div class="summary-item"><span class="s-icon">🏁</span><div><div class="s-val text-success">{{ completionFocusData.summary?.tail || 0 }}</div><div class="s-label">尾数清理</div></div></div>
              <div class="summary-item"><span class="s-icon">⚠️</span><div><div class="s-val" style="color:var(--danger)">{{ completionFocusData.summary?.stuck || 0 }}</div><div class="s-label">存在滞留</div></div></div>
              <div class="summary-item"><span class="s-icon">🔄</span><div><div class="s-val" style="color:var(--warning)">{{ completionFocusData.summary?.partial || 0 }}</div><div class="s-label">部分完工</div></div></div>
              <div class="summary-item"><span class="s-icon">🟦</span><div><div class="s-val" style="color:var(--primary)">{{ completionFocusData.summary?.exception || 0 }}</div><div class="s-label">例外订单</div></div></div>
            </div>
            <div class="focus-control-bar">
              <div>
                <div style="font-weight:700;margin-bottom:4px">当前模式：{{ completionFocusModeLabel(completionFocusConfig.mode) }}</div>
                <div style="font-size:var(--text-xs);color:var(--text-placeholder)">关闭=不提示不拦截；软提示=提示但允许；强拦截=普通员工不可继续报工。</div>
              </div>
              <div class="focus-mode-buttons">
                <button
                  v-for="option in completionFocusModeOptions()"
                  :key="option.value"
                  class="btn btn-sm"
                  :class="completionFocusConfig.mode===option.value ? (option.button_class || 'btn-primary') : 'btn-default'"
                  @click="setCompletionFocusMode(option.value)"
                >{{ option.label }}</button>
              </div>
            </div>
            <div class="focus-rule-note">
              管控原则：同路线/同产品下，移动端扫码优先提示或拦截后下达订单；例外订单在有效期内不参与强拦截优先级判断。
            </div>
            <table v-if="completionFocusData.items?.length" class="data-table focus-table">
              <thead>
                <tr><th>优先级</th><th>订单</th><th>产品/路线</th><th>进度</th><th>优先处理工序</th><th>交期风险</th><th>建议</th><th>例外/操作</th></tr>
              </thead>
              <tbody>
                <tr v-for="(item, idx) in completionFocusData.items" :key="item.order_id">
                  <td style="text-align:center">
                    <div class="focus-rank">#{{ idx + 1 }}</div>
                    <div class="focus-label" :class="'focus-' + item.focus_type">{{ item.focus_label }}</div>
                  </td>
                  <td>
                    <code>{{ item.order_no }}</code>
                    <div style="font-size:var(--text-xs);color:var(--text-placeholder)">下达：{{ item.created_at?.slice(0,16) || '-' }}</div>
                    <div style="font-size:var(--text-xs);color:var(--text-placeholder)">客户：{{ item.customer || '-' }}</div>
                  </td>
                  <td>
                    <div>{{ item.product_name }}</div>
                    <div style="font-size:var(--text-xs);color:var(--text-placeholder)">{{ item.product_code || '-' }}</div>
                    <div style="font-size:var(--text-xs);color:var(--primary)">路线：{{ item.route_name || '-' }}</div>
                  </td>
                  <td>
                    <div style="display:flex;align-items:center;gap:8px">
                      <div class="progress-bar" style="height:7px;flex:1;background:var(--border-light);border-radius:4px;overflow:hidden">
                        <div :style="{width:item.completion_pct+'%',height:'100%',background:item.completion_pct>=70?'var(--success)':'var(--primary)'}"></div>
                      </div>
                      <span style="font-size:var(--text-xs);white-space:nowrap">{{ item.completion_pct }}%</span>
                    </div>
                    <div style="font-size:var(--text-xs);color:var(--text-placeholder);margin-top:4px">
                      已完成 {{ item.completed_workpieces }} / 剩余 {{ item.remaining_workpieces }}，滞留 {{ item.stuck_workpieces }}
                    </div>
                  </td>
                  <td>
                    <div style="font-weight:600">{{ item.priority_process_name || '-' }}</div>
                    <div style="font-size:var(--text-xs);color:var(--text-placeholder)">积压 {{ item.priority_backlog || 0 }} 件，滞留 {{ item.priority_stuck || 0 }} 件</div>
                  </td>
                  <td>
                    <span class="badge" :class="item.risk_level==='overdue'||item.risk_level==='high'?'badge-danger':item.risk_level==='medium'?'badge-warning':'badge-success'">
                      {{ riskLabel(item.risk_level) }}
                    </span>
                    <div style="font-size:var(--text-xs);color:var(--text-placeholder);margin-top:4px">交期：{{ item.deadline || '-' }}</div>
                  </td>
                  <td style="font-size:var(--text-xs);color:var(--text-secondary);line-height:1.5">
                    <div v-for="tip in (item.recommendations || []).slice(0,2)" :key="tip">• {{ tip }}</div>
                  </td>
                  <td style="font-size:var(--text-xs);min-width:110px">
                    <div v-if="item.is_exception" style="margin-bottom:6px">
                      <span class="focus-label focus-exception">例外：{{ item.exception_reason }}</span>
                      <div style="color:var(--text-placeholder);margin-top:4px">到期：{{ item.exception_expires_at || '长期' }}</div>
                    </div>
                    <button v-if="!item.is_exception" class="btn btn-sm btn-default" @click="openFocusException(item)">设为例外</button>
                    <button v-else class="btn btn-sm btn-danger" @click="cancelFocusException(item)">取消例外</button>
                  </td>
                </tr>
              </tbody>
            </table>
            <div v-else style="text-align:center;padding:28px;color:var(--text-placeholder)">当前没有需要集中完工管控的订单</div>
          </div>
        </div>
      </div>
    </div>

    <!-- 集中完工例外弹窗 -->
    <div v-if="showFocusExceptionModal" class="modal-overlay" >
      <div class="modal" style="max-width:460px;width:95%">
        <div class="modal-header">
          <span>🟦 设置例外订单 — {{ focusExceptionOrder?.order_no || '' }}</span>
          <span class="modal-close" @click="showFocusExceptionModal=false">&times;</span>
        </div>
        <div class="modal-body">
          <div class="form-group">
            <label>例外原因 *</label>
            <select class="form-input" v-model="focusExceptionForm.reason">
              <option v-for="reason in completionFocusConfig.reason_options" :key="reason" :value="reason">{{ reason }}</option>
            </select>
          </div>
          <div class="form-group">
            <label>有效期 *</label>
            <input class="form-input" type="datetime-local" v-model="focusExceptionForm.expires_at">
          </div>
          <div class="form-group">
            <label>说明</label>
            <textarea class="form-input" rows="3" v-model="focusExceptionForm.detail" placeholder="如：缺料待采购、设备维修预计明天恢复、客户急单插单等"></textarea>
          </div>
          <div class="focus-rule-note">例外有效期内，该订单不会作为强拦截的优先订单；到期后自动恢复管控。</div>
        </div>
        <div class="modal-footer">
          <button class="btn btn-default" @click="showFocusExceptionModal=false">取消</button>
          <button class="btn btn-primary" @click="saveFocusException">保存例外</button>
        </div>
      </div>
    </div>

    <!-- 申请返工弹窗 -->
    <div v-if="showReworkModal" class="modal-overlay" >
      <div class="modal" style="max-width:450px;width:95%">
        <div class="modal-header">
          <span>🔧 申请返工 — {{ reworkOrder?.order_no || '' }}</span>
          <span class="modal-close" @click="showReworkModal=false">&times;</span>
        </div>
        <div class="modal-body">
          <div style="margin-bottom:12px;font-size:var(--text-sm)">
            <b>产品:</b> {{ reworkOrder?.product_name }} | <b>数量:</b> {{ reworkOrder?.quantity }}
          </div>
          <div class="form-group"><label>返工工序 *</label>
            <select class="form-input" v-model="reworkForm.process_id">
              <option value="">-- 请选择工序 --</option>
              <option v-for="p in (reworkOrder?.processes || [])" :key="p.id" :value="p.id">{{ p.seq_order }}. {{ p.process_name }}</option>
            </select>
          </div>
          <div class="form-group"><label>返工数量 *</label>
            <input class="form-input" v-model.number="reworkForm.quantity" type="number" min="1" :max="reworkOrder?.quantity || 1" placeholder="返工件数">
          </div>
          <div class="form-group"><label>返工原因 *</label>
            <textarea class="form-input" v-model="reworkForm.reason" rows="2" placeholder="如：焊接缺陷、尺寸超差..."></textarea>
          </div>
        </div>
        <div class="modal-footer">
          <button class="btn btn-default" @click="showReworkModal=false">取消</button>
          <button class="btn btn-primary" @click="submitRework">提交返工</button>
        </div>
      </div>
    </div>

    <!-- 二维码打印弹窗 -->
    <div v-if="showQrPrint" class="modal-overlay" >
      <div class="modal qr-modal-lg">
        <div class="modal-header">
          <span>🖨️ 二维码标签打印 — {{ qrPrintOrder?.order_no || '' }}</span>
          <span class="modal-close" @click="showQrPrint=false">&times;</span>
        </div>
        <div class="modal-body" style="padding:var(--space-5)">
          <!-- 订单信息 -->
          <div v-if="qrPrintOrder" class="qr-print-order-info">
            <span>📋 <strong>{{ qrPrintOrder.order_no }}</strong></span>
            <span>🔢 数量: <strong>{{ qrPrintOrder.quantity }}</strong></span>
            <span v-if="qrPrintOrder.product_code" style="font-size:var(--text-xs-alt);color:var(--text-placeholder)">编码: {{ qrPrintOrder.product_code }}</span>
          </div>

          <!-- 模式选择 -->
          <div class="qr-mode-tabs no-print">
            <button class="qr-mode-tab" :class="{active:qrMode==='order'}" :disabled="!!(qrPrintOrder?.qr_mode||'').trim()" @click="switchQrMode('order')">📋 订单模式 <small style="opacity:0.6">(1个/订单)</small>{{ qrPrintOrder?.qr_mode === 'order' ? ' 🔒' : '' }}</button>
            <button class="qr-mode-tab" :class="{active:qrMode==='serial'}" :disabled="!!(qrPrintOrder?.qr_mode||'').trim()" @click="switchQrMode('serial')">🔢 序列号模式 <small style="opacity:0.6" v-if="qrPrintOrder">(共 {{ qrPrintOrder.quantity }} 件)</small>{{ qrPrintOrder?.qr_mode === 'serial' ? ' 🔒' : '' }}</button>
          </div>

          <!-- 控制面板 -->
          <div class="qr-control-bar no-print">
            <button class="btn btn-primary" @click="generateQrCodes" :disabled="qrPrintLoading" style="padding:var(--space-3) 28px;font-size:15px">
              {{ qrPrintLoading ? '⏳ 生成中...' : '🎯 生成二维码' }}
            </button>
            <div class="qr-control-group" v-if="qrCodes.length">
              <span>📄 份数</span>
              <input type="number" v-model.number="qrPrintCopies" min="1" max="10" style="width:55px;text-align:center">
            </div>
            <button v-if="qrCodes.length" class="btn btn-success" @click="printQrCodes" style="padding:var(--space-3) 20px;font-size:15px">🖨️ 打印</button>
          </div>

          <!-- 预览区 -->
          <div id="qr-print-root" class="qr-print-area">
            <div v-if="qrPrintLoading" class="qr-empty-state">⏳ 正在生成二维码...</div>
            <div v-else-if="qrCodes.length" class="qr-grid">
              <template v-for="copy in qrPrintCopies" :key="'copy'+copy">
                <div v-for="(code, idx) in qrCodes" :key="idx+'_'+copy" class="qr-card">
                  <img :src="code.qrcode" :alt="code.serial_no || code.order_no">
                  <div class="qr-label-info">
                    <div class="qr-label-no">{{ code.serial_no || code.order_no }}</div>
                    <div class="qr-label-code" v-if="code.product_code">{{ code.product_code }}</div>
                  </div>
                </div>
              </template>
            </div>
            <div v-else class="qr-empty-state">
              <div style="font-size:56px;margin-bottom:var(--space-3)">🏷️</div>
              <div style="font-size:15px;font-weight:500;color:var(--text-placeholder);margin-bottom:var(--space-1)">选择模式后点击「生成二维码」</div>
              <div style="font-size:var(--text-xs);color:var(--text-placeholder)">支持订单模式（1个/订单）和序列号模式（1个/件）</div>
            </div>
          </div>
        </div>
      </div>
    </div>

    <!-- 回收站模态框 -->
    <div v-if="showTrash" class="modal-overlay" >
      <div class="modal" style="max-width:900px;width:95%">
        <div class="modal-header">
          <span>🗑️ 回收站（{{ trashTotal }} 个已删除订单）</span>
          <span class="modal-close" @click="showTrash=false">&times;</span>
        </div>
        <div class="modal-body" style="max-height:60vh;overflow-y:auto">
          <table v-if="trashOrders.length" class="data-table">
            <thead>
              <tr><th>订单号</th><th>产品</th><th>客户</th><th>删除时间</th><th>操作人</th><th style="text-align:center">操作</th></tr>
            </thead>
            <tbody>
              <tr v-for="o in trashOrders" :key="o.id">
                <td><code>{{ o.order_no }}</code></td>
                <td>{{ o.product_name }}</td>
                <td>{{ o.customer }}</td>
                <td style="font-size:var(--text-xs);color:var(--text-placeholder)">{{ o.deleted_at }}</td>
                <td style="font-size:var(--text-xs)">{{ o.deleted_by_name || '-' }}</td>
                <td style="text-align:center">
                  <button class="btn btn-sm" style="background:var(--success-lighter);color:var(--success);font-size:var(--text-xs-alt);padding:var(--space-1) 10px" @click="restoreOrder(o.id)">恢复</button>
                  <button class="btn btn-sm" style="background:var(--danger-lighter, #fff0f0);color:var(--danger,#e74c3c);font-size:var(--text-xs-alt);padding:var(--space-1) 10px;margin-left:6px" @click="permanentDelete(o.id)">彻底删除</button>
                </td>
              </tr>
            </tbody>
          </table>
          <div v-else style="text-align:center;padding:24px 16px;color:var(--text-placeholder);font-size:var(--text-sm)">回收站为空</div>
        </div>
      </div>
    </div>

    <!-- 工件进度弹窗 -->
    <div v-if="progressOrder" class="modal-overlay" >
      <div class="modal" style="max-width:900px;width:95%">
        <div class="modal-header">
          <span>📊 工件进度 — {{ progressOrder.order_no }} {{ progressOrder.product_name }}</span>
          <span class="modal-close" @click="progressOrder=null">&times;</span>
        </div>
        <div class="modal-body" style="max-height:70vh;overflow:auto">
          <div v-if="progressLoading" style="text-align:center;padding:40px;color:var(--text-placeholder)">⏳ 加载中...</div>
          <div v-else-if="progressData">
            <div class="summary-bar" style="margin-bottom:var(--space-4);flex-wrap:wrap">
              <div class="summary-item"><span class="s-icon">📦</span><div><div class="s-val">{{ progressData.summary.total_workpieces }}</div><div class="s-label">工件总数</div></div></div>
              <div class="summary-item"><span class="s-icon">✅</span><div><div class="s-val text-success">{{ progressData.summary.completed_workpieces }}</div><div class="s-label">已完成</div></div></div>
              <div class="summary-item"><span class="s-icon">🔄</span><div><div class="s-val" style="color:var(--warning)">{{ progressData.summary.in_progress_workpieces }}</div><div class="s-label">进行中</div></div></div>
              <div class="summary-item"><span class="s-icon">⏳</span><div><div class="s-val text-muted">{{ progressData.summary.pending_workpieces }}</div><div class="s-label">待产</div></div></div>
              <div class="summary-item"><span class="s-icon">⚠️</span><div><div class="s-val" style="color:var(--danger)">{{ progressData.summary.stuck_workpieces || 0 }}</div><div class="s-label">滞留</div></div></div>
              <div class="summary-item"><span class="s-icon">📈</span><div><div class="s-val" style="color:var(--primary-accent)">{{ progressData.summary.overall_progress_pct }}%</div><div class="s-label">总进度</div></div></div>
              <div class="summary-item"><span class="s-icon">⏱️</span><div><div class="s-val">{{ progressData.summary.estimated_remaining_hours ?? '-' }}</div><div class="s-label">剩余工时</div></div></div>
            </div>
            <div v-if="progressData.analysis" class="progress-risk-panel">
              <div class="progress-risk-card" :class="'risk-' + (progressData.analysis.deadline_risk?.level || 'low')">
                <div style="display:flex;justify-content:space-between;gap:var(--space-3);align-items:flex-start">
                  <div>
                    <div style="font-weight:700;margin-bottom:4px">交期风险：{{ riskLabel(progressData.analysis.deadline_risk?.level) }}</div>
                    <div style="font-size:var(--text-xs);color:var(--text-secondary)">{{ progressData.analysis.deadline_risk?.reason }}</div>
                  </div>
                  <div style="font-size:var(--text-xs);text-align:right;color:var(--text-placeholder);white-space:nowrap">
                    <div>交期：{{ progressData.analysis.deadline_risk?.deadline || '-' }}</div>
                    <div>剩余：{{ progressData.analysis.deadline_risk?.days_remaining ?? '-' }} 天</div>
                  </div>
                </div>
              </div>
              <div class="progress-advice" v-if="progressData.analysis.recommendations?.length">
                <div style="font-weight:600;margin-bottom:6px">处理建议</div>
                <div v-for="(tip, idx) in progressData.analysis.recommendations" :key="idx" class="progress-advice-item">{{ tip }}</div>
              </div>
              <div v-if="progressData.analysis.stuck_items?.length" style="margin-bottom:var(--space-4)">
                <div style="font-weight:600;font-size:var(--text-sm);margin-bottom:var(--space-2)">卡点工件清单（超过 {{ progressData.analysis.stuck_threshold_hours }} 小时未推进）</div>
                <table class="data-table" style="font-size:var(--text-xs)">
                  <thead><tr><th>工件</th><th>卡点工序</th><th>滞留</th><th>剩余工序</th><th>上一道完成</th></tr></thead>
                  <tbody>
                    <tr v-for="item in progressData.analysis.stuck_items.slice(0, 10)" :key="item.serial_no || item.position_no">
                      <td><code>{{ item.serial_no || ('#' + item.position_no) }}</code></td>
                      <td>{{ item.blocking_process_name || '-' }}</td>
                      <td style="color:var(--danger);font-weight:600">{{ formatHours(item.wait_hours) }}</td>
                      <td>{{ item.remaining_steps }}</td>
                      <td style="color:var(--text-placeholder)">{{ item.last_completed_at || '-' }}</td>
                    </tr>
                  </tbody>
                </table>
              </div>
            </div>
            <div style="margin-bottom:var(--space-4)">
              <div style="font-weight:600;font-size:var(--text-sm);margin-bottom:var(--space-2)">各工序完成情况</div>
              <div v-for="ps in progressData.summary.process_stats" :key="ps.process_id" style="display:flex;align-items:center;gap:var(--space-2);margin-bottom:var(--space-1)">
                <span style="width:50px;font-size:var(--text-xs);text-align:right;color:var(--text-placeholder)">{{ ps.process_name }}</span>
                <div style="flex:1;height:20px;background:var(--bg-hover);border-radius:4px;overflow:hidden">
                  <div :style="{width:(ps.completed/ps.total*100)+'%',height:'100%',background:ps.completed===ps.total?'var(--success)':'var(--primary-accent)',borderRadius:'4px'}"></div>
                </div>
                <span style="width:40px;font-size:var(--text-xs);text-align:right">{{ ps.completed }}/{{ ps.total }}</span>
              </div>
            </div>
            <div class="table-wrap" style="max-height:400px;overflow:auto">
              <table class="data-table" style="font-size:var(--text-xs);min-width:600px">
                <thead><tr>
                  <th style="position:sticky;left:0;background:white;z-index:1;min-width:70px">工件</th>
                  <th v-for="proc in progressData.processes" :key="proc.process_id" style="min-width:55px;text-align:center;white-space:nowrap;font-size:var(--text-xs-alt)">{{ proc.name }}</th>
                  <th style="min-width:55px;text-align:center">状态</th>
                </tr></thead>
                <tbody>
                  <tr v-for="wp in progressData.progress" :key="wp.serial_no">
                    <td style="position:sticky;left:0;background:white;font-weight:500">{{ wp.serial_no ? wp.serial_no.split('-').pop() : '#'+wp.position_no }}</td>
                    <td v-for="step in wp.steps" :key="step.process_id" style="text-align:center;padding:2px">
                      <span v-if="step.status==='completed'" style="color:var(--success)">✅</span>
                      <span v-else-if="step.status==='current'" style="color:var(--warning)">🔵</span>
                      <span v-else style="color:var(--border)">·</span>
                    </td>
                    <td style="text-align:center"><span class="badge wp-badge" :class="wp.status==='completed'?'completed':wp.status==='in_progress'?'in-progress':'pending'">{{ wp.status==='completed'?'完成':wp.status==='in_progress'?'进行中':'待产' }}</span></td>
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
import { useOrder } from '@/composables/useOrder.js'

export default {
  setup() {
    return useOrder()
  }
}
</script>
