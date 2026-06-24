import { request, buildQuery, uploadFile } from './client.js'

const ORDERS_API = '/api/orders'

export const ordersApi = {
  // ========== 订单 ==========
  listOrders:       (params) => request('GET', ORDERS_API + buildQuery(params)),
  nextOrderNo:      ()       => request('GET', ORDERS_API + '/next-no'),
  createOrder:      (data)   => request('POST', ORDERS_API, data),
  updateOrder:      (id,data)=> request('PUT',  ORDERS_API + '/' + id, data),
  deleteOrder:      (id)     => request('DELETE', ORDERS_API + '/' + id),
  trashOrders:      (params) => request("GET", ORDERS_API + "/trash" + buildQuery(params)),
  restoreOrder:     (id)     => request("POST", ORDERS_API + "/" + id + "/restore"),
  purgeOrder:       (id)     => request("DELETE", ORDERS_API + "/" + id + "/purge"),
  getWorkpieceProgress: (id)  => request('GET', ORDERS_API + '/' + id + '/workpiece-progress'),
  batchCreateOrders:(data)   => request('POST', ORDERS_API + '/batch', data),
}
