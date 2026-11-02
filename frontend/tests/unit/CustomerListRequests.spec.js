import { flushPromises, mount } from '@vue/test-utils'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import CustomerList from '@/views/CustomerList.vue'


const mocks = vi.hoisted(() => ({
  listCustomers: vi.fn(),
  customerOrders: vi.fn(),
  createCustomer: vi.fn(),
  updateCustomer: vi.fn(),
  deleteCustomer: vi.fn(),
  showToast: vi.fn(),
}))

vi.mock('@/lib/api.js', () => ({
  api: { domains: { customers: mocks } },
}))
vi.mock('@/lib/auth.js', () => ({ can: () => true }))
vi.mock('@/lib/store.js', () => ({ showToast: mocks.showToast }))


function deferred() {
  let resolve
  let reject
  const promise = new Promise((res, rej) => { resolve = res; reject = rej })
  return { promise, resolve, reject }
}

function result(name, overrides = {}) {
  return {
    customers: [{ id: 1, name }],
    total: 1,
    summary: { total: 1, with_orders: 0, with_contact: 0, with_email: 0 },
    available_tags: ['VIP', '重点'],
    ...overrides,
  }
}

function rows(count, start = 1) {
  return Array.from({ length: count }, (_, index) => ({
    id: start + index,
    name: `Customer ${start + index}`,
  }))
}

const wrappers = []

async function openList() {
  const wrapper = mount(CustomerList)
  wrappers.push(wrapper)
  await flushPromises()
  return wrapper
}

async function search(wrapper, keyword) {
  const input = wrapper.get('input[placeholder="搜索名称/联系人/电话..."]')
  await input.setValue(keyword)
  await input.trigger('keyup.enter')
}

describe('CustomerList request and pagination lifecycle', () => {
  beforeEach(() => {
    for (const mock of Object.values(mocks)) mock.mockReset()
    mocks.listCustomers.mockResolvedValue(result('Initial customer'))
    mocks.customerOrders.mockResolvedValue({ orders: [], total: 0 })
    mocks.createCustomer.mockResolvedValue({})
    mocks.updateCustomer.mockResolvedValue({})
    mocks.deleteCustomer.mockResolvedValue({})
    vi.spyOn(window, 'confirm').mockReturnValue(true)
  })

  afterEach(() => {
    for (const wrapper of wrappers.splice(0)) {
      if (wrapper.exists()) wrapper.unmount()
    }
  })

  it('keeps the latest Enter search results, totals, summary and tags when an older success arrives', async () => {
    const wrapper = await openList()
    const older = deferred()
    const newer = deferred()
    mocks.listCustomers.mockReturnValueOnce(older.promise).mockReturnValueOnce(newer.promise)
    await search(wrapper, 'A')
    await search(wrapper, 'B')

    const latest = result('B customer', {
      total: 8,
      summary: { total: 8, with_orders: 2, with_contact: 5, with_email: 3 },
      available_tags: ['月结'],
    })
    newer.resolve(latest)
    await flushPromises()
    older.resolve(result('A customer', { total: 30, available_tags: ['沉睡'] }))
    await flushPromises()

    expect(wrapper.vm.searchKeyword).toBe('B')
    expect(wrapper.vm.customers).toEqual(latest.customers)
    expect(wrapper.vm.total).toBe(8)
    expect(wrapper.vm.summary).toEqual(latest.summary)
    expect(wrapper.vm.allTags).toEqual(['月结'])
    expect(wrapper.text()).toContain('B customer')
    expect(wrapper.text()).not.toContain('A customer')
    expect(wrapper.vm.loadError).toBe('')
    expect(wrapper.vm.loading).toBe(false)
  })

  it('ignores an older rejection after the latest search succeeds, including its toast', async () => {
    const wrapper = await openList()
    const older = deferred()
    const newer = deferred()
    mocks.listCustomers.mockReturnValueOnce(older.promise).mockReturnValueOnce(newer.promise)
    await search(wrapper, 'A')
    await search(wrapper, 'B')
    newer.resolve(result('B customer'))
    await flushPromises()
    older.reject(new Error('Older request failed'))
    await flushPromises()

    expect(wrapper.text()).toContain('B customer')
    expect(wrapper.vm.total).toBe(1)
    expect(wrapper.vm.loadError).toBe('')
    expect(mocks.showToast).not.toHaveBeenCalled()
  })

  it.each(['resolve', 'reject'])('keeps loading when an older request %s while the latest is pending', async outcome => {
    const wrapper = await openList()
    const older = deferred()
    const newer = deferred()
    mocks.listCustomers.mockReturnValueOnce(older.promise).mockReturnValueOnce(newer.promise)
    await search(wrapper, 'A')
    await wrapper.get('select').setValue('VIP')

    if (outcome === 'resolve') older.resolve(result('A customer'))
    else older.reject(new Error('Older request failed'))
    await flushPromises()
    expect(wrapper.vm.loading).toBe(true)
    expect(wrapper.text()).toContain('正在加载客户数据')
    expect(wrapper.vm.loadError).toBe('')
    expect(mocks.showToast).not.toHaveBeenCalled()
    expect(mocks.listCustomers).toHaveBeenLastCalledWith({
      page: 1, limit: 20, keyword: 'A', tag: 'VIP',
    })

    newer.resolve(result('VIP customer'))
    await flushPromises()
    expect(wrapper.vm.loading).toBe(false)
    expect(wrapper.text()).toContain('VIP customer')
  })

  it('shows the latest request failure and recovers through the visible retry button', async () => {
    const wrapper = await openList()
    mocks.listCustomers.mockRejectedValueOnce(new Error('Current request failed'))
    await search(wrapper, 'retry')
    await flushPromises()
    expect(wrapper.text()).toContain('Current request failed')
    expect(wrapper.vm.customers).toEqual([])
    expect(wrapper.vm.total).toBe(0)
    expect(wrapper.vm.loading).toBe(false)
    expect(mocks.showToast).toHaveBeenCalledExactlyOnceWith('Current request failed', 'error')

    mocks.listCustomers.mockResolvedValueOnce(result('Recovered customer'))
    await wrapper.get('.empty button').trigger('click')
    await flushPromises()
    expect(wrapper.text()).toContain('Recovered customer')
    expect(wrapper.vm.loadError).toBe('')
    expect(wrapper.vm.loading).toBe(false)
  })

  it.each(['resolve', 'reject'])('ignores a pending request that %s after the component unmounts', async outcome => {
    const wrapper = await openList()
    const request = deferred()
    mocks.listCustomers.mockReturnValueOnce(request.promise)
    const vm = wrapper.vm
    const pendingLoad = vm.load()
    const beforeUnmount = {
      customers: vm.customers,
      total: vm.total,
      summary: vm.summary,
      allTags: vm.allTags,
      page: vm.page,
      loading: vm.loading,
      error: vm.loadError,
    }
    wrapper.unmount()
    if (outcome === 'resolve') request.resolve(result('Detached result', { total: 0 }))
    else request.reject(new Error('Detached failure'))
    await pendingLoad
    await vm.load()

    expect({
      customers: vm.customers,
      total: vm.total,
      summary: vm.summary,
      allTags: vm.allTags,
      page: vm.page,
      loading: vm.loading,
      error: vm.loadError,
    }).toEqual(beforeUnmount)
    expect(mocks.listCustomers).toHaveBeenCalledTimes(2)
    expect(mocks.showToast).not.toHaveBeenCalled()
  })

  it.each([
    { initialTotal: 21, requestedPage: 2, finalTotal: 20, finalPage: 1 },
    { initialTotal: 41, requestedPage: 3, finalTotal: 40, finalPage: 2 },
    { initialTotal: 21, requestedPage: 2, finalTotal: 0, finalPage: 1 },
  ])('returns to page $finalPage when deletion shrinks $initialTotal customers to $finalTotal', async ({
    initialTotal, requestedPage, finalTotal, finalPage,
  }) => {
    mocks.listCustomers.mockResolvedValueOnce(result('Initial', { total: initialTotal }))
    const wrapper = await openList()
    wrapper.vm.page = requestedPage
    const deleted = { id: initialTotal, name: 'Last customer' }
    wrapper.vm.customers = [deleted]
    const finalRows = finalTotal ? rows(20, (finalPage - 1) * 20 + 1) : []
    mocks.listCustomers
      .mockResolvedValueOnce({ customers: [], total: finalTotal })
      .mockResolvedValueOnce({ customers: finalRows, total: finalTotal })

    await wrapper.vm.del(deleted)
    await flushPromises()

    expect(mocks.deleteCustomer).toHaveBeenCalledExactlyOnceWith(initialTotal)
    expect(mocks.listCustomers).toHaveBeenNthCalledWith(2, { page: requestedPage, limit: 20 })
    expect(mocks.listCustomers).toHaveBeenLastCalledWith({ page: finalPage, limit: 20 })
    expect(wrapper.vm.page).toBe(finalPage)
    expect(wrapper.vm.total).toBe(finalTotal)
    expect(wrapper.vm.customers).toEqual(finalRows)
    expect(wrapper.vm.loading).toBe(false)
    if (finalTotal) expect(wrapper.text()).not.toContain('暂无客户数据')
    else expect(wrapper.text()).toContain('暂无客户数据')
  })

  it('preserves the query snapshot while reloading after an edit removes the last matching customer', async () => {
    const wrapper = await openList()
    wrapper.vm.searchKeyword = 'original'
    wrapper.vm.tagFilter = 'VIP'
    wrapper.vm.page = 2
    wrapper.vm.openEdit({ id: 21, name: 'original customer', tags: 'VIP' })
    wrapper.vm.form.name = 'renamed customer'
    const outOfRange = deferred()
    const corrected = deferred()
    mocks.listCustomers.mockReturnValueOnce(outOfRange.promise).mockReturnValueOnce(corrected.promise)
    const save = wrapper.vm.save()
    await flushPromises()
    wrapper.vm.searchKeyword = 'not submitted'
    wrapper.vm.tagFilter = '重点'
    outOfRange.resolve({ customers: [], total: 20 })
    await flushPromises()
    expect(mocks.listCustomers).toHaveBeenLastCalledWith({
      page: 1, limit: 20, keyword: 'original', tag: 'VIP',
    })
    expect(wrapper.vm.loading).toBe(true)
    expect(wrapper.text()).not.toContain('暂无客户数据')

    corrected.resolve({ customers: rows(20), total: 20 })
    await save
    await flushPromises()
    expect(mocks.updateCustomer).toHaveBeenCalledTimes(1)
    expect(wrapper.vm.page).toBe(1)
    expect(wrapper.vm.customers).toHaveLength(20)
    expect(wrapper.vm.loading).toBe(false)
  })

  it('can follow more than one decrease in the last page without rendering an intermediate empty state', async () => {
    const wrapper = await openList()
    wrapper.vm.page = 4
    mocks.listCustomers
      .mockResolvedValueOnce({ customers: [], total: 41 })
      .mockResolvedValueOnce({ customers: [], total: 20 })
      .mockResolvedValueOnce({ customers: rows(20), total: 20 })

    await wrapper.vm.load()
    await flushPromises()
    expect(mocks.listCustomers.mock.calls.slice(1).map(([params]) => params.page)).toEqual([4, 3, 1])
    expect(wrapper.vm.page).toBe(1)
    expect(wrapper.vm.customers).toHaveLength(20)
    expect(wrapper.text()).not.toContain('暂无客户数据')
  })

  it('shows a failed corrected-page query and retries on the corrected page', async () => {
    const wrapper = await openList()
    wrapper.vm.page = 2
    mocks.listCustomers
      .mockResolvedValueOnce({ customers: [], total: 20 })
      .mockRejectedValueOnce(new Error('Corrected page failed'))
    await wrapper.vm.load()
    await flushPromises()
    expect(wrapper.vm.page).toBe(1)
    expect(wrapper.text()).toContain('Corrected page failed')
    expect(wrapper.vm.loading).toBe(false)
    expect(mocks.showToast).toHaveBeenCalledExactlyOnceWith('Corrected page failed', 'error')

    mocks.listCustomers.mockResolvedValueOnce({ customers: rows(20), total: 20 })
    await wrapper.vm.load()
    await flushPromises()
    expect(mocks.listCustomers).toHaveBeenLastCalledWith({ page: 1, limit: 20 })
    expect(wrapper.vm.page).toBe(1)
    expect(wrapper.vm.customers).toHaveLength(20)
    expect(wrapper.vm.loadError).toBe('')
  })

  it('does not let an obsolete out-of-range response move the latest query to another page', async () => {
    const wrapper = await openList()
    wrapper.vm.page = 3
    const obsolete = deferred()
    mocks.listCustomers.mockReturnValueOnce(obsolete.promise)
    const oldLoad = wrapper.vm.load()
    mocks.listCustomers.mockResolvedValueOnce(result('Latest search', { total: 1 }))
    await search(wrapper, 'latest')
    await flushPromises()
    obsolete.resolve({ customers: [], total: 0 })
    await oldLoad
    await flushPromises()

    expect(mocks.listCustomers).toHaveBeenCalledTimes(3)
    expect(wrapper.vm.page).toBe(1)
    expect(wrapper.text()).toContain('Latest search')
    expect(wrapper.vm.total).toBe(1)
    expect(wrapper.vm.loading).toBe(false)
  })

  it.each(['resolve', 'reject'])('ignores an obsolete corrected-page query that later %s', async outcome => {
    const wrapper = await openList()
    wrapper.vm.page = 3
    const obsoleteCorrection = deferred()
    const latest = deferred()
    mocks.listCustomers
      .mockResolvedValueOnce({ customers: [], total: 40 })
      .mockReturnValueOnce(obsoleteCorrection.promise)
    const oldLoad = wrapper.vm.load()
    await flushPromises()
    expect(wrapper.vm.page).toBe(2)
    mocks.listCustomers.mockReturnValueOnce(latest.promise)
    await search(wrapper, 'latest')

    if (outcome === 'resolve') obsoleteCorrection.resolve({ customers: rows(20, 21), total: 40 })
    else obsoleteCorrection.reject(new Error('Obsolete corrected page failed'))
    await oldLoad
    await flushPromises()
    expect(wrapper.vm.page).toBe(1)
    expect(wrapper.vm.loading).toBe(true)
    expect(wrapper.vm.loadError).toBe('')
    expect(mocks.showToast).not.toHaveBeenCalled()

    latest.resolve(result('Latest search'))
    await flushPromises()
    expect(wrapper.text()).toContain('Latest search')
    expect(wrapper.vm.total).toBe(1)
    expect(wrapper.vm.loading).toBe(false)
  })

  it('keeps completed latest results when an old corrected-page success arrives afterwards', async () => {
    const wrapper = await openList()
    wrapper.vm.page = 3
    const obsoleteCorrection = deferred()
    mocks.listCustomers
      .mockResolvedValueOnce({ customers: [], total: 40 })
      .mockReturnValueOnce(obsoleteCorrection.promise)
    const oldLoad = wrapper.vm.load()
    await flushPromises()
    mocks.listCustomers.mockResolvedValueOnce(result('Latest search'))
    await search(wrapper, 'latest')
    await flushPromises()
    obsoleteCorrection.resolve({ customers: rows(20, 21), total: 40 })
    await oldLoad
    await flushPromises()

    expect(wrapper.vm.page).toBe(1)
    expect(wrapper.text()).toContain('Latest search')
    expect(wrapper.vm.total).toBe(1)
    expect(wrapper.vm.loading).toBe(false)
  })
})
