/**
 * Normalize one operation into node-specific schedule facts.
 * A split operation is represented by one row per segment so every node
 * queue shows its own quantity and minute interval instead of the aggregate
 * operation window.
 */
export function scheduleSegments(operation = {}) {
  const common = {
    order_id: operation.order_id,
    order_no: operation.order_no,
    process_id: operation.process_id,
    process_name: operation.process_name,
    operation_id: operation.id || operation.order_process_id,
    order_process_id: operation.order_process_id,
    route_version_id: operation.route_version_id || operation.scheduled_route_version_id,
    process_version_id: operation.process_version_id || operation.scheduled_process_version_id,
    schedule_revision_id: operation.schedule_revision_id,
    revision_item_id: operation.revision_item_id,
    status: operation.status || operation.schedule_status,
    schedule_status: operation.schedule_status,
    blocked_code: operation.blocked_code || operation.error_code || '',
    blocked_reason: operation.blocked_reason || operation.reason || operation.error_message || '',
    reason: operation.reason || '',
    error_message: operation.error_message || '',
    risk_level: operation.risk_level || 'none',
    risk_reason: operation.risk_reason || '',
    actual_completed_qty: Number(operation.actual_completed_qty || 0),
    actual_start_at: operation.actual_start_at || operation.actual_start || '',
    actual_last_report_at: operation.actual_last_report_at || '',
    actual_end_at: operation.actual_end_at || operation.actual_end || '',
    standard_id: operation.standard_id,
    standard_version: operation.standard_version,
    standard_match_scope: operation.standard_match_scope || '',
    standard_minutes_per_unit: Number(operation.standard_minutes_per_unit || 0),
    setup_minutes: Number(operation.setup_minutes || 0),
    difficulty_factor: Number(operation.difficulty_factor || 1),
    node_code_snapshot: operation.node_code_snapshot || '',
    node_name_snapshot: operation.node_name_snapshot || '',
    locked: Boolean(operation.locked),
    conflict_count: Number(operation.conflict_count || 0),
  }
  const segments = Array.isArray(operation.segments) ? operation.segments : []
  if (segments.length) {
    return segments.map((segment, index) => ({
      ...common,
      key: `segment:${common.operation_id}:${segment.id || index}`,
      production_node_id: segment.production_node_id || operation.production_node_id,
      node_code: segment.node_code || operation.node_code || operation.node_code_snapshot || '',
      node_name: segment.node_name || operation.node_name || operation.node_name_snapshot || '',
      quantity: Number(segment.quantity ?? operation.quantity ?? operation.scheduled_quantity ?? 0),
      occupied_minutes: Number(segment.occupied_minutes || 0),
      planned_start_at: segment.segment_start_at || segment.start_at || operation.planned_start_at || operation.plan_start || '',
      planned_end_at: segment.segment_end_at || segment.end_at || operation.planned_end_at || operation.plan_end || '',
      actual_start_at: segment.actual_start_at || common.actual_start_at,
      actual_last_report_at: segment.actual_last_report_at || common.actual_last_report_at,
      actual_end_at: segment.actual_end_at || common.actual_end_at,
      source: 'segment',
    }))
  }
  const allocations = Array.isArray(operation.allocations) ? operation.allocations : []
  const timedAllocations = allocations.filter(item => (
    item.allocation_start_at || item.segment_start_at || item.start_at
  ) && (item.allocation_end_at || item.segment_end_at || item.end_at))
  if (timedAllocations.length) {
    return timedAllocations.map((allocation, index) => ({
      ...common,
      key: `allocation:${common.operation_id}:${allocation.id || index}`,
      production_node_id: allocation.production_node_id || operation.production_node_id,
      node_code: allocation.node_code || operation.node_code || operation.node_code_snapshot || '',
      node_name: allocation.node_name || operation.node_name || operation.node_name_snapshot || '',
      quantity: Number(allocation.quantity ?? operation.quantity ?? operation.scheduled_quantity ?? 0),
      occupied_minutes: Number(allocation.occupied_minutes || 0),
      planned_start_at: allocation.allocation_start_at || allocation.segment_start_at || allocation.start_at || '',
      planned_end_at: allocation.allocation_end_at || allocation.segment_end_at || allocation.end_at || '',
      actual_start_at: allocation.actual_start_at || common.actual_start_at,
      actual_last_report_at: allocation.actual_last_report_at || common.actual_last_report_at,
      actual_end_at: allocation.actual_end_at || common.actual_end_at,
      source: 'allocation',
    }))
  }
  return [{
    ...common,
    key: `operation:${common.operation_id}`,
    production_node_id: operation.production_node_id,
    node_code: operation.node_code || operation.node_code_snapshot || '',
    node_name: operation.node_name || operation.node_name_snapshot || '',
    quantity: Number(operation.quantity ?? operation.scheduled_quantity ?? 0),
    occupied_minutes: Number(operation.occupied_minutes || operation.planned_minutes || 0),
    planned_start_at: operation.planned_start_at || operation.plan_start || '',
    planned_end_at: operation.planned_end_at || operation.plan_end || '',
    source: 'operation',
  }]
}

export function sortScheduleSegments(rows = []) {
  return [...rows].sort((left, right) => (
    String(left.planned_start_at || '').localeCompare(String(right.planned_start_at || ''))
    || String(left.planned_end_at || '').localeCompare(String(right.planned_end_at || ''))
    || String(left.key || '').localeCompare(String(right.key || ''))
  ))
}
