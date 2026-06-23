import { request, buildQuery, uploadFile } from './client.js'

export const ordersApi = {
  // ========== 订单 ==========
  listOrders:       (params) => request('GET', '/api/orders' + buildQuery(params)),
  nextOrderNo:      ()       => request('GET', '/api/orders/next-no'),
  createOrder:      (data)   => request('POST', '/api/orders', data),
  updateOrder:      (id,data)=> request('PUT',  '/api/orders/' + id, data),
  deleteOrder:      (id)     => request('DELETE', '/api/orders/' + id),
  trashOrders:      (params) => request("GET", "/api/orders/trash" + buildQuery(params)),
  restoreOrder:     (id)     => request("POST", "/api/orders/" + id + "/restore"),
  purgeOrder:       (id)     => request("DELETE", "/api/orders/" + id + "/purge"),
  getWorkpieceProgress: (id)  => request('GET', '/api/orders/' + id + '/workpiece-progress'),
  batchCreateOrders:(data)   => request('POST', '/api/orders/batch', data),
}
