import { request, buildQuery, uploadFile } from './client.js'

export const processRoutesApi = {
  // ========== 工序路线 ==========
  listProcessRoutes:(params) => request("GET", "/api/process-routes" + buildQuery(params)),
  createProcessRoute:(data)  => request('POST', '/api/process-routes', data),
  updateProcessRoute:(id,data)=>request('PUT', '/api/process-routes/' + id, data),
  deleteProcessRoute:(id)    => request('DELETE', '/api/process-routes/' + id),
  getRouteImpact:   (id)     => request('GET', '/api/process-routes/' + id + '/impact'),
  applyProcessRoute: (id, orderId) => request("POST", "/api/process-routes/" + id + "/apply", { order_id: orderId }),
}
