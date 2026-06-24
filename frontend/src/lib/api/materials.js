import { request, buildQuery } from './client.js'

const MATERIALS_API = '/api/materials'
const SUPPLIERS_API = '/api/suppliers'

export const materialsApi = {
  listMaterials:              (params)    => request('GET', MATERIALS_API + buildQuery(params || {})),
  createMaterial:            (data)      => request('POST', MATERIALS_API, data),
  updateMaterial:            (id, data)  => request('PUT', MATERIALS_API + '/' + id, data),
  deleteMaterial:            (id)        => request('DELETE', MATERIALS_API + '/' + id),
  getMaterialImpact:         (id)        => request('GET', MATERIALS_API + '/' + id + '/impact'),
  materialStockChange:       (id, data)  => request('POST', MATERIALS_API + '/' + id + '/stock', data),
  getMaterialLogs:           (id, params)=> request('GET', MATERIALS_API + '/' + id + '/logs' + buildQuery(params || {})),
  getMaterialConsumptions:   (id, params)=> request('GET', MATERIALS_API + '/' + id + '/consumptions' + buildQuery(params || {})),
  createMaterialConsumption: (id, data)  => request('POST', MATERIALS_API + '/' + id + '/consumptions', data),
  deleteMaterialConsumption: (id)        => request('DELETE', '/api/material-consumptions/' + id),
  listSuppliers:             (params)    => request('GET', SUPPLIERS_API + buildQuery(params || {})),
  createSupplier:            (data)      => request('POST', SUPPLIERS_API, data),
  updateSupplier:            (id, data)  => request('PUT', SUPPLIERS_API + '/' + id, data),
  deleteSupplier:            (id)        => request('DELETE', SUPPLIERS_API + '/' + id),
}
