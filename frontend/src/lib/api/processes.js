import { request, buildQuery, uploadFile } from './client.js'

export const processesApi = {
  // ========== 工序 ==========
  listProcesses:    (params) => request('GET', '/api/processes' + buildQuery(params)),
  createProcess:    (data)   => request('POST', '/api/processes', data),
  updateProcess:    (id,data)=> request('PUT',  '/api/processes/' + id, data),
  deleteProcess:    (id)     => request('DELETE', '/api/processes/' + id),
  getProcessImpact: (id)     => request('GET', '/api/processes/' + id + '/impact'),
}
