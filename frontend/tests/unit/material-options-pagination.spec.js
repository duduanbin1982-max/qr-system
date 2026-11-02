import { ref } from 'vue'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import { useOrderMaterials } from '@/composables/order/useOrderMaterials.js'
import { useProductBom } from '@/composables/useProductResources.js'

const mocks = vi.hoisted(() => ({ listMaterials: vi.fn(), showToast: vi.fn() }))
vi.mock('@/lib/api.js', () => ({ api: { domains: { materials: { listMaterials: mocks.listMaterials } } } }))
vi.mock('@/lib/store.js', () => ({ showToast: mocks.showToast }))

function deferred() {
  let resolve
  let reject
  const promise = new Promise((done, fail) => { resolve = done; reject = fail })
  return { promise, resolve, reject }
}

beforeEach(() => Object.values(mocks).forEach(mock => mock.mockReset()))

describe.each([
  ['order recipe', () => useOrderMaterials({ modalId: ref(1), products: ref([]) })],
  ['product BOM', () => useProductBom(ref(1), ref({}))],
])('%s material options', (_label, create) => {
  it('loads every page, including material 501, with the server maximum page size', async () => {
    const first = Array.from({ length: 500 }, (_, index) => ({ id: index + 1 }))
    mocks.listMaterials
      .mockResolvedValueOnce({ materials: first, total: 501, page: 1, limit: 500 })
      .mockResolvedValueOnce({ materials: [{ id: 501 }], total: 501, page: 2, limit: 500 })
    const ui = create()
    await ui.loadMaterialOptions()
    expect(mocks.listMaterials.mock.calls).toEqual([[{ page: 1, limit: 500 }], [{ page: 2, limit: 500 }]])
    expect(ui.materialOptions.value).toHaveLength(501)
    expect(ui.materialOptions.value.at(-1).id).toBe(501)
  })

  it('does not expose an incomplete catalog when a later page fails', async () => {
    mocks.listMaterials
      .mockResolvedValueOnce({ materials: [{ id: 1 }], total: 2 })
      .mockRejectedValueOnce(new Error('page two failed'))
    const ui = create()
    await ui.loadMaterialOptions()
    expect(ui.materialOptions.value).toEqual([])
    expect(mocks.showToast).toHaveBeenCalledWith('page two failed', 'error')
  })

  it.each(['success', 'failure'])('ignores stale %s after a newer catalog loads', async outcome => {
    const old = deferred()
    mocks.listMaterials.mockImplementationOnce(() => old.promise)
      .mockResolvedValueOnce({ materials: [{ id: 2 }], total: 1 })
    const ui = create()
    const pending = ui.loadMaterialOptions()
    await ui.loadMaterialOptions()
    if (outcome === 'success') old.resolve({ materials: [{ id: 1 }], total: 1 })
    else old.reject(new Error('stale failure'))
    await pending
    expect(ui.materialOptions.value).toEqual([{ id: 2 }])
    expect(mocks.showToast).not.toHaveBeenCalled()
  })

  it('stops on an empty page even if the catalog shrinks during pagination', async () => {
    mocks.listMaterials
      .mockResolvedValueOnce({ materials: [{ id: 1 }], total: 100 })
      .mockResolvedValueOnce({ materials: [], total: 100 })
    const ui = create()
    await ui.loadMaterialOptions()
    expect(ui.materialOptions.value).toEqual([{ id: 1 }])
    expect(mocks.listMaterials).toHaveBeenCalledTimes(2)
  })
})
