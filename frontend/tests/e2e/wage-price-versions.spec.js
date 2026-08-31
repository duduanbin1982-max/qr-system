import { expect, test } from '@playwright/test'

import { loginAdmin, observeRuntimeFailures, openSidebarPage } from './helpers.js'


const releaseActors = {
  preparer: { id: 901, name: 'E2E 制单人' },
  approver: { id: 902, name: 'E2E 独立批准人' },
}

function clone(value) {
  return JSON.parse(JSON.stringify(value))
}

function createWorkflowState({
  pendingRouteVersionId = 82,
  pendingRouteVersion = 2,
  pendingProcessVersionId = 72,
  pendingPriceId = null,
} = {}) {
  const currentItem = {
    id: 8101,
    process_id: 7,
    process_version_id: 71,
    process_code_snapshot: 'PROC-0007',
    process_name_snapshot: '精车',
    process_category: '机加工',
    process_version: 1,
    process_version_status: 'published',
    seq_order: 10,
    is_required: 1,
    required_audit: 1,
  }
  const pendingItem = {
    ...currentItem,
    id: pendingRouteVersionId * 100 + 1,
    process_version_id: pendingProcessVersionId,
    process_name_snapshot: `精车 V${pendingRouteVersion}`,
    process_version: pendingRouteVersion,
    process_version_status: 'pending_approval',
  }
  const state = {
    root: {
      id: 8,
      route_code: 'ROUTE-0008',
      name: '标准机加工路线',
      category: '机加工',
      description: '标准机加工路线',
      status: 'active',
      lifecycle_status: 'active',
      current_effective_version_id: 81,
      row_version: 5,
    },
    routeVersions: [
      {
        id: pendingRouteVersionId,
        process_route_id: 8,
        version: pendingRouteVersion,
        route_code_snapshot: 'ROUTE-0008',
        name: '标准机加工路线',
        category: '机加工',
        description: `待发布 V${pendingRouteVersion}`,
        status: 'pending_approval',
        content_digest: `route-v${pendingRouteVersion}`,
        row_version: 4,
        revision_reason: '更新精车工艺与精确工价',
        supersedes_version_id: 81,
        created_by: releaseActors.preparer.id,
        created_by_name: releaseActors.preparer.name,
        items: [pendingItem],
      },
      {
        id: 81,
        process_route_id: 8,
        version: 1,
        route_code_snapshot: 'ROUTE-0008',
        name: '标准机加工路线',
        category: '机加工',
        description: '历史 V1',
        status: 'published',
        content_digest: 'route-v1',
        row_version: 2,
        revision_reason: '历史基线',
        items: [currentItem],
      },
    ],
    prices: [
      {
        id: 101,
        route_id: 8,
        route_version_id: 81,
        route_name: '标准机加工路线',
        process_id: 7,
        process_version_id: 71,
        process_name: '精车',
        normal_unit_price_micros: 100000,
        rework_rate_basis_points: 5000,
        rework_rate_configured: 1,
        valid_from: '2026-01-01 07:00:00',
        valid_to: '',
        status: 'approved',
        row_version: 1,
      },
    ],
    batch: null,
    captures: {
      createdPrice: null,
      createdBatch: null,
      submittedBatch: null,
      approvedBatch: null,
      rejectedRoute: null,
    },
  }
  if (pendingPriceId) {
    state.prices.push({
      id: pendingPriceId,
      route_id: 8,
      route_version_id: pendingRouteVersionId,
      route_name: '标准机加工路线',
      process_id: 7,
      process_version_id: pendingProcessVersionId,
      process_name: pendingItem.process_name_snapshot,
      normal_unit_price_micros: 130000,
      valid_from: '2026-09-01 07:00:00',
      valid_to: '',
      status: 'draft',
      created_by: releaseActors.preparer.id,
      created_by_name: releaseActors.preparer.name,
      row_version: 0,
    })
  }
  return state
}

function currentRouteVersion(state) {
  return state.routeVersions.find(
    version => Number(version.id) === Number(state.root.current_effective_version_id)
  )
}

function referenceRows(state) {
  const current = currentRouteVersion(state)
  const candidates = [
    current,
    ...state.routeVersions.filter(version => version.status === 'pending_approval'),
  ].filter((version, index, versions) => (
    version && versions.findIndex(item => item.id === version.id) === index
  ))
  return candidates.flatMap(version => version.items.map(item => ({
    reference_key: `${version.id}:${item.process_version_id}`,
    route_id: 8,
    route_version_id: version.id,
    route_version: version.version,
    route_name: version.name,
    route_category: version.category,
    route_version_status: version.status,
    route_content_digest: version.content_digest,
    process_id: item.process_id,
    process_version_id: item.process_version_id,
    process_version: item.process_version,
    process_name: item.process_name_snapshot,
    process_version_status: item.process_version_status,
    process_content_digest: `process-v${item.process_version}`,
    seq_order: item.seq_order,
    pricing_mode: version.status === 'published'
      ? 'published_adjustment'
      : 'pending_group_release',
  })))
}

function routeListPayload(state) {
  const current = currentRouteVersion(state)
  const open = state.routeVersions.find(
    version => ['draft', 'pending_approval'].includes(version.status)
  )
  return {
    routes: [{
      ...state.root,
      route_version: current.version,
      route_version_id: open?.id || current.id,
      version_status: current.status,
      open_version_status: open?.status || '',
      processes: current.items,
      used_orders: 2,
      used_products: 1,
    }],
    total: 1,
    summary: {
      total_routes: 1,
      category_counts: { 机加工: 1 },
      process_nodes_total: 1,
    },
  }
}

function batchPayload(state) {
  if (!state.batch) return null
  const route = state.routeVersions.find(version => version.id === state.batch.routeVersionId)
  const item = route.items[0]
  const price = state.prices.find(version => version.id === state.batch.priceVersionId)
  return {
    id: 41,
    release_no: state.batch.releaseNo,
    revision_reason: state.batch.reason,
    status: state.batch.status,
    row_version: state.batch.rowVersion,
    created_by: releaseActors.preparer.id,
    created_by_name: releaseActors.preparer.name,
    approved_by: state.batch.status === 'published' ? releaseActors.approver.id : null,
    approved_by_name: state.batch.status === 'published' ? releaseActors.approver.name : '',
    process_versions: [{
      id: item.process_version_id,
      process_id: item.process_id,
      version: item.process_version,
      name: item.process_name_snapshot,
      status: item.process_version_status,
    }],
    route_versions: [clone(route)],
    price_versions: price ? [clone(price)] : [],
  }
}

async function fulfillJson(route, body, status = 200) {
  await route.fulfill({
    status,
    contentType: 'application/json',
    body: JSON.stringify(body),
  })
}

async function installWorkflowApi(page, state) {
  await page.route('**/api/**', async route => {
    const request = route.request()
    const method = request.method()
    const url = new URL(request.url())
    const path = url.pathname

    if (path === '/api/route-price-versions/reference' && method === 'GET') {
      return fulfillJson(route, { items: referenceRows(state) })
    }
    if (path === '/api/route-price-versions' && method === 'GET') {
      const routeVersionId = Number(url.searchParams.get('route_version_id'))
      const versions = routeVersionId
        ? state.prices.filter(price => Number(price.route_version_id) === routeVersionId)
        : state.prices
      return fulfillJson(route, { versions: clone(versions) })
    }
    if (path === '/api/route-price-versions' && method === 'POST') {
      state.captures.createdPrice = request.postDataJSON()
      const reference = referenceRows(state).find(row => (
        Number(row.route_version_id) === Number(state.captures.createdPrice.route_version_id)
        && Number(row.process_version_id) === Number(state.captures.createdPrice.process_version_id)
      ))
      const price = {
        id: 301,
        ...state.captures.createdPrice,
        route_name: reference.route_name,
        process_name: reference.process_name,
        normal_unit_price_micros: Math.round(
          Number(state.captures.createdPrice.normal_unit_price) * 10000
        ),
        rework_rate_basis_points: 0,
        rework_rate_configured: 0,
        valid_to: '',
        status: 'draft',
        created_by: releaseActors.preparer.id,
        created_by_name: releaseActors.preparer.name,
        row_version: 0,
      }
      state.prices.push(price)
      return fulfillJson(route, clone(price))
    }
    if (path === '/api/process-routes' && method === 'GET') {
      return fulfillJson(route, routeListPayload(state))
    }
    if (path === '/api/processes' && method === 'GET') {
      return fulfillJson(route, {
        processes: referenceRows(state).map(row => ({
          id: row.process_id,
          process_version_id: row.process_version_id,
          process_version: row.process_version,
          process_name: row.process_name,
          name: row.process_name,
          category: '机加工',
          version_status: row.process_version_status,
        })),
      })
    }
    if (path === '/api/process-routes/8/versions' && method === 'GET') {
      return fulfillJson(route, {
        route: clone(state.root),
        versions: clone(state.routeVersions),
        events: [],
      })
    }
    const impactMatch = path.match(/^\/api\/process-route-versions\/(\d+)\/impact$/)
    if (impactMatch && method === 'GET') {
      return fulfillJson(route, {
        impact: { total_references: Number(impactMatch[1]) === 81 ? 3 : 0, references: [] },
      })
    }
    const rejectMatch = path.match(/^\/api\/process-route-versions\/(\d+)\/reject$/)
    if (rejectMatch && method === 'POST') {
      state.captures.rejectedRoute = request.postDataJSON()
      const version = state.routeVersions.find(item => item.id === Number(rejectMatch[1]))
      version.status = 'draft'
      version.row_version += 1
      for (const price of state.prices.filter(item => (
        item.route_version_id === version.id && item.status === 'draft'
      ))) {
        price.status = 'voided'
        price.row_version += 1
        price.void_reason = state.captures.rejectedRoute.reason
        price.voided_at = '2026-08-24 15:30:00'
        price.voided_by = releaseActors.approver.id
        price.voided_by_name = releaseActors.approver.name
      }
      return fulfillJson(route, clone(version))
    }
    if (path === '/api/master-data-release-batches' && method === 'GET') {
      const batch = batchPayload(state)
      return fulfillJson(route, { batches: batch ? [batch] : [] })
    }
    if (path === '/api/master-data-release-batches' && method === 'POST') {
      state.captures.createdBatch = request.postDataJSON()
      state.batch = {
        releaseNo: state.captures.createdBatch.release_no,
        reason: state.captures.createdBatch.revision_reason,
        routeVersionId: state.captures.createdBatch.route_version_ids[0],
        priceVersionId: state.captures.createdBatch.price_version_ids[0],
        status: 'draft',
        rowVersion: 0,
      }
      return fulfillJson(route, batchPayload(state))
    }
    if (path === '/api/master-data-release-batches/41' && method === 'GET') {
      return fulfillJson(route, { batch: batchPayload(state) })
    }
    if (path === '/api/master-data-release-batches/41/submit' && method === 'POST') {
      state.captures.submittedBatch = request.postDataJSON()
      state.batch.status = 'pending_approval'
      state.batch.rowVersion += 1
      return fulfillJson(route, batchPayload(state))
    }
    if (path === '/api/master-data-release-batches/41/approve' && method === 'POST') {
      state.captures.approvedBatch = request.postDataJSON()
      state.batch.status = 'published'
      state.batch.rowVersion += 1
      const routeVersion = state.routeVersions.find(
        version => version.id === state.batch.routeVersionId
      )
      const previous = currentRouteVersion(state)
      previous.status = 'superseded'
      routeVersion.status = 'published'
      routeVersion.row_version += 1
      routeVersion.items[0].process_version_status = 'published'
      state.root.current_effective_version_id = routeVersion.id
      state.root.row_version += 1
      const price = state.prices.find(version => version.id === state.batch.priceVersionId)
      price.status = 'approved'
      price.row_version += 1
      price.approved_by = releaseActors.approver.id
      price.approved_by_name = releaseActors.approver.name
      return fulfillJson(route, batchPayload(state))
    }
    return route.fallback()
  })
}

async function assertNoDocumentOverflow(page, width) {
  expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(width)
}


test('pending V2 price is exact, grouped, published, and leaves V1 history visible', async ({ page }) => {
  const failures = observeRuntimeFailures(page)
  const state = createWorkflowState()
  await installWorkflowApi(page, state)

  await loginAdmin(page)
  await openSidebarPage(page, '工资核算', '工资批次台账')
  const main = page.locator('.main-content')
  await main.getByRole('button', { name: '工价版本', exact: true }).click()
  await main.getByTestId('view-pending-route').click()
  await expect(main.getByText('标准机加工路线 · 待发布 V2')).toBeVisible()
  await main.getByTestId('create-price-82:72').click()

  const editor = page.getByTestId('price-version-editor')
  await expect(editor).toContainText('只能随路线成组发布')
  await expect(editor.getByTestId('locked-route')).toHaveValue('标准机加工路线 · V2')
  await expect(editor.getByTestId('locked-process')).toHaveValue('精车 V2 · V2')
  await editor.getByTestId('price-unit-input').fill('13.7500')
  await editor.getByTestId('price-remark-input').fill('待发布 V2 精确定价')
  await editor.getByTestId('save-price-draft').click()

  await expect.poll(() => state.captures.createdPrice?.route_id).toBe(8)
  expect(state.captures.createdPrice).toMatchObject({
    route_id: 8,
    route_version_id: 82,
    process_id: 7,
    process_version_id: 72,
    expected_route_content_digest: 'route-v2',
    expected_process_content_digest: 'process-v2',
    normal_unit_price: '13.75',
    remark: '待发布 V2 精确定价',
  })

  await page.setViewportSize({ width: 1440, height: 900 })
  await page.screenshot({
    path: 'test-results/pending-route-price-v2-desktop.png',
    fullPage: true,
  })
  await assertNoDocumentOverflow(page, 1440)

  await openSidebarPage(page, '基础设置', '基础设置')
  await main.getByRole('button', { name: '工序路线' }).click()
  await expect(main.getByRole('heading', { name: '工序路线', exact: true })).toBeVisible()
  await main.getByRole('button', { name: '标准机加工路线', exact: true }).click()
  const routeDetail = page.locator('.route-detail-modal')
  await expect(routeDetail.getByRole('button', { name: '待审批 V2' })).toBeVisible()
  await expect(routeDetail.locator('.coverage-table')).toContainText('#301 草稿 ¥13.7500')
  await expect(routeDetail.locator('.coverage-table')).toContainText('V2')

  await routeDetail.getByRole('button', { name: '加入成组发布' }).click()
  const releaseModal = page.locator('.release-workbench-modal')
  await releaseModal.getByRole('button', { name: '新建发布批次' }).click()
  await expect(releaseModal.locator('.create-scope')).toContainText('工序版本 1')
  await expect(releaseModal.locator('.create-scope')).toContainText('路线版本 1')
  await expect(releaseModal.locator('.create-scope')).toContainText('工价版本 1')
  await releaseModal.getByText('发布批次号').locator('input').fill('MDR-E2E-V2')
  await releaseModal.getByText('发布原因').locator('textarea').fill('V2 路线工序工价成组发布')
  await releaseModal.getByRole('button', { name: '创建草稿批次' }).click()

  await expect.poll(() => state.captures.createdBatch?.route_version_ids).toEqual([82])
  expect(state.captures.createdBatch).toMatchObject({
    process_version_ids: [72],
    route_version_ids: [82],
    price_version_ids: [301],
  })
  await releaseModal.getByRole('button', { name: '提交审批' }).click()
  await expect.poll(() => state.captures.submittedBatch?.row_version).toBe(0)

  const disposition = releaseModal.locator('.disposition-row').first()
  await disposition.locator('select').first().selectOption('price_version')
  await disposition.locator('select').nth(1).selectOption('301')
  await releaseModal.getByRole('button', { name: '批准并原子发布' }).click()

  await expect.poll(() => state.captures.approvedBatch?.price_dispositions).toEqual([{
    process_id: 7,
    disposition: 'price_version',
    price_version_id: 301,
  }])
  expect(releaseActors.approver.id).not.toBe(releaseActors.preparer.id)
  expect(batchPayload(state)).toMatchObject({
    status: 'published',
    created_by: releaseActors.preparer.id,
    approved_by: releaseActors.approver.id,
  })

  await releaseModal.getByRole('button', { name: '关闭' }).click()
  await expect(routeDetail.getByRole('button', { name: '当前版本 V2' })).toBeVisible()
  const historySelect = routeDetail.getByLabel('历史版本')
  await historySelect.selectOption('81')
  await expect(historySelect).toHaveValue('81')
  await expect(routeDetail).toContainText('V1 · 已取代')
  await expect(routeDetail.locator('.coverage-table')).toContainText('#101 已批准 ¥10.0000')
  expect(state.prices.find(price => price.id === 101)).toMatchObject({
    route_version_id: 81,
    process_version_id: 71,
    status: 'approved',
  })

  await page.setViewportSize({ width: 390, height: 844 })
  await expect(routeDetail).toBeVisible()
  await assertNoDocumentOverflow(page, 390)
  await page.screenshot({
    path: 'test-results/pending-route-price-v1-history-mobile.png',
    fullPage: true,
  })
  expect(failures).toEqual([])
})


test('rejecting pending V3 keeps its price only as immutable voided history', async ({ page }) => {
  const failures = observeRuntimeFailures(page)
  const state = createWorkflowState({
    pendingRouteVersionId: 83,
    pendingRouteVersion: 3,
    pendingProcessVersionId: 73,
    pendingPriceId: 401,
  })
  await installWorkflowApi(page, state)

  await loginAdmin(page)
  const main = page.locator('.main-content')
  await openSidebarPage(page, '基础设置', '基础设置')
  await main.getByRole('button', { name: '工序路线' }).click()
  await expect(main.getByRole('heading', { name: '工序路线', exact: true })).toBeVisible()
  await main.getByRole('button', { name: '标准机加工路线', exact: true }).click()
  const routeDetail = page.locator('.route-detail-modal')
  await expect(routeDetail.getByRole('button', { name: '待审批 V3' })).toBeVisible()
  await expect(routeDetail.locator('.coverage-table')).toContainText('#401 草稿 ¥13.0000')
  await routeDetail.getByRole('button', { name: '驳回', exact: true }).click()
  await page.locator('.command-modal textarea').fill('节点需要调整')
  await page.locator('.command-modal').getByRole('button', { name: '确认' }).click()

  await expect.poll(() => state.captures.rejectedRoute?.reason).toBe('节点需要调整')
  expect(state.prices.find(price => price.id === 401)).toMatchObject({
    status: 'voided',
    void_reason: '节点需要调整',
    voided_by: releaseActors.approver.id,
  })

  await routeDetail.locator('.modal-close').click()
  await expect(routeDetail).toBeHidden()
  await openSidebarPage(page, '工资核算', '工资批次台账')
  await main.getByRole('button', { name: '工价版本', exact: true }).click()
  await main.getByTestId('view-voided').click()
  await expect(main.locator('.voided-table')).toContainText('标准机加工路线')
  await expect(main.locator('.voided-table')).toContainText('精车 V3')
  await expect(main.locator('.voided-table')).toContainText('节点需要调整')
  await expect(main.locator('.voided-table')).toContainText(releaseActors.approver.name)
  await expect(main.getByText('标准机加工路线 · 待发布 V3')).toHaveCount(0)

  await page.setViewportSize({ width: 390, height: 844 })
  await assertNoDocumentOverflow(page, 390)
  await page.screenshot({
    path: 'test-results/pending-route-price-v3-voided-mobile.png',
    fullPage: true,
  })
  expect(failures).toEqual([])
})
