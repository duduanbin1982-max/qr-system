import { describe, expect, it } from 'vitest'

import { buildTraceTimeline } from '@/lib/traceTimeline.js'

const at = (hour) => `2026-11-04 ${hour}:00:00`

function result() {
  return {
    order: { id: 1, created_at: at('08') },
    work_records: [{ id: 1, created_at: at('09'), process_name: '焊接' }],
    quality_inspections: [{ id: 1, inspected_at: at('10'), process_name: '终检' }],
    inventory_logs: [{ id: 1, created_at: at('11'), product_name: '产品' }],
    shipments: [{ id: 1, completed_at: at('12'), shipment_no: 'SHIP-1' }],
  }
}

describe('trace lifecycle timeline', () => {
  it.each([
    ['10', '11', '12', ['order', 'work', 'quality', 'inventory', 'shipment']],
    ['12', '10', '13', ['order', 'work', 'inventory', 'quality', 'shipment']],
    ['12', '11', '10', ['order', 'work', 'shipment', 'inventory', 'quality']],
  ])('sorts inspection %s, inventory %s and shipment %s by actual time', (quality, inventory, shipment, expected) => {
    const input = result()
    input.quality_inspections[0].inspected_at = at(quality)
    input.inventory_logs[0].created_at = at(inventory)
    input.shipments[0].completed_at = at(shipment)
    expect(buildTraceTimeline(input).map(event => event.kind)).toEqual(expected)
  })

  it('uses kind priority then numeric stable ID for equal timestamps', () => {
    const input = result()
    for (const value of Object.values(input)) {
      for (const row of Array.isArray(value) ? value : [value]) {
        row.created_at = at('10')
        if ('inspected_at' in row) row.inspected_at = at('10')
        if ('completed_at' in row) row.completed_at = at('10')
      }
    }
    input.work_records = [10, 2, 1].map(id => ({ id, created_at: at('10') }))
    expect(buildTraceTimeline(input).map(event => [event.kind, event.stable_id])).toEqual([
      ['order', '1'], ['work', '1'], ['work', '2'], ['work', '10'],
      ['quality', '1'], ['inventory', '1'], ['shipment', '1'],
    ])
  })

  it('compares naive production time with explicit offsets independently of browser timezone', () => {
    const events = buildTraceTimeline({
      work_records: [
        { id: 3, created_at: '2026-11-04T02:00:00Z' },
        { id: 2, created_at: '2026-11-04T10:00:00+08:00' },
        { id: 1, created_at: at('10') },
        { id: 4, created_at: '2026-11-03T21:00:00-05:00' },
      ],
    })
    expect(events.map(event => event.stable_id)).toEqual(['1', '2', '3', '4'])
    expect(new Set(events.map(event => event.timestamp)).size).toBe(1)
  })

  it('uses a total, locale-independent order for mixed numeric, textual and missing IDs', () => {
    const records = [2, 10, '1a', undefined, '9007199254740993', '9007199254740992']
      .map(id => ({ id, created_at: at('10') }))
    const expected = ['2', '10', '9007199254740992', '9007199254740993', '', '1a']
    expect(buildTraceTimeline({ work_records: records }).map(event => event.stable_id)).toEqual(expected)
    expect(buildTraceTimeline({ work_records: [...records].reverse() }).map(event => event.stable_id)).toEqual(expected)
  })

  it('puts missing and invalid timestamps last, with an explicit missing-time label', () => {
    const events = buildTraceTimeline({
      order: { id: 1 },
      work_records: [
        { id: 4, created_at: '' },
        { id: 3, created_at: 'not-a-date' },
        { id: 2, created_at: at('12') },
        { id: 1, created_at: null },
      ],
    })
    expect(events.map(event => [event.kind, event.stable_id])).toEqual([
      ['work', '2'], ['order', '1'], ['work', '1'], ['work', '3'], ['work', '4'],
    ])
    expect(events.slice(1).every(event => event.timestamp === null && event.time_label === '时间缺失')).toBe(true)
  })

  it('preserves microsecond ordering instead of breaking sub-millisecond ties by ID', () => {
    const events = buildTraceTimeline({ work_records: [
      { id: 1, created_at: '2026-11-04 10:00:00.000009' },
      { id: 2, created_at: '2026-11-04 10:00:00.000001' },
      { id: 3, created_at: '2026-11-04 10:00:00.123456' },
    ] })
    expect(events.map(event => event.stable_id)).toEqual(['2', '1', '3'])
    expect(events[1].timestamp).toBeGreaterThan(events[0].timestamp)
  })

  it.each(['2026-02-30 10:00:00', '2026-13-04 10:00:00', '2026-11-04 24:00:00', '2026-11-04 10:60:00', 123, false])(
    'does not coerce an invalid calendar timestamp %j into an event time', (created_at) => {
      expect(buildTraceTimeline({ order: { created_at } })[0].timestamp).toBeNull()
    },
  )

  it('retains timestamp fallback fields and labels in the DTO', () => {
    const events = buildTraceTimeline({
      quality_inspections: [{ id: 1, created_at: at('10'), process_name: '终检' }],
      inventory_logs: [{ id: 2, created_at: at('11'), product_model: 'MODEL' }],
      shipments: [{ id: 3, created_at: at('12'), shipment_no: 'SHIP' }],
    })
    expect(events.map(event => event.label)).toEqual(['终检 质检', '入库 · MODEL', '发货 · SHIP'])
    expect(events.map(event => event.time_label)).toEqual([at('10'), at('11'), at('12')])
    expect(events.every(event => Number.isFinite(event.timestamp))).toBe(true)
  })

  it('keeps duplicate IDs, cross-kind IDs and missing IDs without rendering-key collisions', () => {
    const input = {
      order: { id: 1, created_at: at('10') },
      work_records: [1, 1, undefined, undefined, '1:0', '["work","1",0]'].map(id => ({ id, created_at: at('10') })),
      quality_inspections: [{ id: 1, inspected_at: at('10') }],
    }
    const events = buildTraceTimeline(input)
    expect(events).toHaveLength(8)
    expect(new Set(events.map(event => event.key)).size).toBe(8)
    expect(buildTraceTimeline(input)).toEqual(events)
    expect(events.filter(event => event.kind === 'work' && event.stable_id === '1').map(event => event.payload))
      .toEqual(input.work_records.slice(0, 2))
  })

  it('does not mutate frozen API arrays or payloads while sorting', () => {
    const records = Object.freeze([
      Object.freeze({ id: 2, created_at: at('12') }),
      Object.freeze({ id: 1, created_at: at('09') }),
    ])
    const input = Object.freeze({ work_records: records })
    const snapshot = JSON.stringify(input)
    const events = buildTraceTimeline(input)
    expect(events.map(event => event.stable_id)).toEqual(['1', '2'])
    expect(events[0].payload).toBe(records[1])
    expect(JSON.stringify(input)).toBe(snapshot)
  })

  it('uses only order_scope logistics in serial mode and preserves order-level labels', () => {
    const input = result()
    input.item = { serial_no: 'SERIAL' }
    input.order_scope = {
      inventory_logs: [{ id: 22, created_at: at('11'), product_name: '订单产品' }],
      shipments: [{ id: 33, completed_at: at('12'), shipment_no: 'ORDER-SHIP' }],
    }
    const events = buildTraceTimeline(input)
    expect(events.find(event => event.kind === 'inventory').label).toBe('订单入库 · 订单产品')
    expect(events.find(event => event.kind === 'shipment').stable_id).toBe('33')
    delete input.order_scope
    expect(buildTraceTimeline(input).some(event => ['inventory', 'shipment'].includes(event.kind))).toBe(false)
  })

  it('handles absent optional collections', () => {
    expect(buildTraceTimeline({})).toEqual([])
  })
})
