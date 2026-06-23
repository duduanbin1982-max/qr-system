import { request, buildQuery, uploadFile } from './client.js'

export const orderAttachmentsApi = {
  // ========== 订单附件 ==========
  listOrderAttachments: (orderId)             => request('GET', '/api/orders/' + orderId + '/attachments'),
  uploadOrderAttachment:(orderId, formData)   => uploadFile('/api/orders/' + orderId + '/attachments', formData),
  downloadAttachment:  (attachmentId)          => '/api/attachments/' + attachmentId + '/download',
  deleteAttachment:    (attachmentId)          => request('DELETE', '/api/attachments/' + attachmentId),
}
