import { mount } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'

import TraceOverview from '@/components/TraceOverview.vue'

function traceResult(status) {
  return {
    item: {
      serial_no: 'SERIAL-STATUS',
      status,
      position_no: 1,
      current_process_name: '焊接',
    },
    order: {
      order_no: 'ORDER-STATUS',
      product_name: '测试产品',
      status: 'producing',
      created_at: '2026-11-03 10:00:00',
    },
    work_records: [],
    meta: { page: 1, total_pages: 1 },
  }
}

describe('TraceOverview status contract', () => {
  it.each([
    ['pending', '待生产', 'badge-pending'],
    ['producing', '生产中', 'badge-warning'],
    ['completed', '已完成', 'badge-success'],
    ['cancelled', '已取消', 'badge-danger'],
    ['paused', '已暂停', 'badge-secondary'],
    ['in_progress', '生产中', 'badge-warning'],
    ['scrapped', '已报废', 'badge-danger'],
    ['deleted', '已删除', 'badge-danger'],
    ['unexpected', '未知状态', 'badge-info'],
    ['toString', '未知状态', 'badge-info'],
    [undefined, '未知状态', 'badge-info'],
  ])('renders %s consistently in order and serial summaries and product rows', (status, label, cls) => {
    const result = traceResult(status)
    result.order.status = status
    result.items = [{ ...result.item }]
    const wrapper = mount(TraceOverview, { props: { result } })
    const badges = wrapper.findAll('.badge')

    expect(badges).toHaveLength(3)
    for (const badge of badges) {
      expect(badge.text()).toBe(label)
      expect(badge.classes()).toContain(cls)
    }
  })

  it('updates shared status presentation when a different order is loaded', async () => {
    const wrapper = mount(TraceOverview, { props: { result: traceResult('completed') } })
    const result = traceResult('paused')
    result.order.status = 'cancelled'
    await wrapper.setProps({ result })

    const badges = wrapper.findAll('.badge')
    expect(badges[0].text()).toBe('已暂停')
    expect(badges[0].classes()).toContain('badge-secondary')
    expect(badges[1].text()).toBe('已取消')
    expect(badges[1].classes()).toContain('badge-danger')
  })

  it('renders scrapped products as scrapped instead of pending', () => {
    const wrapper = mount(TraceOverview, { props: { result: traceResult('scrapped') } })

    expect(wrapper.text()).toContain('已报废')
    expect(wrapper.text()).not.toContain('待处理')
    expect(wrapper.find('.badge-danger').exists()).toBe(true)
  })

  it('renders unknown product states explicitly', () => {
    const wrapper = mount(TraceOverview, { props: { result: traceResult('unexpected') } })

    expect(wrapper.text()).toContain('未知状态')
    expect(wrapper.text()).not.toContain('待处理')
  })

  it('shows historical evidence warnings without hiding the trace result', () => {
    const wrapper = mount(TraceOverview, {
      props: {
        result: {
          ...traceResult('completed'),
          meta: {
            page: 1,
            total_pages: 1,
            history_evidence: {
              has_legacy_fallback: true,
              has_missing: true,
            },
          },
        },
      },
    })

    expect(wrapper.text()).toContain('兼容回退')
    expect(wrapper.text()).toContain('缺少可验证的工序快照或版本证据')
    expect(wrapper.find('.trace-card').exists()).toBe(true)
  })

  it('provides controls for non-item collection pages', async () => {
    const wrapper = mount(TraceOverview, {
      props: {
        result: {
          ...traceResult('completed'),
          meta: {
            pagination: {
              items: { page: 1, per_page: 100, total: 1, total_pages: 1 },
              work_records: { page: 1, per_page: 100, total: 101, total_pages: 2 },
              quality_inspections: { page: 2, per_page: 100, total: 201, total_pages: 3 },
            },
          },
        },
      },
    })

    expect(wrapper.text()).toContain('历史集合分页')
    expect(wrapper.text()).toContain('报工')
    expect(wrapper.text()).toContain('质检')
    expect(wrapper.text()).toContain('第 2 / 3 页')
    const nextButton = wrapper.findAll('.trace-collection-pagination')[1].findAll('button')[1]
    await nextButton.trigger('click')
    expect(wrapper.emitted('collection-page')).toEqual([[
      { name: 'quality_inspections', page: 3, perPage: 100 },
    ]])
  })
})
