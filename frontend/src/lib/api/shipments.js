import { request, buildQuery, uploadFile } from './client.js'

export const shipmentsApi = {
  // ========== 发货 ==========
  listShipments:    (params) => request('GET', '/api/shipments' + buildQuery(params)),
  getShipment:      (id)     => request('GET', '/api/shipments/' + id),
  createShipment:   (data)   => request('POST', '/api/shipments', data),
  updateShipment:   (id,data)=> request('PUT',  '/api/shipments/' + id, data),
  deleteShipment:   (id)     => request('DELETE', '/api/shipments/' + id),
  completeShipment: (id)     => request('POST', '/api/shipments/' + id + '/complete'),
  draftShipment:    ()       => request('GET', '/api/shipments/draft'),
  receiveShipment:  (id,data)=> request('POST', '/api/shipments/' + id + '/receive', data),
  recordPayment:    (id,data)=> request('POST', '/api/shipments/' + id + '/payment', data),
  refundPayment:    (id,data)=> request('POST', '/api/shipments/' + id + '/refund', data),
  reversePayment:   (id,paymentId,data)=> request('POST', '/api/shipments/' + id + '/payments/' + paymentId + '/reverse', data),
  updateLogistics:  (id,data)=> request('PUT', '/api/shipments/' + id + '/logistics', data),
  getShipmentOrderItems: (id) => request('GET', '/api/shipments/order-items/' + id),
  cancelShipment:   (id,data)=> request('POST', '/api/shipments/' + id + '/cancel', data),
  shipmentImpact:   (id)     => request('GET', '/api/shipments/' + id + '/impact'),
  customerHistory:  (params) => request('GET', '/api/shipments/customer-history' + buildQuery(params)),
  shipmentStats:    ()       => request('GET', '/api/shipments/stats'),
  exportShipments:  (params) => request('GET', '/api/shipments/export' + buildQuery(params)),
}
