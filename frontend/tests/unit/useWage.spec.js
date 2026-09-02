import { describe, expect, it } from 'vitest'

import { buildPieceworkCsvRows } from '@/composables/useWage.js'


describe('buildPieceworkCsvRows', () => {
  const fmtDate = value => String(value || '').slice(0, 10)
  const fmtMoney = value => Number(value || 0).toFixed(2)

  it('includes product code in detail rows and keeps subtotal columns aligned', () => {
    const rows = buildPieceworkCsvRows([
      {
        employee_name: '张三',
        position_name: '车工',
        employee_no: '1001',
        total_quantity: 2,
        total_wage: 10.5,
        details: [{
          date: '2026-09-02 08:00:00',
          order_no: '26090201',
          product_name: '静音外壳',
          product_code: 'P-195',
          process_name: '焊接',
          quantity: 2,
          unit_price: 5.25,
          wage: 10.5,
        }],
      },
    ], fmtDate, fmtMoney)

    expect(rows[0]).toEqual(['姓名', '岗位', '工号', '日期', '订单号', '产品', '产品编码', '工序', '数量', '单价', '工资'])
    expect(rows[1]).toEqual(['张三', '车工', '1001', '2026-09-02', '26090201', '静音外壳', 'P-195', '焊接', 2, '5.25', '10.50'])
    expect(rows[2]).toEqual(['张三', '车工', '1001', '', '', '', '', '小计', 2, '', '10.50'])
    expect(rows[3]).toEqual(['', '', '', '', '', '', '', '合计', 2, '', '10.50'])
  })

  it('exports an empty product code when legacy detail has none', () => {
    const rows = buildPieceworkCsvRows([
      { employee_name: '李四', total_quantity: 0, total_wage: 0, details: [{ product_name: '旧产品' }] },
    ], fmtDate, fmtMoney)

    expect(rows[1][6]).toBe('')
  })
})
