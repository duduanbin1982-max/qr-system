import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'
import { runInNewContext } from 'node:vm'

import { describe, expect, it } from 'vitest'


describe('mobile quality evaluation task order', () => {
  it('places required groups and required cards first', () => {
    const source = readFileSync(
      resolve(process.cwd(), 'public/js/mobile/mobile-quality-evaluation.js'),
      'utf8',
    )
    const context = {}
    runInNewContext(source, context)

    const groups = context.groupQualityEvaluationTasks([
      { id: 1, trigger_work_record_id: 10, is_required: 0 },
      { id: 2, trigger_work_record_id: 20, is_required: 0 },
      { id: 3, trigger_work_record_id: 20, is_required: 1 },
      { id: 4, trigger_work_record_id: 30, is_required: 1 },
    ])

    expect(groups.map(group => group.key)).toEqual(['work:20', 'work:30', 'work:10'])
    expect(groups[0].rows.map(task => task.id)).toEqual([3, 2])
  })
})
