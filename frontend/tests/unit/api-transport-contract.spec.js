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

  it('exposes immutable schedule revision queries and publish commands', async () => {
    const fetchMock = vi.spyOn(globalThis, 'fetch').mockResolvedValue(
      response(200, { ok: true, revision: { id: 8 }, items: [] }),
    )

    await expect(
      api.domains.production.listOrderScheduleRevisions(42, { limit: 10 }),
    ).resolves.toEqual({ ok: true, revision: { id: 8 }, items: [] })
    expect(fetchMock).toHaveBeenNthCalledWith(
      1,
      '/api/schedule/order/42/revisions?limit=10',
      { method: 'GET', headers: {}, credentials: 'same-origin' },
    )

    await expect(
      api.domains.production.publishScheduleRevision(8, { published_by: 1000 }),
    ).resolves.toEqual({ ok: true, revision: { id: 8 }, items: [] })
    expect(fetchMock).toHaveBeenNthCalledWith(
      2,
      '/api/schedule/revisions/8/publish',
      {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        credentials: 'same-origin',
        body: JSON.stringify({ published_by: 1000 }),
      },
    )
  })

  it('serializes schedule downtime list, create, and cancellation commands', async () => {
    const fetchMock = vi.spyOn(globalThis, 'fetch').mockResolvedValue(
      response(200, { ok: true, events: [{ id: 7 }] }),
    )

    await expect(api.domains.production.listScheduleDowntime({ limit: 500 })).resolves.toEqual({
      ok: true,
      events: [{ id: 7 }],
    })
    expect(fetchMock).toHaveBeenNthCalledWith(
      1,
      '/api/schedule/downtime?limit=500',
      { method: 'GET', headers: {}, credentials: 'same-origin' },
    )

    await expect(api.domains.production.createScheduleDowntime({
      process_line_id: 41,
      start_at: '2026-09-01T08:00',
      end_at: '2026-09-01T09:30',
      reason: '设备检修',
    })).resolves.toEqual({ ok: true, events: [{ id: 7 }] })
    expect(fetchMock).toHaveBeenNthCalledWith(
      2,
      '/api/schedule/downtime',
      {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        credentials: 'same-origin',
        body: JSON.stringify({
          process_line_id: 41,
          start_at: '2026-09-01T08:00',
          end_at: '2026-09-01T09:30',
          reason: '设备检修',
        }),
      },
    )

    await expect(api.domains.production.cancelScheduleDowntime(7)).resolves.toEqual({
      ok: true,
      events: [{ id: 7 }],
    })
    expect(fetchMock).toHaveBeenNthCalledWith(
      3,
      '/api/schedule/downtime/7',
      { method: 'DELETE', headers: {}, credentials: 'same-origin' },
    )
  })
})
