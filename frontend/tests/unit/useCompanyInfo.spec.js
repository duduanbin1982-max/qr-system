import { flushPromises, mount } from '@vue/test-utils'
import { defineComponent, h } from 'vue'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import { useCompanyInfo } from '@/composables/settings/useCompanyInfo.js'


const mocks = vi.hoisted(() => ({
  getCompanyInfo: vi.fn(),
  saveCompanyInfo: vi.fn(),
  getCompanyInfoHistory: vi.fn(),
  can: vi.fn(),
  showToast: vi.fn(),
}))

vi.mock('@/lib/api.js', () => ({
  api: { domains: { settings: {
    getCompanyInfo: mocks.getCompanyInfo,
    saveCompanyInfo: mocks.saveCompanyInfo,
    getCompanyInfoHistory: mocks.getCompanyInfoHistory,
  } } },
}))
vi.mock('@/lib/auth.js', () => ({ can: mocks.can }))
vi.mock('@/lib/store.js', () => ({ showToast: mocks.showToast }))


const baseProfile = {
  company_name: '测试公司',
  contact: '杨冰',
  phone: '13800000000',
  address: '测试地址',
  description: '测试简介',
  version: 4,
  updated_at: '2026-08-16 10:00:00',
  updated_by_name: '管理员',
}


function mountHarness() {
  let companyInfo
  const harness = defineComponent({
    setup() {
      companyInfo = useCompanyInfo()
      return () => h('div')
    },
  })
  return {
    wrapper: mount(harness),
    get companyInfo() { return companyInfo },
  }
}


describe('useCompanyInfo', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    mocks.can.mockImplementation(permission => permission === 'company_info:edit')
    mocks.getCompanyInfo.mockResolvedValue({ profile: baseProfile })
    mocks.getCompanyInfoHistory.mockResolvedValue({
      sensitive_history_visible: false,
      revisions: [{ id: 1, version: 4, contact: '***' }],
    })
    mocks.saveCompanyInfo.mockResolvedValue({
      changed: true,
      profile: { ...baseProfile, company_name: '更新公司', version: 5 },
    })
  })

  it('loads only the scoped profile and its permission-filtered history', async () => {
    const harness = mountHarness()
    await flushPromises()

    expect(mocks.getCompanyInfo).toHaveBeenCalledTimes(1)
    expect(mocks.getCompanyInfoHistory).toHaveBeenCalledTimes(1)
    expect(harness.companyInfo.version.value).toBe(4)
    expect(harness.companyInfo.edits.value.company_name).toBe('测试公司')
    expect(harness.companyInfo.historyRedacted.value).toBe(true)
    expect(harness.companyInfo.canAuditHistory.value).toBe(false)
    harness.wrapper.unmount()
  })

  it('sends only changed fields with the loaded version and resets dirty state', async () => {
    const harness = mountHarness()
    await flushPromises()
    expect(harness.companyInfo.companyInfoDirty.value).toBe(false)

    harness.companyInfo.edits.value.company_name = '更新公司'
    expect(harness.companyInfo.companyInfoDirty.value).toBe(true)
    await harness.companyInfo.saveSettings()

    expect(mocks.saveCompanyInfo).toHaveBeenCalledWith({
      version: 4,
      company_name: '更新公司',
    })
    expect(harness.companyInfo.version.value).toBe(5)
    expect(harness.companyInfo.companyInfoDirty.value).toBe(false)
    harness.wrapper.unmount()
  })

  it('does not save in view-only mode', async () => {
    mocks.can.mockReturnValue(false)
    const harness = mountHarness()
    await flushPromises()
    harness.companyInfo.edits.value.company_name = '禁止更新'

    expect(await harness.companyInfo.saveSettings()).toBe(false)
    expect(mocks.saveCompanyInfo).not.toHaveBeenCalled()
    harness.wrapper.unmount()
  })

  it('preserves the draft and marks a stale-version conflict', async () => {
    const stale = new Error('数据冲突')
    stale.status = 409
    mocks.saveCompanyInfo.mockRejectedValue(stale)
    const harness = mountHarness()
    await flushPromises()
    harness.companyInfo.edits.value.address = '本地草稿地址'

    expect(await harness.companyInfo.saveSettings()).toBe(false)
    expect(harness.companyInfo.conflict.value).toBe(true)
    expect(harness.companyInfo.edits.value.address).toBe('本地草稿地址')
    expect(mocks.showToast).toHaveBeenCalledWith(
      '公司资料已被其他用户更新，请刷新后重新编辑', 'error',
    )
    harness.wrapper.unmount()
  })

  it('registers browser navigation protection while a draft is dirty', async () => {
    const harness = mountHarness()
    await flushPromises()
    harness.companyInfo.edits.value.contact = '未保存联系人'
    const event = new Event('beforeunload', { cancelable: true })
    window.dispatchEvent(event)

    expect(event.defaultPrevented).toBe(true)
    harness.wrapper.unmount()
  })
})
