import { request, buildQuery, uploadFile } from './client.js'

export const reworkApi = {
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
}
