import { request, buildQuery, uploadFile } from './client.js'

export const dashboardApi = {
  // ========== 仪表盘 ==========
  dashboard: ()         => request('GET', '/api/dashboard'),
  board:    (params)     => request('GET', '/api/dashboard/board' + buildQuery(params)),
}
