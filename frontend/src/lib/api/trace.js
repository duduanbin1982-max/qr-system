import { request, buildQuery } from './client.js'

export const traceApi = {
  // ========== 追溯 ==========
  trace:            (code)   => request('GET', '/api/trace/' + encodeURIComponent(code)),
  traceByOrder:     (orderNo, params) => request(
    'GET',
    '/api/trace/order/' + encodeURIComponent(orderNo) + buildQuery(params),
  ),
}
