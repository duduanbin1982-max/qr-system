import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'
import { describe, expect, it } from 'vitest'

const source = readFileSync(resolve(process.cwd(), 'frontend/src/views/InventoryList.vue'), 'utf8')
const styles = readFileSync(resolve(process.cwd(), 'frontend/src/style.css'), 'utf8')

describe('inventory product view layout', () => {
  it('keeps summary cards above the product catalogue', () => {
    expect(source.indexOf('inventory-summary-bar')).toBeGreaterThanOrEqual(0)
    expect(source.indexOf('inventory-product-card')).toBeGreaterThanOrEqual(0)
    expect(source.indexOf('inventory-summary-bar')).toBeLessThan(source.indexOf('inventory-product-card'))
  })

  it('uses a full-width vertical header for the order filter workbench', () => {
    expect(source).toContain('card-header inventory-order-header')
    expect(styles).toMatch(/\.inventory-order-header\s*\{[^}]*flex-direction:\s*column/s)
    expect(styles).toMatch(/\.inventory-order-header \.inventory-filter-workbench\s*\{[^}]*width:\s*100%/s)
  })
})
