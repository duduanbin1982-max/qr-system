import { describe, expect, it } from 'vitest'

import { formatCSVCell } from '@/lib/report-utils.js'


describe('formatCSVCell', () => {
  it.each([
    ['=1+1', "'=1+1"],
    [' +SUM(A1:A2)', "' +SUM(A1:A2)"],
    ['\t-2+3', "'\t-2+3"],
    ['@cmd', "'@cmd"],
  ])('neutralizes spreadsheet formulas in %j', (value, expected) => {
    expect(formatCSVCell(value)).toBe(expected)
  })

  it('quotes delimiters and escapes quotes', () => {
    expect(formatCSVCell('a,"b"')).toBe('"a,""b"""')
  })
})
