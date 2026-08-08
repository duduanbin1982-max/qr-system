import { request, buildQuery, uploadFile } from './client.js'

export const inventoryApi = {
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
  countStatus:      (taskId) => request('GET', '/api/inventory/count-status' + buildQuery({ task_id: taskId })),
  submitCount:      (id,data)=> request('POST', '/api/inventory/' + id + '/count', data),
  approveCountTask: (taskId) => request('POST', '/api/inventory/count-task/' + taskId + '/approve', {}),
  listLocations:    ()       => request('GET', '/api/inventory/locations'),
  inventoryImpact:  (id)     => request('GET', '/api/inventory/' + id + '/impact'),
}
