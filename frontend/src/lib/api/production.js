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
  listOrderScheduleRevisions:(id, params={}) => request('GET', '/api/schedule/order/' + id + '/revisions' + buildQuery(params)),
  getScheduleRevision:(id, params={}) => request('GET', '/api/schedule/revisions/' + id + buildQuery(params)),
  publishScheduleRevision:(id, data={}) => request('POST', '/api/schedule/revisions/' + id + '/publish', data),
  generateOrderOperationSchedule:(id,data={}) => request('POST', '/api/schedule/order/' + id + '/generate', data),
  dynamicReplanOrderSchedule:(id,data={}) => request('POST', '/api/schedule/order/' + id + '/dynamic-replan', data),
  listScheduleDowntime:(params={}) => request('GET', '/api/schedule/downtime' + buildQuery(params)),
  createScheduleDowntime:(data={}) => request('POST', '/api/schedule/downtime', data),
  cancelScheduleDowntime:(id) => request('DELETE', '/api/schedule/downtime/' + id),
  listOperationSchedules:(params={}) => request('GET', '/api/schedule/operations' + buildQuery(params)),
  auditScheduleCapacity:(params={}) => request('GET', '/api/schedule/capacity-audit' + buildQuery(params)),
}
