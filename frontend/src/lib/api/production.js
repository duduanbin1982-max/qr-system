import { request, buildQuery, uploadFile } from './client.js'

export const productionApi = {
  // ========== 产线 ==========
  listProductionLines: ()     => request('GET', '/api/production-lines'),
  getScheduleGantt:   (params) => request('GET', '/api/schedule/gantt' + buildQuery(params)),
  updateScheduleOrder:(id,data)=> request('PATCH', '/api/schedule/order/' + id, data),
  batchShiftSchedule: (data)   => request('POST', '/api/schedule/batch-shift', data),
  createProductionLine:(data)  => request('POST', '/api/production-lines', data),
  updateProductionLine:(id,data)=>request('PUT', '/api/production-lines/' + id, data),
  deleteProductionLine:(id)    => request('DELETE', '/api/production-lines/' + id),
  listProcessCapacityLines:(params={}) => request('GET', '/api/schedule/capacity-lines' + buildQuery(params)),
  listScheduleCalendars:() => request('GET', '/api/schedule/calendars'),
  listCapacityOrders:(params={}) => request('GET', '/api/schedule/capacity-orders' + buildQuery(params)),
  getOrderOperationSchedule:(id) => request('GET', '/api/schedule/order/' + id + '/operations'),
  generateOrderOperationSchedule:(id,data={}) => request('POST', '/api/schedule/order/' + id + '/generate', data),
  listOperationSchedules:(params={}) => request('GET', '/api/schedule/operations' + buildQuery(params)),
  auditScheduleCapacity:(params={}) => request('GET', '/api/schedule/capacity-audit' + buildQuery(params)),
}
