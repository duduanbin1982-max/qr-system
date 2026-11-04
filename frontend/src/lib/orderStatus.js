// Order labels and badge classes shared by order and traceability views.
export const ORDER_STATUS_MAP = Object.freeze({
  pending: Object.freeze({ label: '待生产', cls: 'badge-pending' }),
  producing: Object.freeze({ label: '生产中', cls: 'badge-warning' }),
  completed: Object.freeze({ label: '已完成', cls: 'badge-success' }),
  cancelled: Object.freeze({ label: '已取消', cls: 'badge-danger' }),
  paused: Object.freeze({ label: '已暂停', cls: 'badge-secondary' }),
  in_progress: Object.freeze({ label: '生产中', cls: 'badge-warning' }),
  scrapped: Object.freeze({ label: '已报废', cls: 'badge-danger' }),
  deleted: Object.freeze({ label: '已删除', cls: 'badge-danger' }),
})

const UNKNOWN_ORDER_STATUS = Object.freeze({ label: '未知状态', cls: 'badge-info' })

export function getOrderStatus(status) {
  return typeof status === 'string' && Object.hasOwn(ORDER_STATUS_MAP, status)
    ? ORDER_STATUS_MAP[status]
    : UNKNOWN_ORDER_STATUS
}
