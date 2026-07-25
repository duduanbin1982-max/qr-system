// ===== QR-System API Layer =====
// Domain API facade: callers use api.domains.<domain>.<method>().
export { request, handleApiError, buildQuery, uploadFile } from './api/client.js'
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
import { performanceApi } from './api/performance.js'
import { workTimeApi } from './api/work-time.js'
import { processQualityEvaluationsApi } from './api/process-quality-evaluations.js'
import { qualityManagementApi } from './api/quality-management.js'

export const apiNamespaces = Object.freeze({
  auth: authApi,
  dashboard: dashboardApi,
  orders: ordersApi,
  orderAttachments: orderAttachmentsApi,
  products: productsApi,
  materials: materialsApi,
  customers: customersApi,
  users: usersApi,
  processes: processesApi,
  processRoutes: processRoutesApi,
  pricing: pricingApi,
  wages: wagesApi,
  inventory: inventoryApi,
  shipments: shipmentsApi,
  scan: scanApi,
  qrcode: qrcodeApi,
  stats: statsApi,
  trace: traceApi,
  approvals: approvalsApi,
  settings: settingsApi,
  positions: positionsApi,
  roles: rolesApi,
  logs: logsApi,
  quality: qualityApi,
  rework: reworkApi,
  production: productionApi,
  performance: performanceApi,
  workTime: workTimeApi,
  processQualityEvaluations: processQualityEvaluationsApi,
  qualityManagement: qualityManagementApi,
})

function validateApiModules(namespaces) {
  const owners = new Map()
  const duplicateKeys = []
  let methodCount = 0
  Object.entries(namespaces).forEach(([namespace, moduleApi]) => {
    for (const key of Object.keys(moduleApi)) {
      if (owners.has(key)) {
        duplicateKeys.push(`${key} (${owners.get(key)} -> ${namespace})`)
      }
      owners.set(key, namespace)
      methodCount += 1
    }
  })
  if (duplicateKeys.length) {
    throw new Error(`Duplicate API facade methods: ${duplicateKeys.join(', ')}`)
  }
  return methodCount
}

export const apiMethodCount = validateApiModules(apiNamespaces)

export const api = Object.freeze({
  domains: apiNamespaces,
})
