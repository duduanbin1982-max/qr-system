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

  it('uses a structured page header and separated order filter area', () => {
    expect(source).toContain('inventory-page-header')
    expect(source).toContain('inventory-order-filter-area')
    expect(styles).toMatch(/\.inventory-page\s*\{[^}]*width:\s*100%;/s)
    expect(styles).toMatch(/\.inventory-page\s*\{[^}]*max-width:\s*none;/s)
    expect(styles).toMatch(/\.inventory-order-filter-area\s*\{[^}]*background:/s)
  })
})
