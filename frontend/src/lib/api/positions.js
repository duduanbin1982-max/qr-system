import { request, buildQuery, uploadFile } from './client.js'

export const positionsApi = {
  // ========== 岗位 ==========
  listPositions:    ()       => request('GET', '/api/positions'),
  createPosition:   (data)   => request('POST', '/api/positions', data),
  updatePosition:   (id,data)=> request('PUT',  '/api/positions/' + id, data),
  deletePosition:   (id)     => request('DELETE', '/api/positions/' + id),
}
