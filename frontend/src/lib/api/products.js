import { request, buildQuery, uploadFile } from './client.js'

const PRODUCTS_API = '/api/products'
const ORDERS_API = '/api/orders'

export const productsApi = {
  listMaterials: (params) => request('GET', '/api/materials' + buildQuery(params || {})),
  listProcesses: () => request('GET', '/api/processes'),
  listProducts: (params) => request('GET', PRODUCTS_API + buildQuery(params)),
  createProduct: (data) => request('POST', PRODUCTS_API, data),
  updateProduct: (id, data) => request('PUT', PRODUCTS_API + '/' + id, data),
  deleteProduct: (id) => request('DELETE', PRODUCTS_API + '/' + id),
  restoreProduct: (id) => request('PUT', PRODUCTS_API + '/' + id + '/restore'),
  purgeProduct: (id) => request('DELETE', PRODUCTS_API + '/' + id + '/purge'),
  uploadProductImport: (formData) => uploadFile(PRODUCTS_API + '/import', formData),
  listProductBom: (productId) => request('GET', PRODUCTS_API + '/' + productId + '/bom'),
  addProductBom: (productId, data) => request('POST', PRODUCTS_API + '/' + productId + '/bom', data),
  deleteProductBom: (productId, bomId) => request('DELETE', PRODUCTS_API + '/' + productId + '/bom/' + bomId),
  listOrderMaterials: (orderId) => request('GET', ORDERS_API + '/' + orderId + '/materials'),
  addOrderMaterial: (orderId, data) => request('POST', ORDERS_API + '/' + orderId + '/materials', data),
  deleteOrderMaterial: (orderId, omId) => request('DELETE', ORDERS_API + '/' + orderId + '/materials/' + omId),
  listProductAttachments: (productId) => request('GET', PRODUCTS_API + '/' + productId + '/attachments'),
  uploadProductAttachment: (productId, formData) => uploadFile(PRODUCTS_API + '/' + productId + '/attachments', formData),
  deleteProductAttachment: (attachmentId) => request('DELETE', '/api/product-attachments/' + attachmentId),
}
