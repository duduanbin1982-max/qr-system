import { request, uploadFile } from './client.js'

const ORDER_ATTACHMENTS_API = '/api/order-attachments'

export const orderAttachmentsApi = {
  listOrderAttachments: (orderId)           => request('GET', '/api/orders/' + orderId + '/attachments'),
  uploadOrderAttachment: (orderId, formData) => uploadFile('/api/orders/' + orderId + '/attachments', formData),
  downloadAttachment: (attachmentId)        => ORDER_ATTACHMENTS_API + '/' + attachmentId + '/download',
  deleteAttachment: (attachmentId)          => request('DELETE', ORDER_ATTACHMENTS_API + '/' + attachmentId),
}
