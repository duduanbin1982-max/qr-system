import { flushPromises, mount } from '@vue/test-utils'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import ScheduleCapacityDashboard from '@/components/schedule/ScheduleCapacityDashboard.vue'


const mocks = vi.hoisted(() => ({
  listOrderScheduleRevisions: vi.fn(),
  getScheduleRevision: vi.fn(),
  showToast: vi.fn(),
}))

vi.mock('@/lib/api.js', () => ({
  api: {
    domains: {
      production: {
        listOrderScheduleRevisions: mocks.listOrderScheduleRevisions,
        getScheduleRevision: mocks.getScheduleRevision,
      },
    },
  },
}))

vi.mock('@/lib/store.js', () => ({ showToast: mocks.showToast }))

const nodes = [{
  id: 41,
  process_id: 7,
  process_name: '焊接',
  node_code: 'WELD-01',
  node_name: '焊接-01',
  calendar_id: 3,
  capacity_minutes: 540,
}]

const operations = [{
  id: 501,
  order_id: 12,
  order_no: '26092201',
  process_id: 7,
  process_name: '焊接',
  production_node_id: 41,
  node_code: 'WELD-01',
  node_name: '焊接-01',
  schedule_revision_id: 77,
  revision_status: 'draft',
  revision_approval_status: 'submitted',
  candidate_revision: true,
  locked: true,
  conflict_count: 0,
  segments: [{
    id: 1,
    production_node_id: 41,
    node_code: 'WELD-01',
    node_name: '焊接-01',
    segment_start_at: '2026-09-22 08:00:00',
    segment_end_at: '2026-09-22 11:00:00',
    occupied_minutes: 180,
    quantity: 3,
  }],
}]

function mountDashboard() {
  return mount(ScheduleCapacityDashboard, {
    attachTo: document.body,
    props: {
      operations,
      nodes,
      orders: [{
        id: 12,
        order_no: '26092201',
        schedule_replan_required: 1,
        schedule_replan_reason: '新增返工',
      }],
      audit: {
        calendars: [{ id: 3, weekly_workdays: '1,2,3,4,5' }],
        capacity_unavailability: [{
          id: 9,
          production_node_id: 41,
          start_at: '2026-09-22 12:00:00',
          end_at: '2026-09-22 13:00:00',
          unavailable_type: 'downtime',
        }],
        capacity_overrides: [{
          id: 10,
          production_node_id: 41,
          start_at: '2026-09-22 18:00:00',
          end_at: '2026-09-22 19:00:00',
          override_type: 'overtime',
        }],
        risk_orders: [{
          order_id: 12,
          order_no: '26092201',
          risk_level: 'high',
          risk_reason: '瓶颈节点产能不足',
          delay_minutes: 120,
        }],
      },
      downtime: [],
    },
  })
}

describe('ScheduleCapacityDashboard', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    document.body.innerHTML = ''
    mocks.listOrderScheduleRevisions.mockResolvedValue({
      revisions: [
        { id: 77, revision_no: 2, status: 'draft', approval_status: 'submitted' },
        { id: 76, revision_no: 1, status: 'published', approval_status: 'approved' },
      ],
    })
    mocks.getScheduleRevision.mockImplementation(async (id) => ({
      revision: { id: Number(id), revision_no: Number(id) === 77 ? 2 : 1, risk_level: 'high', delay_minutes: 120 },
      items: [{
        id: Number(id),
        order_process_id: 99,
        payload_json: JSON.stringify({
          order_process_id: 99,
          production_node_id: Number(id) === 77 ? 41 : 42,
          planned_start_at: Number(id) === 77 ? '2026-09-22 08:00:00' : '2026-09-22 09:00:00',
          planned_end_at: '2026-09-22 11:00:00',
          quantity: 3,
        }),
      }],
      conflict_summary: { blocking_count: 0 },
      replan_differences: [],
    }))
  })

  it('renders minute timeline and node capacity with downtime and overtime evidence', async () => {
    const wrapper = mountDashboard()
    await flushPromises()

    expect(wrapper.text()).toContain('排程与产能驾驶舱')
    expect(wrapper.text()).toContain('WELD-01')
    expect(wrapper.text()).toContain('26092201')
    expect(wrapper.text()).toContain('占用 3小时')
    expect(wrapper.text()).toContain('停机 1小时')
    expect(wrapper.text()).toContain('加班 +1小时')

    await wrapper.get('[data-test="timeline-group-mode"]').setValue('order')
    expect(wrapper.text()).toContain('26092201')
    wrapper.unmount()
  })

  it('shows bottleneck, risk, replan and locked-task work queues', async () => {
    const wrapper = mountDashboard()
    await wrapper.findAll('.schedule-dashboard__tabs button').find(button => button.text() === '风险工作台').trigger('click')

    expect(wrapper.text()).toContain('瓶颈生产节点')
    expect(wrapper.text()).toContain('交期风险订单')
    expect(wrapper.text()).toContain('新增返工')
    expect(wrapper.text()).toContain('人工锁定任务')
    wrapper.unmount()
  })

  it('loads immutable revision history and compares the selected version', async () => {
    const wrapper = mountDashboard()
    await wrapper.findAll('.schedule-dashboard__tabs button').find(button => button.text() === '版本与差异').trigger('click')
    await wrapper.get('.schedule-dashboard__revision-grid button').trigger('click')
    await flushPromises()

    expect(mocks.listOrderScheduleRevisions).toHaveBeenCalledWith(12, { limit: 100 })
    expect(mocks.getScheduleRevision).toHaveBeenCalledWith(77, { limit: 1000 })
    expect(mocks.getScheduleRevision).toHaveBeenCalledWith(76, { limit: 1000 })
    expect(document.body.textContent).toContain('排程版本与差异')
    expect(document.body.textContent).toContain('production_node_id')
    wrapper.unmount()
  })
})
