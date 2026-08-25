import { nextTick } from 'vue'
import { beforeEach, describe, expect, it } from 'vitest'

import { navigate, requestedNavigation, restoreNavState, router } from '@/lib/router.js'


describe('navigation state', () => {
  beforeEach(() => {
    router.page = 'login'
    router.params = {}
    router.subPage = null
    router.tab = null
  })

  it('persists explicit navigation and restores tab state', async () => {
    navigate('orders', { id: 7 })
    router.subPage = 'roles'
    router.tab = 'daily'
    await nextTick()

    expect(localStorage.getItem('currentPage')).toBe('orders')
    expect(router.params).toEqual({ id: 7 })

    router.subPage = null
    router.tab = null
    restoreNavState()

    expect(router.subPage).toBe('roles')
    expect(router.tab).toBe('daily')
  })

  it('parses legacy entrypoint navigation without mutating router state', () => {
    expect(requestedNavigation('?page=settings&settings_tab=audit-logs')).toEqual({
      page: 'settings',
      settingsTab: 'audit-logs',
      wageTab: '',
      routeVersionId: null,
      processVersionId: null,
    })
    expect(router.page).toBe('login')
  })

  it('parses exact route price navigation intent', () => {
    expect(requestedNavigation(
      '?page=wages&wage_tab=priceversions&route_version_id=82&process_version_id=72'
    )).toEqual({
      page: 'wages',
      settingsTab: '',
      wageTab: 'priceversions',
      routeVersionId: 82,
      processVersionId: 72,
    })
  })
})
