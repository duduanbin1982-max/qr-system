import { request, buildQuery } from './client.js'

const ROUTE_PRICES_API = '/api/route-prices'

export const pricingApi = {
  getRoutePrices: (params) => request('GET', ROUTE_PRICES_API + buildQuery(params)),
  getRoutePricingDetail: (routeId) => request('GET', ROUTE_PRICES_API + '/' + routeId),
  getRoutePricingHistory: (routeId) => request('GET', ROUTE_PRICES_API + '/' + routeId + '/history'),
  saveRouteLevelPricing: (routeId, data) => request('PUT', ROUTE_PRICES_API + '/' + routeId, data),
}
