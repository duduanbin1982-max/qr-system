import { describe, expect, it } from 'vitest'

import { getOrderStatus } from '@/lib/orderStatus.js'

describe('shared order status presentation', () => {
  it.each([
    ['pending', '待生产', 'badge-pending'],
    ['producing', '生产中', 'badge-warning'],
    ['completed', '已完成', 'badge-success'],
    ['cancelled', '已取消', 'badge-danger'],
    ['paused', '已暂停', 'badge-secondary'],
    ['in_progress', '生产中', 'badge-warning'],
    ['scrapped', '已报废', 'badge-danger'],
    ['deleted', '已删除', 'badge-danger'],
  ])('maps %s to its Chinese label and badge class', (status, label, cls) => {
    expect(getOrderStatus(status)).toEqual({ label, cls })
  })

  it.each([
    'unexpected', '', 'toString', 'constructor', '__proto__',
    null, undefined, false, 0, {}, ['completed'],
  ])('renders unknown input %j explicitly', (status) => {
    expect(getOrderStatus(status)).toEqual({ label: '未知状态', cls: 'badge-info' })
  })

  it('keeps historical in_progress presentation consistent with producing', () => {
    expect(getOrderStatus('in_progress')).toEqual(getOrderStatus('producing'))
  })

  it('prevents consumers from changing shared status definitions', () => {
    expect(Object.isFrozen(getOrderStatus('pending'))).toBe(true)
    expect(Object.isFrozen(getOrderStatus('unexpected'))).toBe(true)
  })
})
