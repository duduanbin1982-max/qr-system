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
  listLocations:    ()       => request('GET', '/api/inventory/locations'),
  inventoryImpact:  (id)     => request('GET', '/api/inventory/' + id + '/impact'),
}
