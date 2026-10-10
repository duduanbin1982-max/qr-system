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

  it('fills the product table container and keeps the product code readable', () => {
    expect(styles).toMatch(/\.inventory-product-scroll\s*\{[^}]*--inventory-product-code-width:\s*220px;/s)
    expect(styles).toMatch(/\.inventory-product-table\s*\{[^}]*width:\s*max\(100%,\s*var\(--inventory-product-table-min-width\)\);/s)
    expect(styles).toMatch(/\.inventory-product-table\s+\.inventory-frozen--code\s*\{[^}]*overflow-wrap:\s*anywhere;/s)
  })

  it('pins the mobile detail action on the opposite edge of the product code', () => {
    expect(styles).toMatch(/@media\s*\(max-width:\s*768px\)[\s\S]*?\.inventory-product-table\s+\.inventory-mobile-actions\s*\{[^}]*position:\s*sticky;[^}]*right:\s*0;/s)
    expect(styles).toMatch(/\.inventory-product-table\s+\.inventory-mobile-actions\s*\{[^}]*z-index:\s*3;/s)
    expect(styles).toMatch(/thead\s+th\.inventory-mobile-actions\s*\{[^}]*z-index:\s*9;/s)
  })
})
