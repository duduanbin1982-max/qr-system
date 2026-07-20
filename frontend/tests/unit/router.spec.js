import { nextTick } from 'vue'
import { beforeEach, describe, expect, it } from 'vitest'

import { navigate, restoreNavState, router } from '@/lib/router.js'


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
})
