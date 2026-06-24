import { request, buildQuery, uploadFile } from './client.js'

export const qrcodeApi = {
  // ========== 二维码 ==========
  qrcode:           (orderNo)=>request('GET', '/api/qrcode/' + orderNo),
  qrcodeBatch:      (data)   => request('POST', '/api/qrcode/batch', data),
}
