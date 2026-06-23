import { request, buildQuery, uploadFile } from './client.js'

export const productsApi = {
  // ========== 产品 ==========
  listMaterials:   (params) => request('GET', '/api/materials' + buildQuery(params || {})),
  listProcesses:   ()       => request('GET', '/api/processes'),
  listProducts:     (params) => request('GET', '/api/products' + buildQuery(params)),
  createProduct:    (data)   => request('POST', '/api/products', data),
  updateProduct:    (id,data)=> request('PUT',  '/api/products/' + id, data),
  deleteProduct:    (id)     => request('DELETE', '/api/products/' + id),
  restoreProduct:   (id)     => request('POST', '/api/products/' + id + '/restore'),
  purgeProduct:     (id)     => request('DELETE', '/api/products/' + id + '/purge'),
  uploadProductImport:(formData)=> uploadFile('/api/products/import', formData),
  // Product attachments
  listProductBom:  (productId)         => request('GET', '/api/products/' + productId + '/bom'),
  addProductBom:   (productId, data)   => request('POST', '/api/products/' + productId + '/bom', data),
  deleteProductBom:(productId, bomId)  => request('DELETE', '/api/products/' + productId + '/bom/' + bomId),
  listOrderMaterials: (orderId)        => request('GET', '/api/orders/' + orderId + '/materials'),
  addOrderMaterial:   (orderId, data)  => request('POST', '/api/orders/' + orderId + '/materials', data),
  deleteOrderMaterial:(orderId, omId)  => request('DELETE', '/api/orders/' + orderId + '/materials/' + omId),
  listProductAttachments:   (productId)          => request('GET', '/api/products/' + productId + '/attachments'),
  uploadProductAttachment:  (productId, formData) => uploadFile('/api/products/' + productId + '/attachments', formData),
  deleteProductAttachment:  (attachmentId)        => request('DELETE', '/api/product-attachments/' + attachmentId),
}
