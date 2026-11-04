const KIND_PRIORITY = Object.freeze({ order: 0, work: 1, quality: 2, inventory: 3, shipment: 4 })
const TIMESTAMP = /^(\d{4})-(\d{2})-(\d{2})(?:[ T](\d{2}):(\d{2})(?::(\d{2})(\.\d{1,6})?)?(Z|[+-]\d{2}:?\d{2})?)?$/i

// SQLite wall-clock values use production time (+08:00), never browser time.
// Reject calendar rollovers instead of letting Date turn February 30 into March.
function parseTimestamp(value) {
  if (typeof value !== 'string') return null
  const text = value.trim()
  const match = TIMESTAMP.exec(text)
  if (!match) return null
  const [, year, month, day, hour = '00', minute = '00', second = '00', fraction = '', offset = '+08:00'] = match
  const calendar = new Date(`${year}-${month}-${day}T00:00:00Z`)
  if (!Number.isFinite(calendar.getTime()) || calendar.getUTCDate() !== Number(day)
    || Number(hour) > 23 || Number(minute) > 59 || Number(second) > 59) return null
  const zone = offset.toUpperCase() === 'Z' ? 'Z' : offset.replace(/([+-]\d{2})(\d{2})$/, '$1:$2')
  const milliseconds = fraction ? `.${fraction.slice(1).padEnd(3, '0').slice(0, 3)}` : ''
  const timestamp = Date.parse(`${year}-${month}-${day}T${hour}:${minute}:${second}${milliseconds}${zone}`)
  // Python timestamps may include microseconds; do not turn distinct instants
  // inside one millisecond into an ID-based tie.
  const subMillisecond = Number(fraction.slice(4).padEnd(3, '0')) / 1000
  return Number.isFinite(timestamp) ? timestamp + subMillisecond : null
}

function compareIds(left, right) {
  const leftNumeric = /^\d+$/.test(left)
  const rightNumeric = /^\d+$/.test(right)
  if (leftNumeric !== rightNumeric) return leftNumeric ? -1 : 1
  if (leftNumeric) {
    const a = BigInt(left)
    const b = BigInt(right)
    if (a !== b) return a < b ? -1 : 1
  }
  return left < right ? -1 : left > right ? 1 : 0
}

/**
 * Build presentation events without changing API arrays or their payloads.
 * Equal times use kind, ID and original occurrence order. Duplicate IDs remain
 * separate events; JSON tuple keys cannot collide with delimiter-bearing IDs.
 */
export function buildTraceTimeline(result) {
  const events = []
  const occurrences = new Map()
  function add(kind, payload, time, label, ordinal = null) {
    const stable_id = String(payload.id ?? '')
    const identity = JSON.stringify([kind, stable_id])
    const occurrence = occurrences.get(identity) || 0
    occurrences.set(identity, occurrence + 1)
    const timestamp = parseTimestamp(time)
    events.push({
      timestamp,
      kind,
      stable_id,
      label,
      payload,
      key: JSON.stringify([kind, stable_id, occurrence]),
      time_label: timestamp === null ? '时间缺失' : time,
      ordinal,
    })
  }

  if (result.order) add('order', result.order, result.order.created_at, '订单创建')
  for (const [index, record] of (result.work_records || []).entries()) {
    add('work', record, record.created_at, record.process_name || '-', index + 1)
  }
  for (const inspection of result.quality_inspections || []) {
    add('quality', inspection, inspection.inspected_at || inspection.created_at, `${inspection.process_name || '-'} 质检`)
  }
  const logistics = result.item ? result.order_scope || {} : result
  for (const log of logistics.inventory_logs || []) {
    add('inventory', log, log.created_at, `${result.item ? '订单入库' : '入库'} · ${log.product_name || log.product_model || '-'}`)
  }
  for (const shipment of logistics.shipments || []) {
    add('shipment', shipment, shipment.completed_at || shipment.created_at, `${result.item ? '订单发货' : '发货'} · ${shipment.shipment_no}`)
  }

  return events.sort((left, right) => {
    if (left.timestamp !== right.timestamp) {
      if (left.timestamp === null) return 1
      if (right.timestamp === null) return -1
      return left.timestamp - right.timestamp
    }
    return KIND_PRIORITY[left.kind] - KIND_PRIORITY[right.kind]
      || compareIds(left.stable_id, right.stable_id)
  })
}
