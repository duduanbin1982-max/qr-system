// ===== QR-System API Layer =====
// Compatibility facade: existing callers keep importing { api } from '@/lib/api.js'.
export { request, handleApiError, buildQuery, uploadFile } from './api/client.js'
import { request } from './api/client.js'
import { authApi } from './api/auth.js'
import { dashboardApi } from './api/dashboard.js'
import { ordersApi } from './api/orders.js'
import { orderAttachmentsApi } from './api/order-attachments.js'
import { productsApi } from './api/products.js'
import { materialsApi } from './api/materials.js'
import { customersApi } from './api/customers.js'
import { usersApi } from './api/users.js'
import { processesApi } from './api/processes.js'
import { processRoutesApi } from './api/process-routes.js'
import { pricingApi } from './api/pricing.js'
import { wagesApi } from './api/wages.js'
import { inventoryApi } from './api/inventory.js'
import { shipmentsApi } from './api/shipments.js'
import { scanApi } from './api/scan.js'
import { qrcodeApi } from './api/qrcode.js'
import { statsApi } from './api/stats.js'
import { traceApi } from './api/trace.js'
import { approvalsApi } from './api/approvals.js'
import { settingsApi } from './api/settings.js'
import { positionsApi } from './api/positions.js'
import { rolesApi } from './api/roles.js'
import { logsApi } from './api/logs.js'
import { qualityApi } from './api/quality.js'
import { reworkApi } from './api/rework.js'
import { productionApi } from './api/production.js'

const httpApi = {
  get:    (url)         => request('GET', url),
  post:   (url, data)   => request('POST', url, data),
  put:    (url, data)   => request('PUT', url, data),
  delete: (url)         => request('DELETE', url),
  del:    (url)         => request('DELETE', url),
}

export const api = {
  ...httpApi,
  ...authApi,
  ...dashboardApi,
  ...ordersApi,
  ...orderAttachmentsApi,
  ...productsApi,
  ...materialsApi,
  ...customersApi,
  ...usersApi,
  ...processesApi,
  ...processRoutesApi,
  ...pricingApi,
  ...wagesApi,
  ...inventoryApi,
  ...shipmentsApi,
  ...scanApi,
  ...qrcodeApi,
  ...statsApi,
  ...traceApi,
  ...approvalsApi,
  ...settingsApi,
  ...positionsApi,
  ...rolesApi,
  ...logsApi,
  ...qualityApi,
  ...reworkApi,
  ...productionApi
}
