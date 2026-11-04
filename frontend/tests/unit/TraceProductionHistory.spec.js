import { mount } from '@vue/test-utils'
import { describe, expect, it, vi } from 'vitest'

import TraceProductionHistory from '@/components/TraceProductionHistory.vue'

function result() {
  return {
    order: { id: 1, created_at: '2026-11-04 08:00:00' },
    work_records: [
      { id: 1, process_name: '晚报工', created_at: '2026-11-04 14:00:00', worker_name: '王', quantity: 2 },
      { id: 1, process_name: '早报工', created_at: '2026-11-04 09:00:00', worker_name: '杜', quantity: 1 },
    ],
    quality_inspections: [{ id: 1, process_name: '终检', inspected_at: '2026-11-04 13:00:00', result: 'pass', quantity_checked: 2 }],
    inventory_logs: [{ id: 1, product_name: '产品', created_at: '2026-11-04 11:00:00', type: 'in', quantity: 2 }],
    shipments: [{ id: 1, shipment_no: 'SHIP', completed_at: '2026-11-04 12:00:00', order_quantity: 2 }],
  }
}

const lifecycle = wrapper => wrapper.get('[data-testid="trace-lifecycle"]')

describe('TraceProductionHistory lifecycle presentation', () => {
  it('interleaves event types while retaining each original detail and API array order', () => {
    const input = result()
    const snapshot = JSON.stringify(input)
    const wrapper = mount(TraceProductionHistory, { props: { result: input } })
    expect(lifecycle(wrapper).findAll('strong').map(node => node.text())).toEqual([
      '订单创建', '早报工', '入库 · 产品', '发货 · SHIP', '终检 质检', '晚报工',
    ])
    const rows = lifecycle(wrapper).findAll('.timeline-row')
    expect(rows[1].text()).toContain('杜 · +1')
    expect(rows[2].text()).toContain('+2')
    expect(rows[3].text()).toContain('数量 2')
    expect(rows[4].text()).toContain('合格 · 抽检 2')
    expect(wrapper.findAll('.trace-card')[0].findAll('strong').map(node => node.text())).toEqual(['晚报工', '早报工'])
    expect(JSON.stringify(input)).toBe(snapshot)
  })

  it('updates when an order is replaced and renders duplicate IDs without Vue key warnings', async () => {
    const warn = vi.spyOn(console, 'warn').mockImplementation(() => {})
    const wrapper = mount(TraceProductionHistory, { props: { result: result() } })
    await wrapper.setProps({ result: { work_records: [
      { id: 1, process_name: '新报工A', created_at: '2026-11-05 10:00:00' },
      { id: 1, process_name: '新报工B', created_at: '2026-11-05 10:00:00' },
    ] } })
    expect(lifecycle(wrapper).findAll('strong').map(node => node.text())).toEqual(['新报工A', '新报工B'])
    expect(wrapper.text()).not.toContain('晚报工')
    expect(warn).not.toHaveBeenCalled()
  })

  it('keeps missing and invalid times visible after all valid events', () => {
    const input = result()
    input.order.created_at = null
    input.quality_inspections[0].inspected_at = 'invalid'
    const wrapper = mount(TraceProductionHistory, { props: { result: input } })
    const rows = lifecycle(wrapper).findAll('.timeline-row')
    expect(rows.slice(-2).map(node => node.get('strong').text())).toEqual(['订单创建', '终检 质检'])
    expect(rows.slice(-2).every(node => node.text().includes('时间缺失'))).toBe(true)
  })

  it('retains serial-mode order-scope logistics and reacts to nested collection changes', async () => {
    const input = result()
    input.item = { serial_no: 'SERIAL' }
    input.order_scope = {
      inventory_logs: [{ id: 1, product_name: '订单产品', created_at: '2026-11-04 10:00:00' }],
      shipments: [{ id: 1, shipment_no: 'ORDER-SHIP', completed_at: '2026-11-04 11:00:00' }],
    }
    const wrapper = mount(TraceProductionHistory, { props: { result: input } })
    expect(lifecycle(wrapper).text()).toContain('订单入库 · 订单产品')
    expect(lifecycle(wrapper).text()).toContain('订单发货 · ORDER-SHIP')
    expect(lifecycle(wrapper).text()).not.toContain('发货 · SHIP')
    await wrapper.setProps({ result: { ...input, order_scope: {} } })
    expect(lifecycle(wrapper).findAll('[data-kind="inventory"], [data-kind="shipment"]')).toHaveLength(0)
  })
})
