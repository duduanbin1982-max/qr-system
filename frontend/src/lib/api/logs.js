import { request, buildQuery, uploadFile } from './client.js'

export const logsApi = {
  // ========== 日志 ==========
  listLogs:         (params) => request('GET', '/api/logs' + buildQuery(params)),
  listCategories:   () => request('GET', '/api/logs/categories'),
  deleteLogs:       (params) => request("POST", "/api/logs/clear", params),
  listCleanupRequests: (params) => request('GET', '/api/logs/cleanup-requests' + buildQuery(params)),
  approveCleanupRequest: (id, data) => request('POST', `/api/logs/cleanup-requests/${id}/approve`, data),
  rejectCleanupRequest: (id, data) => request('POST', `/api/logs/cleanup-requests/${id}/reject`, data),
}
