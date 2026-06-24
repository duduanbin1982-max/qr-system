import { request, buildQuery, uploadFile } from './client.js'

const PRODUCTS_API = '/api/products'
const ROUTE_PRICES_API = '/api/route-prices'

export const pricingApi = {
  // ========== 工价 ==========
  // 产品路线工价（新）
  getRoutePricing: (productId)    => request('GET', PRODUCTS_API + '/' + productId + '/route-pricing'),
  saveRoutePricing: (productId, data) => request('POST', PRODUCTS_API + '/' + productId + '/route-pricing', data),
  // 路线级工价（v4）
  getRoutePrices: (params)      => request('GET', ROUTE_PRICES_API + buildQuery(params)),
  getRoutePricingDetail: (routeId) => request('GET', ROUTE_PRICES_API + '/' + routeId),
  getRoutePricingHistory: (routeId) => request('GET', ROUTE_PRICES_API + '/' + routeId + '/history'),
  saveRouteLevelPricing: (routeId, data) => request('PUT', ROUTE_PRICES_API + '/' + routeId, data),
}
