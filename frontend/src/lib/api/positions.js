import { request, buildQuery, uploadFile } from './client.js'

export const positionsApi = {
  // ========== 岗位 ==========
  listPositions:    (params = {}) => request('GET', '/api/positions' + buildQuery(params)),
  createPosition:   (data)   => request('POST', '/api/positions', data),
  updatePosition:   (id,data)=> request('PUT',  '/api/positions/' + id, data),
  deletePosition:   (id)     => request('DELETE', '/api/positions/' + id),
  getPositionImpact:(id)     => request('GET', '/api/positions/' + id + '/impact'),
}
