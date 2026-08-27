import { beforeEach, describe, expect, it, vi } from 'vitest'

import { api } from '@/lib/api.js'


function response(status, payload) {
  return {
    status,
    ok: status >= 200 && status < 300,
    text: vi.fn(async () => JSON.stringify(payload)),
  }
}


describe('API facade transport contracts', () => {
  beforeEach(() => {
    vi.restoreAllMocks()
  })

  it('serializes performance score queries through the real facade and client', async () => {
    const fetchMock = vi.spyOn(globalThis, 'fetch').mockResolvedValue(
      response(200, { items: [], summary: {} }),
    )

    await expect(api.domains.performance.performanceScores({
      year_month: '2026-07',
      warning_level: '',
      position_id: null,
      per_page: 200,
    })).resolves.toEqual({ items: [], summary: {} })

    expect(fetchMock).toHaveBeenCalledWith(
      '/api/performance/scores?year_month=2026-07&per_page=200',
      { method: 'GET', headers: {}, credentials: 'same-origin' },
    )
  })

  it('preserves command payloads and maps server conflicts to the public error contract', async () => {
    const payload = {
      row_version: 4,
      idempotency_key: 'performance-ui:submit-supervisor-review:10:request-1',
    }
    const fetchMock = vi.spyOn(globalThis, 'fetch').mockResolvedValue(
      response(409, {
        error: '批次版本已变化',
        code: 'performance_batch_conflict',
        action: 'reload_performance_batch',
        details: { current_row_version: 5 },
      }),
    )

    await expect(
      api.domains.performance.submitPerformanceSupervisorReview(10, payload),
    ).rejects.toMatchObject({
      status: 409,
      domainCode: 'performance_batch_conflict',
      action: 'reload_performance_batch',
      details: { current_row_version: 5 },
    })

    expect(fetchMock).toHaveBeenCalledWith(
      '/api/performance/batches/10/submit-supervisor-review',
      {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        credentials: 'same-origin',
        body: JSON.stringify(payload),
      },
    )
  })
})
