import { request, buildQuery, uploadFile } from './client.js'

export const scanApi = {
  // ========== 扫码报工 ==========
  scan:             (data)   => request('POST', '/api/scan', data),
  report:           (data)   => request('POST', '/api/report', data),
  reportLogs:       (params) => request('GET', '/api/report-logs' + buildQuery(params)),
}
