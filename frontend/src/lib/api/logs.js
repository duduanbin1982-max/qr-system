import { request, buildQuery, uploadFile } from './client.js'

export const logsApi = {
  // ========== 日志 ==========
  listLogs:         (params) => request('GET', '/api/logs' + buildQuery(params)),
  deleteLogs:       (params) => request("POST", "/api/logs/clear", params),
}
