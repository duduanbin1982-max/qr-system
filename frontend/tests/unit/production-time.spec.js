import { describe, expect, it } from 'vitest'

import {
  addProductionDays,
  formatProductionDateTime,
  parseProductionTimestamp,
  productionApiTimestamp,
  productionCalendarParts,
  productionDate,
  productionDateTimeLocal,
} from '@/lib/productionTime.js'


describe('production time semantics', () => {
  it('uses the Shanghai date at the UTC cross-day boundary', () => {
    const instant = new Date('2026-10-09T16:30:00Z')
    expect(productionDate(instant)).toBe('2026-10-10')
    expect(productionDateTimeLocal(instant)).toBe('2026-10-10T00:30')
    expect(formatProductionDateTime(instant)).toBe('10-10 00:30')
  })

  it('normalizes local inputs and UTC inputs to explicit Shanghai offset', () => {
    expect(productionApiTimestamp('2026-10-10T08:00')).toBe('2026-10-10T08:00:00+08:00')
    expect(productionApiTimestamp('2026-10-10T00:00:00Z')).toBe('2026-10-10T08:00:00+08:00')
    expect(parseProductionTimestamp('2026-10-10 08:00').getTime()).toBe(
      parseProductionTimestamp('2026-10-10T00:00:00Z').getTime(),
    )
  })

  it('adds production calendar days without browser-timezone drift', () => {
    const monday = addProductionDays(parseProductionTimestamp('2026-10-10'), 2)
    expect(productionDate(monday)).toBe('2026-10-12')
    expect(productionCalendarParts(monday).weekday).toBe(1)
  })
})
