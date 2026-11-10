import { describe, expect, it } from 'vitest'
import {
  WAGE_TAB_DEFINITIONS,
  getVisibleWageTabs,
  resolveWageTab,
} from '@/composables/wage/wageTabs.js'

describe('wage tab policy', () => {
  it('keeps the tab registry immutable and centrally defined', () => {
    expect(Object.isFrozen(WAGE_TAB_DEFINITIONS)).toBe(true)
    expect(Object.isFrozen(WAGE_TAB_DEFINITIONS[0])).toBe(true)
    expect(WAGE_TAB_DEFINITIONS.map(tab => tab.id)).toEqual([
      'ledger', 'settlement', 'exceptions', 'adjustment', 'priceversions', 'my', 'piece',
      'monthly', 'process', 'compare', 'trend', 'position', 'predict',
    ])
  })

  it('filters tabs by any granted permission', () => {
    const visible = getVisibleWageTabs(permission => permission === 'wages:view_self')
    expect(visible.map(tab => tab.id)).toEqual(['my'])
  })

  it('exposes settlement to finance permissions but not employee self-view', () => {
    const visible = getVisibleWageTabs(permission => permission === 'wages:receipt')
    expect(visible.map(tab => tab.id)).toContain('settlement')
    expect(getVisibleWageTabs(permission => permission === 'wages:view_self')
      .map(tab => tab.id)).not.toContain('settlement')
  })

  it('prefers an allowed URL tab, then allowed persisted state, then the first tab', () => {
    const visible = [{ id: 'my' }, { id: 'piece' }]
    expect(resolveWageTab('piece', 'my', visible)).toBe('piece')
    expect(resolveWageTab('hidden', 'my', visible)).toBe('my')
    expect(resolveWageTab('hidden', 'also-hidden', visible)).toBe('my')
  })
})
