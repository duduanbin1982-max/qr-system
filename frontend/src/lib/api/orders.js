import { request, buildQuery, uploadFile } from './client.js'

const ORDERS_API = '/api/orders'

export const ordersApi = {
  // ========== 订单 ==========
  listOrders:       (params) => request('GET', ORDERS_API + buildQuery(params)),
  nextOrderNo:      ()       => request('GET', ORDERS_API + '/next-no'),
  createOrder:      (data)   => request('POST', ORDERS_API, data),
  updateOrder:      (id,data)=> request('PUT',  ORDERS_API + '/' + id, data),
  deleteOrder:      (id)     => request('DELETE', ORDERS_API + '/' + id),
  reopenOrder:      (id,data)=> request('POST', ORDERS_API + '/' + id + '/reopen', data),
  trashOrders:      (params) => request("GET", ORDERS_API + "/trash" + buildQuery(params)),
  restoreOrder:     (id)     => request("POST", ORDERS_API + "/" + id + "/restore"),
  purgeOrder:       (id)     => request("DELETE", ORDERS_API + "/" + id + "/purge"),
  getWorkpieceProgress: (id)  => request('GET', ORDERS_API + '/' + id + '/workpiece-progress'),
  getCompletionFocus: (params) => request('GET', ORDERS_API + '/completion-focus' + buildQuery(params || {})),
  getCompletionFocusConfig: () => request('GET', ORDERS_API + '/completion-focus/config'),
  saveCompletionFocusConfig: (data) => request('POST', ORDERS_API + '/completion-focus/config', data),
  createCompletionFocusException: (id, data) => request('POST', ORDERS_API + '/' + id + '/completion-focus-exception', data),
  cancelCompletionFocusException: (id, data) => request('DELETE', ORDERS_API + '/completion-focus-exceptions/' + id, data || {}),
  batchCreateOrders:(data)   => request('POST', ORDERS_API + '/batch', data),
}
