// ===== QR-System API Layer =====
// 统一 fetch 封装：令牌注入、401/409 统一处理
const BASE = ''

export async function request(method, url, data) {
  const opts = {
    method,
    headers: {},
    credentials: "include"
  }
  // Token is sent via httpOnly cookie (auto-attached by browser).
  // No localStorage or Authorization header needed.
  if (data && method !== 'GET') {
    opts.headers['Content-Type'] = 'application/json'
    opts.body = JSON.stringify(data)
  }
  const r = await fetch(BASE + url, opts)
  if (r.status === 401) {
    const err = new Error('登录已过期')
    err.code = 401
    // Dispatch event so auth module can redirect if user was logged in
    window.dispatchEvent(new CustomEvent('auth:expired'))
    throw err
  }
  const d = await r.json()
  if (r.status === 409) {
    const err = new Error(d.error || '数据冲突')
    err.code = 409
    throw err
  }
  if (d.error) {
    const err = new Error(d.error)
    err.code = r.status
    throw err
  }
  return d
}

// 便捷方法

// Brooks R3 fix: Unified error handler — eliminates 100+ repeated showToast patterns
export function handleApiError(e, fallbackMsg) {
  const msg = (e && e.message) ? e.message : (fallbackMsg || '操作失败')
  return { error: true, message: msg }
}

export const api = {
  get:    (url)         => request('GET', url),
  post:   (url, data)   => request('POST', url, data),
  put:    (url, data)   => request('PUT', url, data),
  delete: (url)         => request('DELETE', url),
  del:    (url)         => request('DELETE', url),
  
  // ========== 认证 ==========
  login:         (data) => request('POST', '/api/auth/login', data),
  logout:        ()    => request('POST', '/api/auth/logout'),
  authInfo:      ()    => request('GET', '/api/auth/info'),
  changePassword:(data) => request('POST', '/api/auth/change-password', data),
  
  // ========== 仪表盘 ==========
  dashboard: ()         => request('GET', '/api/dashboard'),
  board:    (params)     => request('GET', '/api/dashboard/board' + buildQuery(params)),
  
  // ========== 订单 ==========
  listOrders:       (params) => request('GET', '/api/orders' + buildQuery(params)),
  nextOrderNo:      ()       => request('GET', '/api/orders/next-no'),
  createOrder:      (data)   => request('POST', '/api/orders', data),
  updateOrder:      (id,data)=> request('PUT',  '/api/orders/' + id, data),
  deleteOrder:      (id)     => request('DELETE', '/api/orders/' + id),
  trashOrders:      (params) => request("GET", "/api/orders/trash" + buildQuery(params)),
  restoreOrder:     (id)     => request("POST", "/api/orders/" + id + "/restore"),
  purgeOrder:       (id)     => request("DELETE", "/api/orders/" + id + "/purge"),
  getWorkpieceProgress: (id)  => request('GET', '/api/orders/' + id + '/workpiece-progress'),
  batchCreateOrders:(data)   => request('POST', '/api/orders/batch', data),
  
  // ========== 订单附件 ==========
  listOrderAttachments: (orderId)             => request('GET', '/api/orders/' + orderId + '/attachments'),
  uploadOrderAttachment:(orderId, formData)   => uploadFile('/api/orders/' + orderId + '/attachments', formData),
  downloadAttachment:  (attachmentId)          => '/api/attachments/' + attachmentId + '/download',
  deleteAttachment:    (attachmentId)          => request('DELETE', '/api/attachments/' + attachmentId),
  
  // ========== 产品 ==========
  listMaterials:   (params) => request('GET', '/api/materials' + buildQuery(params || {})),
  listProcesses:   ()       => request('GET', '/api/processes'),
  listProducts:     (params) => request('GET', '/api/products' + buildQuery(params)),
  createProduct:    (data)   => request('POST', '/api/products', data),
  updateProduct:    (id,data)=> request('PUT',  '/api/products/' + id, data),
  deleteProduct:    (id)     => request('DELETE', '/api/products/' + id),
  restoreProduct:   (id)     => request('POST', '/api/products/' + id + '/restore'),
  purgeProduct:     (id)     => request('DELETE', '/api/products/' + id + '/purge'),
  uploadProductImport:(formData)=> uploadFile('/api/products/import', formData),

  // Product attachments
  listProductBom:  (productId)         => request('GET', '/api/products/' + productId + '/bom'),
  addProductBom:   (productId, data)   => request('POST', '/api/products/' + productId + '/bom', data),
  deleteProductBom:(productId, bomId)  => request('DELETE', '/api/products/' + productId + '/bom/' + bomId),
  listOrderMaterials: (orderId)        => request('GET', '/api/orders/' + orderId + '/materials'),
  addOrderMaterial:   (orderId, data)  => request('POST', '/api/orders/' + orderId + '/materials', data),
  deleteOrderMaterial:(orderId, omId)  => request('DELETE', '/api/orders/' + orderId + '/materials/' + omId),
  listProductAttachments:   (productId)          => request('GET', '/api/products/' + productId + '/attachments'),
  uploadProductAttachment:  (productId, formData) => uploadFile('/api/products/' + productId + '/attachments', formData),
  deleteProductAttachment:  (attachmentId)        => request('DELETE', '/api/product-attachments/' + attachmentId),

  
  // ========== 客户 ==========
  listCustomers:    (params) => request('GET', '/api/customers' + buildQuery(params)),
  createCustomer:   (data)   => request('POST', '/api/customers', data),
  updateCustomer:   (id,data)=> request('PUT',  '/api/customers/' + id, data),
  deleteCustomer:   (id)     => request('DELETE', '/api/customers/' + id),
  customerOrders:   (id)     => request('GET', '/api/customers/' + id + '/orders'),
  
  // ========== 员工 ==========
  listUsers:        (params) => request('GET', '/api/users' + buildQuery(params)),
  createUser:       (data)   => request('POST', '/api/users', data),
  updateUser:       (id,data)=> request('PUT',  '/api/users/' + id, data),
  deleteUser:       (id)     => request('DELETE', '/api/users/' + id),
  restoreUser:      (id)     => request('POST', '/api/users/' + id + '/restore'),
  permanentDeleteUser: (id)     => request('DELETE', '/api/users/' + id + '/permanent'),
  resetPassword:    (id,data)=> request('POST', '/api/users/' + id + '/reset-password', data),
  unlockUser:       (id)     => request('POST', '/api/users/' + id + '/unlock'),
  
  // ========== 工序 ==========
  listProcesses:    (params) => request('GET', '/api/processes' + buildQuery(params)),
  createProcess:    (data)   => request('POST', '/api/processes', data),
  updateProcess:    (id,data)=> request('PUT',  '/api/processes/' + id, data),
  deleteProcess:    (id)     => request('DELETE', '/api/processes/' + id),
  getProcessImpact: (id)     => request('GET', '/api/processes/' + id + '/impact'),
  
  // ========== 工序路线 ==========
  listProcessRoutes:(params) => request("GET", "/api/process-routes" + buildQuery(params)),
  createProcessRoute:(data)  => request('POST', '/api/process-routes', data),
  updateProcessRoute:(id,data)=>request('PUT', '/api/process-routes/' + id, data),
  deleteProcessRoute:(id)    => request('DELETE', '/api/process-routes/' + id),
  getRouteImpact:   (id)     => request('GET', '/api/process-routes/' + id + '/impact'),
  applyProcessRoute: (id, orderId) => request("POST", "/api/process-routes/" + id + "/apply", { order_id: orderId }),
  
  // ========== 工价 ==========
  // 产品路线工价（新）
  getRoutePricing: (productId)    => request('GET', '/api/products/' + productId + '/route-pricing'),
  saveRoutePricing: (productId, data) => request('POST', '/api/products/' + productId + '/route-pricing', data),
  
  // 路线级工价（v4）
  getRoutePrices: (params)      => request('GET', '/api/route-prices' + buildQuery(params)),
  getRoutePricingDetail: (routeId) => request('GET', '/api/route-prices/' + routeId),
  saveRouteLevelPricing: (routeId, data) => request('PUT', '/api/route-prices/' + routeId, data),
  
  // ========== 工资 ==========
  listWages:        (params) => request('GET', '/api/wages' + buildQuery(params)),
  
  // ========== 库存 ==========
  listInventory:    (params) => request('GET', '/api/inventory' + buildQuery(params)),
  classifyABC:      ()       => request('POST', '/api/inventory/abc'),
  createInventory:  (data)   => request('POST', '/api/inventory', data),
  updateInventory:  (id,data)=> request('PUT',  '/api/inventory/' + id, data),
  deleteInventory:  (id)     => request('DELETE', '/api/inventory/' + id),
  stockIn:          (data)   => request('POST', '/api/inventory/stock-in', data),
  stockOut:         (data)   => request('POST', '/api/inventory/stock-out', data),
  inventoryLogs:    (params) => request('GET', '/api/inventory/logs' + buildQuery(params)),
  inventoryAlerts:  ()       => request('GET', '/api/inventory/alerts'),
  inventoryStats:   ()       => request('GET', '/api/inventory/stats'),
  inventoryTurnover:()       => request('GET', '/api/inventory/turnover'),
  createCountTask:  ()       => request('POST', '/api/inventory/count-task', {}),
  listLocations:    ()       => request('GET', '/api/inventory/locations'),
  inventoryImpact:  (id)     => request('GET', '/api/inventory/' + id + '/impact'),
  
  // ========== 发货 ==========
  listShipments:    (params) => request('GET', '/api/shipments' + buildQuery(params)),
  getShipment:      (id)     => request('GET', '/api/shipments/' + id),
  createShipment:   (data)   => request('POST', '/api/shipments', data),
  updateShipment:   (id,data)=> request('PUT',  '/api/shipments/' + id, data),
  deleteShipment:   (id)     => request('DELETE', '/api/shipments/' + id),
  completeShipment: (id)     => request('POST', '/api/shipments/' + id + '/complete'),
  draftShipment:    ()       => request('GET', '/api/shipments/draft'),
  receiveShipment:  (id,data)=> request('POST', '/api/shipments/' + id + '/receive', data),
  recordPayment:    (id,data)=> request('POST', '/api/shipments/' + id + '/payment', data),
  getShipmentOrderItems: (id) => request('GET', '/api/shipments/order-items/' + id),
  
  // ========== 扫码报工 ==========
  scan:             (data)   => request('POST', '/api/scan', data),
  report:           (data)   => request('POST', '/api/report', data),
  reportLogs:       (params) => request('GET', '/api/report-logs' + buildQuery(params)),
  
  // ========== 二维码 ==========
  qrcode:           (orderNo)=>request('GET', '/api/qrcode/' + orderNo),
  qrcodeBatch:      (data)   => request('POST', '/api/qrcode/batch', data),
  
  // ========== 统计 ==========
  dailyStats:       (params) => request('GET', '/api/stats/daily' + buildQuery(params)),
  workerStats:      (params) => request('GET', '/api/stats/worker' + buildQuery(params)),
  workerDetail:     (params) => request('GET', '/api/stats/worker-detail' + buildQuery(params)),
  scrapStats:       (params) => request('GET', '/api/stats/scrap' + buildQuery(params)),
  orderProgress:    (params) => request('GET', '/api/stats/order-progress' + buildQuery(params)),
  dailyReport:      (params) => request('GET', '/api/daily-report' + buildQuery(params)),
  productionProgress:(params)=>request('GET', '/api/production-progress' + buildQuery(params)),
  productionTrend:  (params) => request('GET', '/api/reports/production-trend' + buildQuery(params)),
  workerEfficiency: (params) => request('GET', '/api/reports/worker-efficiency' + buildQuery(params)),
  qualityAnalysis:  (params) => request('GET', '/api/reports/quality-analysis' + buildQuery(params)),
  orderAnalysis:    (params) => request('GET', '/api/reports/order-analysis' + buildQuery(params)),
  dashboardKpi:     (params) => request('GET', '/api/reports/dashboard-kpi' + buildQuery(params)),
  materialUsage:    (params) => request('GET', '/api/stats/material' + buildQuery(params)),
  productStats:     (params) => request('GET', '/api/stats/product' + buildQuery(params)),
  productProcessMatrix: (params) => request('GET', '/api/reports/product-process-matrix' + buildQuery(params)),
  modelProcessStats: (params) => request('GET', '/api/reports/model-process-stats' + buildQuery(params)),
  productProcessStats: (params) => request('GET', '/api/stats/product-process' + buildQuery(params)),
  shipmentStats:    (params) => request('GET', '/api/stats/shipment' + buildQuery(params)),
  // ========== 追溯 ==========
  trace:            (code)   => request('GET', '/api/trace/' + encodeURIComponent(code)),
  traceByOrder:     (orderNo) => request('GET', '/api/trace/order/' + encodeURIComponent(orderNo)),
  
  // ========== 审批 ==========
  pendingApprovals:  ()       => request('GET', '/api/approvals/pending'),
  approvalHistory:  (params) => request('GET', '/api/approvals/history' + buildQuery(params)),
  handleApproval:   (id,action,comment) => request('POST', '/api/approvals/' + id + '/' + action, {comment: comment || ''}),
  batchApproval:    (ids, action) => request('POST', '/api/approvals/batch', {ids: ids, action: action}),
  approvalStats:    ()       => request('GET', '/api/approvals/stats'),
  approvalConfig:   ()       => request('GET', '/api/approvals/config'),
  saveApprovalConfig: (data) => request('POST', '/api/approvals/config', data),
  
  // ========== 系统设置 ==========
  getSettings:      ()       => request('GET', '/api/settings'),
  saveSettings:     (data)   => request('POST', '/api/settings', data),
  
  // ========== 岗位 ==========
  listPositions:    ()       => request('GET', '/api/positions'),
  createPosition:   (data)   => request('POST', '/api/positions', data),
  updatePosition:   (id,data)=> request('PUT',  '/api/positions/' + id, data),
  deletePosition:   (id)     => request('DELETE', '/api/positions/' + id),
  
  // ========== 角色 ==========
  listRoleGroups:   ()       => request('GET', '/api/role-groups'),
  createRoleGroup:  (data)   => request('POST', '/api/role-groups', data),
  updateRoleGroup:  (id,data)=> request('PUT',  '/api/role-groups/' + id, data),
  deleteRoleGroup:  (id)     => request('DELETE', '/api/role-groups/' + id),
  listRoles:        ()       => request('GET', '/api/roles'),
  createRole:       (data)   => request('POST', '/api/roles', data),
  updateRole:       (id,data)=> request('PUT',  '/api/roles/' + id, data),
  deleteRole:       (id)     => request('DELETE', '/api/roles/' + id),
  
  // ========== 日志 ==========
  listLogs:         (params) => request('GET', '/api/logs' + buildQuery(params)),
  deleteLogs:       (params) => request("POST", "/api/logs/clear", params),

  // ========== 质检 ==========
  listInspections:  (params) => request('GET', '/api/quality/inspections' + buildQuery(params)),
  inspectionStats:  ()       => request('GET', '/api/inspection/stats'),
  createInspection: (data)   => request('POST', '/api/quality/inspections', data),
  updateInspection: (id,data)=> request('PUT', '/api/quality/inspections/' + id, data),
  deleteInspection: (id)     => request('DELETE', '/api/quality/inspections/' + id),
  defectCategories: ()       => request('GET', '/api/quality/defect-categories'),
  defectPareto:     (params) => request('GET', '/api/quality/defect-pareto' + buildQuery(params)),
  inspectionTemplates: ()     => request('GET', '/api/quality/inspection-templates'),
  batchInspections:   (data)  => request('POST', '/api/quality/inspections/batch', data),
  listQAttachments:   (iid)   => request('GET', '/api/quality/inspections/' + iid + '/attachments'),
  uploadQAttachment:  (iid, formData) => uploadFile('/api/quality/inspections/' + iid + '/attachments', formData),
  exportInspections:(params) => request('GET', '/api/quality/inspections/export' + buildQuery(params)),
  qualityInspStats: ()       => request('GET', '/api/quality/inspections/stats'),
  spcPChart:       (params) => request('GET', '/api/quality/spc-p-chart' + buildQuery(params)),
  deleteQAttachment:  (aid)   => request('DELETE', '/api/quality/attachments/' + aid),
  getQAttachmentUrl:  (aid)   => '/api/quality/attachments/' + aid,

  // ========== 返工 ==========
  listRework:       (params) => request('GET', '/api/rework' + buildQuery(params)),
  reworkStats:      ()       => request('GET', '/api/rework/stats'),
  createRework:     (data)   => request('POST', '/api/rework', data),
  updateRework:     (id,data)=> request('PUT', '/api/rework/' + id, data),
  completeRework:   (id,data)=> request('POST', '/api/rework/' + id + '/complete', data),
  batchCompleteRework: (data)=> request('POST', '/api/rework/batch-complete', data),
  exportRework:     (params) => request('GET', '/api/rework/export' + buildQuery(params)),
  reworkTrend:      (params) => request('GET', '/api/rework/trend' + buildQuery(params)),
  reworkTopProcesses:(params) => request('GET', '/api/rework/top-processes' + buildQuery(params)),
  reworkWorkerStats:()       => request('GET', '/api/rework/worker-stats'),

  // ========== 产线 ==========
  listProductionLines: ()     => request('GET', '/api/production-lines'),
  getScheduleGantt:   ()       => request('GET', '/api/schedule/gantt'),
  updateScheduleOrder:(id,data)=> request('PUT', '/api/schedule/order/' + id, data),
  batchShiftSchedule: (data)   => request('POST', '/api/schedule/batch-shift', data),
  createProductionLine:(data)  => request('POST', '/api/production-lines', data),
  updateProductionLine:(id,data)=>request('PUT', '/api/production-lines/' + id, data),
  deleteProductionLine:(id)    => request('DELETE', '/api/production-lines/' + id),
}

function buildQuery(params) {
  if (!params) return ''
  const qs = Object.entries(params)
    .filter(([_,v]) => v !== '' && v != null)
    .map(([k,v]) => encodeURIComponent(k) + '=' + encodeURIComponent(v))
    .join('&')
  return qs ? '?' + qs : ''
}

async function uploadFile(url, formData) {
  // Cookie-only auth: httpOnly cookie auto-attached by browser.
  // No manual Authorization header needed.
  const opts = { method: 'POST', body: formData }
  const r = await fetch(BASE + url, opts)
  if (r.status === 401) {
    const err = new Error('登录已过期')
    err.code = 401
    window.dispatchEvent(new CustomEvent('auth:expired'))
    throw err
  }
  const d = await r.json()
  if (d.error) {
    const err = new Error(d.error)
    err.code = r.status
    throw err
  }
  return d
}
