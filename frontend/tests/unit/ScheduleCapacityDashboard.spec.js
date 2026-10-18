import { DOMWrapper, flushPromises, mount } from '@vue/test-utils'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

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

let dashboard

function mountDashboard() {
  dashboard = mount(ScheduleCapacityDashboard, {
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
  return dashboard
}

async function openRevisionDialog() {
  const wrapper = mountDashboard()
  await wrapper.findAll('.schedule-dashboard__tabs button').find(button => button.text() === '版本与差异').trigger('click')
  await wrapper.get('.schedule-dashboard__revision-grid button').trigger('click')
  await flushPromises()
  return new DOMWrapper(document.body.querySelector('.schedule-revision-dialog'))
}

describe('ScheduleCapacityDashboard', () => {
  beforeEach(() => {
    vi.resetAllMocks()
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

  afterEach(() => {
    dashboard?.unmount()
    dashboard = null
    document.body.innerHTML = ''
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
  })

  it('shows bottleneck, risk, replan and locked-task work queues', async () => {
    const wrapper = mountDashboard()
    await wrapper.findAll('.schedule-dashboard__tabs button').find(button => button.text() === '风险工作台').trigger('click')

    expect(wrapper.text()).toContain('瓶颈生产节点')
    expect(wrapper.text()).toContain('交期风险订单')
    expect(wrapper.text()).toContain('新增返工')
    expect(wrapper.text()).toContain('人工锁定任务')
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
  })

  it('switches to the first immutable revision without loading a predecessor', async () => {
    const dialog = await openRevisionDialog()
    mocks.getScheduleRevision.mockClear()
    await dialog.get('select').setValue('76')
    await flushPromises()

    expect(mocks.getScheduleRevision).toHaveBeenCalledExactlyOnceWith('76', { limit: 1000 })
    expect(dialog.get('select').element.value).toBe('76')
    expect(dialog.get('.schedule-revision-dialog__diffs').text()).toContain('新增')
    expect(dialog.text()).not.toContain('正在加载排程版本')
  })

  it.each(['history', 'detail'])('releases loading and reports %s failure, then allows reopening', async (phase) => {
    const target = phase === 'history' ? mocks.listOrderScheduleRevisions : mocks.getScheduleRevision
    target.mockRejectedValueOnce(new Error('排程查询失败'))
    const dialog = await openRevisionDialog()

    expect(mocks.showToast).toHaveBeenCalledExactlyOnceWith('排程查询失败', 'error')
    expect(dialog.text()).not.toContain('正在加载排程版本')
    await dialog.get('header button').trigger('click')
    await dashboard.get('.schedule-dashboard__revision-grid button').trigger('click')
    await flushPromises()
    expect(document.body.querySelector('.schedule-revision-dialog__diffs').textContent).toContain('production_node_id')
  })

  it('uses saved dynamic-replan evidence ahead of inferred item differences', async () => {
    mocks.getScheduleRevision.mockResolvedValue({
      revision: { id: 77, revision_no: 2 },
      items: [{ order_process_id: 999, production_node_id: 1 }],
      replan_differences: [{
        id: 31, order_process_id: 99, change_type: 'node_changed',
        before: { production_node_id: 42, quantity: 3 },
        after: { production_node_id: 41, quantity: 3 },
      }],
    })
    const dialog = await openRevisionDialog()
    const differences = dialog.get('.schedule-revision-dialog__diffs')
    expect(differences.findAll('article')).toHaveLength(1)
    expect(differences.text()).toContain('订单工序 #99')
    expect(differences.text()).toContain('node_changed')
    expect(differences.text()).toContain('节点 42')
    expect(differences.text()).toContain('节点 41')
    expect(differences.text()).not.toContain('#999')
  })

  it('preserves payload compatibility, top-level precedence and added or removed operations', async () => {
    mocks.getScheduleRevision.mockImplementation(async (id) => ({
      revision: { id: Number(id), revision_no: Number(id) === 77 ? 2 : 1 },
      items: Number(id) === 77 ? [
        { order_process_id: 99, production_node_id: 41, payload_json: JSON.stringify({ production_node_id: 999, quantity: 3 }) },
        { order_process_id: 101, process_name_snapshot: '新增工序', payload_json: '{broken json' },
        { order_process_id: 102, production_node_id: 50 },
      ] : [
        { order_process_id: 99, payload_json: JSON.stringify({ production_node_id: 42, quantity: 3 }) },
        { order_process_id: 100, process_name_snapshot: '移除工序', payload_json: '{}' },
        { order_process_id: 102, production_node_id: 50 },
      ],
    }))
    const dialog = await openRevisionDialog()
    const differences = dialog.get('.schedule-revision-dialog__diffs')
    expect(differences.findAll('article')).toHaveLength(3)
    expect(differences.text()).toContain('production_node_id')
    expect(differences.text()).toContain('节点 42')
    expect(differences.text()).toContain('节点 41')
    expect(differences.text()).not.toContain('节点 999')
    expect(differences.text()).toContain('移除工序移除')
    expect(differences.text()).toContain('新增工序新增')
    expect(differences.text()).not.toContain('#102')
    expect(mocks.showToast).not.toHaveBeenCalled()
  })

  it('keeps equivalent UTC and Shanghai times on the same production date in revision evidence', async () => {
    mocks.getScheduleRevision.mockImplementation(async (id) => ({
      revision: { id: Number(id), revision_no: Number(id) === 77 ? 2 : 1 },
      items: [{
        order_process_id: 99,
        planned_start_at: Number(id) === 77 ? '2026-09-21T16:30:00Z' : '2026-09-22T00:30:00+08:00',
        planned_end_at: '2026-09-22T01:00:00+08:00', quantity: 3,
      }],
    }))
    const dialog = await openRevisionDialog()
    const versions = dialog.findAll('.schedule-revision-dialog__diffs article > div')
    expect(versions).toHaveLength(2)
    for (const version of versions) {
      expect(version.text()).toContain('09-22 00:30')
      expect(version.text()).toContain('09-22 01:00')
      expect(version.text()).not.toContain('09-21')
    }
  })
})
