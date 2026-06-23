import { request, buildQuery, uploadFile } from './client.js'

export const pricingApi = {
  // ========== 工价 ==========
  // 产品路线工价（新）
  getRoutePricing: (productId)    => request('GET', '/api/products/' + productId + '/route-pricing'),
  saveRoutePricing: (productId, data) => request('POST', '/api/products/' + productId + '/route-pricing', data),
  // 路线级工价（v4）
  getRoutePrices: (params)      => request('GET', '/api/route-prices' + buildQuery(params)),
  getRoutePricingDetail: (routeId) => request('GET', '/api/route-prices/' + routeId),
  getRoutePricingHistory: (routeId) => request('GET', '/api/route-prices/' + routeId + '/history'),
  saveRouteLevelPricing: (routeId, data) => request('PUT', '/api/route-prices/' + routeId, data),
}
