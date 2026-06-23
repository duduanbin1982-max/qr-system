import { request, buildQuery, uploadFile } from './client.js'

export const customersApi = {
  // ========== 客户 ==========
  listCustomers:    (params) => request('GET', '/api/customers' + buildQuery(params)),
  createCustomer:   (data)   => request('POST', '/api/customers', data),
  updateCustomer:   (id,data)=> request('PUT',  '/api/customers/' + id, data),
  deleteCustomer:   (id)     => request('DELETE', '/api/customers/' + id),
  customerOrders:   (id, params) => request('GET', '/api/customers/' + id + '/orders' + buildQuery(params || {})),
}
