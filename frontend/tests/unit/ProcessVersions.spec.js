import { flushPromises, mount } from '@vue/test-utils'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import ImpactSummaryPanel from '@/components/master-data/ImpactSummaryPanel.vue'
import VersionDiffPanel from '@/components/master-data/VersionDiffPanel.vue'
import {
  processVersionErrorMessage,
  useProcessVersions,
} from '@/composables/useProcessVersions.js'
import { processVersionsApi } from '@/lib/api/process-versions.js'


const mocks = vi.hoisted(() => ({
  createVersionedProcess: vi.fn(),
  listProcessVersions: vi.fn(),
  getProcessVersion: vi.fn(),
  createProcessRevision: vi.fn(),
  updateProcessVersion: vi.fn(),
  submitProcessVersion: vi.fn(),
  approveProcessVersion: vi.fn(),
  rejectProcessVersion: vi.fn(),
  getProcessVersionImpact: vi.fn(),
  requestProcessRetirement: vi.fn(),
  requestProcessReactivation: vi.fn(),
  approveProcessRetirement: vi.fn(),
  approveProcessReactivation: vi.fn(),
  request: vi.fn(),
}))

vi.mock('@/lib/api.js', () => ({
  api: { domains: { processVersions: mocks } },
}))
vi.mock('@/lib/api/client.js', () => ({ request: mocks.request }))

const root = {
  id: 7,
  process_code: 'PROC-0007',
  lifecycle_status: 'active',
  current_effective_version_id: 71,
  row_version: 4,
}

function version(overrides = {}) {
  return {
    id: 71,
    process_id: 7,
    version: 1,
    name: '精车',
    category: '机加工',
    description: '精加工',
    seq_order: 20,
    status: 'published',
    row_version: 2,
    revision_reason: '历史基线',
    ...overrides,
  }
}

function detailPayload(versions, rootOverrides = {}) {
  return { process: { ...root, ...rootOverrides }, versions, events: [] }
}

describe('useProcessVersions', () => {
  beforeEach(() => {
    Object.values(mocks).forEach((mock) => mock.mockReset())
    mocks.getProcessVersionImpact.mockResolvedValue({
      impact: { references: [], total_references: 0 },
    })
  })

  it('creates a stable process root and V1 draft with a command idempotency key', async () => {
    const draft = version({ id: 72, version: 1, status: 'draft', row_version: 0 })
    const draftRoot = { ...root, current_effective_version_id: null, row_version: 0 }
    mocks.createVersionedProcess.mockResolvedValue({ root: draftRoot, version: draft })
    mocks.listProcessVersions.mockResolvedValue(detailPayload([draft], draftRoot))

    const state = useProcessVersions()
    await state.createProcess({
      name: ' 精车 ',
      category: '机加工',
      description: '精加工',
      seq_order: 20,
      revision_reason: '新增精加工工序',
    })

    expect(mocks.createVersionedProcess).toHaveBeenCalledOnce()
    expect(mocks.createVersionedProcess).toHaveBeenCalledWith(expect.objectContaining({
      name: '精车',
      category: '机加工',
      description: '精加工',
      seq_order: 20,
      revision_reason: '新增精加工工序',
      idempotency_key: expect.stringMatching(/^process-create:/),
    }))
    expect(state.selectedVersion.value.id).toBe(72)
  })

  it('sends the root row version when creating a revision and blocks duplicate clicks', async () => {
    const published = version()
    const draft = version({
      id: 72,
      version: 2,
      status: 'draft',
      row_version: 0,
      supersedes_version_id: 71,
      revision_reason: '优化参数',
    })
    mocks.listProcessVersions
      .mockResolvedValueOnce(detailPayload([published]))
      .mockResolvedValue(detailPayload([published, draft]))

    let finishCreate
    mocks.createProcessRevision.mockImplementation(() => new Promise((resolve) => {
      finishCreate = resolve
    }))

    const state = useProcessVersions()
    await state.loadProcess(7)
    const first = state.createRevision({ ...published, revision_reason: '优化参数' })
    const duplicate = state.createRevision({ ...published, revision_reason: '重复请求' })

    await expect(duplicate).resolves.toBeNull()
    expect(mocks.createProcessRevision).toHaveBeenCalledOnce()
    expect(mocks.createProcessRevision).toHaveBeenCalledWith(7, expect.objectContaining({
      row_version: 4,
      revision_reason: '优化参数',
      idempotency_key: expect.stringMatching(/^process-revision:/),
      name: '精车',
      category: '机加工',
      seq_order: 20,
    }))

    finishCreate(draft)
    await first
    expect(state.busy.value).toBe(false)
    expect(state.selectedVersion.value.id).toBe(72)
  })

  it('uses version row versions for draft updates and approval transitions', async () => {
    const draft = version({ id: 72, version: 2, status: 'draft', row_version: 5 })
    const updated = { ...draft, name: '精车二序', row_version: 6 }
    const pending = { ...updated, status: 'pending_approval', row_version: 7 }
    const published = { ...pending, status: 'published', row_version: 8 }
    mocks.updateProcessVersion.mockResolvedValue(updated)
    mocks.submitProcessVersion.mockResolvedValue(pending)
    mocks.approveProcessVersion.mockResolvedValue(published)
    mocks.listProcessVersions
      .mockResolvedValueOnce(detailPayload([updated]))
      .mockResolvedValueOnce(detailPayload([pending]))
      .mockResolvedValueOnce(detailPayload([published], { current_effective_version_id: 72, row_version: 5 }))

    const state = useProcessVersions()
    state.selectedVersion.value = draft
    await state.updateDraft({ ...draft, name: '精车二序' })
    expect(mocks.updateProcessVersion).toHaveBeenCalledWith(72, expect.objectContaining({
      row_version: 5,
      name: '精车二序',
    }))

    await state.transition('submit')
    expect(mocks.submitProcessVersion).toHaveBeenCalledWith(72, {
      row_version: 6,
      idempotency_key: expect.stringMatching(/^process-submit:/),
    })

    await state.transition('approve')
    expect(mocks.approveProcessVersion).toHaveBeenCalledWith(72, {
      row_version: 7,
      idempotency_key: expect.stringMatching(/^process-approve:/),
    })
  })

  it('sends reject and lifecycle reasons without replacing server workflow rules', async () => {
    const pending = version({ id: 72, version: 2, status: 'pending_approval', row_version: 7 })
    const rejected = { ...pending, status: 'rejected', row_version: 8 }
    mocks.rejectProcessVersion.mockResolvedValue(rejected)
    mocks.requestProcessRetirement.mockResolvedValue({ id: 91, status: 'pending' })
    mocks.requestProcessReactivation.mockResolvedValue({ id: 92, status: 'pending' })
    mocks.listProcessVersions.mockResolvedValue(detailPayload([rejected]))

    const state = useProcessVersions()
    state.root.value = { ...root }
    state.selectedProcess.value = { id: 7 }
    state.selectedVersion.value = pending

    await state.transition('reject', '参数依据不完整')
    expect(mocks.rejectProcessVersion).toHaveBeenCalledWith(72, {
      row_version: 7,
      reason: '参数依据不完整',
      idempotency_key: expect.stringMatching(/^process-reject:/),
    })

    state.root.value = { ...root, row_version: 6 }
    await state.requestLifecycle('retire', '旧工艺停止使用')
    expect(mocks.requestProcessRetirement).toHaveBeenCalledWith(7, {
      row_version: 6,
      reason: '旧工艺停止使用',
      idempotency_key: expect.stringMatching(/^process-retire:/),
    })

    state.root.value = { ...root, lifecycle_status: 'retired', row_version: 8 }
    await state.requestLifecycle('reactivate', '新修订版已经发布')
    expect(mocks.requestProcessReactivation).toHaveBeenCalledWith(7, {
      row_version: 8,
      reason: '新修订版已经发布',
      idempotency_key: expect.stringMatching(/^process-reactivate:/),
    })
  })

  it('turns concurrency and separation conflicts into explicit next actions', () => {
    expect(processVersionErrorMessage({ action: 'refresh_process_version' })).toContain('刷新版本详情')
    expect(processVersionErrorMessage({ action: 'select_different_approver' })).toContain('切换批准账号')
    expect(processVersionErrorMessage({ action: 'resolve_release_dependencies' })).toContain('影响处置')
  })

  it('keeps version details available when impact scope is not authorized', async () => {
    mocks.listProcessVersions.mockResolvedValue(detailPayload([version()]))
    mocks.getProcessVersionImpact.mockRejectedValue(new Error('无权限访问'))

    const state = useProcessVersions()
    await expect(state.loadProcess(7)).resolves.toEqual(detailPayload([version()]))

    expect(state.selectedVersion.value.id).toBe(71)
    expect(state.impact.value).toBeNull()
    expect(state.impactError.value).toBe('无权限访问')
  })
})

describe('process version API routes', () => {
  beforeEach(() => {
    mocks.request.mockReset()
    mocks.request.mockResolvedValue({})
  })

  it('uses only versioned write and lifecycle endpoints', async () => {
    const payload = { row_version: 3, idempotency_key: 'command-12345678' }
    await processVersionsApi.createVersionedProcess(payload)
    await processVersionsApi.createProcessRevision(7, payload)
    await processVersionsApi.updateProcessVersion(72, payload)
    await processVersionsApi.submitProcessVersion(72, payload)
    await processVersionsApi.approveProcessVersion(72, payload)
    await processVersionsApi.rejectProcessVersion(72, payload)
    await processVersionsApi.requestProcessRetirement(7, payload)
    await processVersionsApi.requestProcessReactivation(7, payload)

    expect(mocks.request.mock.calls).toEqual([
      ['POST', '/api/process-versions', payload],
      ['POST', '/api/processes/7/revisions', payload],
      ['PUT', '/api/process-versions/72', payload],
      ['POST', '/api/process-versions/72/submit', payload],
      ['POST', '/api/process-versions/72/approve', payload],
      ['POST', '/api/process-versions/72/reject', payload],
      ['POST', '/api/processes/7/retirement-requests', payload],
      ['POST', '/api/processes/7/reactivation-requests', payload],
    ])
  })
})

describe('process version shared panels', () => {
  it('renders backend business labels and suggested actions without a table-name dictionary', async () => {
    const wrapper = mount(ImpactSummaryPanel, {
      props: {
        impact: {
          total_references: 3,
          references: [{
            key: 'route_prices',
            label: '工价版本',
            count: 3,
            impact_level: 'high',
            suggested_action: '发布前确认工价处置',
          }],
        },
      },
    })
    await flushPromises()

    expect(wrapper.text()).toContain('工价版本')
    expect(wrapper.text()).toContain('发布前确认工价处置')
    expect(wrapper.text()).not.toContain('route_prices')
  })

  it('shows immutable version content differences', () => {
    const wrapper = mount(VersionDiffPanel, {
      props: {
        before: version({ version: 1, name: '精车' }),
        after: version({ version: 2, name: '精车二序' }),
      },
    })

    expect(wrapper.text()).toContain('V1')
    expect(wrapper.text()).toContain('V2')
    expect(wrapper.text()).toContain('精车二序')
  })
})
