import { request, buildQuery, uploadFile } from './client.js'

export const productionApi = {
  // ========== 产线 ==========
  listProductionLines: ()     => request('GET', '/api/production-lines'),
  getScheduleGantt:   ()       => request('GET', '/api/schedule/gantt'),
  updateScheduleOrder:(id,data)=> request('PUT', '/api/schedule/order/' + id, data),
  batchShiftSchedule: (data)   => request('POST', '/api/schedule/batch-shift', data),
  createProductionLine:(data)  => request('POST', '/api/production-lines', data),
  updateProductionLine:(id,data)=>request('PUT', '/api/production-lines/' + id, data),
  deleteProductionLine:(id)    => request('DELETE', '/api/production-lines/' + id),
}
