import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'
import { describe, expect, it } from 'vitest'

const source = readFileSync(resolve(process.cwd(), 'frontend/src/views/InventoryList.vue'), 'utf8')

describe('inventory product view layout', () => {
  it('keeps summary cards above the product catalogue', () => {
    expect(source.indexOf('inventory-summary-bar')).toBeGreaterThanOrEqual(0)
    expect(source.indexOf('inventory-product-card')).toBeGreaterThanOrEqual(0)
    expect(source.indexOf('inventory-summary-bar')).toBeLessThan(source.indexOf('inventory-product-card'))
  })
})
