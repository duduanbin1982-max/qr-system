import { flushPromises, mount } from '@vue/test-utils'
import { describe, expect, it, vi } from 'vitest'

import WorkTimeReviewModal from '@/views/work-time/WorkTimeReviewModal.vue'


const mocks = vi.hoisted(() => ({
  reviewRecord: vi.fn(),
  showToast: vi.fn(),
}))

vi.mock('@/lib/api.js', () => ({
  api: {
    domains: {
      workTime: {
        reviewWorkTimeRecord: mocks.reviewRecord,
      },
    },
  },
}))

vi.mock('@/lib/store.js', () => ({
  showToast: mocks.showToast,
}))

describe('WorkTimeReviewModal', () => {
  it('hydrates the record and submits the reviewed effective time', async () => {
    mocks.reviewRecord.mockResolvedValue({})
    const wrapper = mount(WorkTimeReviewModal, {
      props: {
        modelValue: true,
        record: {
          id: 12,
          actual_minutes: 80,
          effective_minutes: 75,
          review_status: 'pending',
          abnormal_reason: '设备等待',
        },
      },
    })

    await wrapper.find('input[type="number"]').setValue('70')
    await wrapper.findAll('textarea')[1].setValue('复核后调整')
    await wrapper.find('.btn-primary').trigger('click')
    await flushPromises()

    expect(mocks.reviewRecord).toHaveBeenCalledWith(12, expect.objectContaining({
      effective_minutes: 70,
      review_status: 'approved',
      review_note: '复核后调整',
    }))
    expect(mocks.showToast).toHaveBeenCalledWith('审核已保存')
    expect(wrapper.emitted('update:modelValue')).toEqual([[false]])
    expect(wrapper.emitted('saved')).toHaveLength(1)
  })
})
