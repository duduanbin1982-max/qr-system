import assert from 'node:assert/strict'
import { mkdtempSync, mkdirSync, readFileSync, rmSync, writeFileSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { dirname, join } from 'node:path'
import { test } from 'node:test'
import {
  baselineBootstrapDrift,
  baselineDriftAgainstBase,
  checkFrontendLayers,
  importSpecifiers,
  validateBaselineManifest,
} from '../../scripts/check-frontend-layers.mjs'

function fixture(files, legacyEdges = new Map()) {
  const root = mkdtempSync(join(tmpdir(), 'frontend-layers-'))
  if (!Object.hasOwn(files, 'lib/productionTime.js')) {
    files = { ...files, 'lib/productionTime.js': `export const productionDate = () => '2026-10-14'` }
  }
  for (const [name, body] of Object.entries(files)) {
    const path = join(root, name)
    mkdirSync(dirname(path), { recursive: true })
    writeFileSync(path, name.endsWith('.vue') && !body.trim().startsWith('<') ? `<script setup>\n${body}\n</script>` : body)
  }
  try {
    return checkFrontendLayers(root, { legacyEdges })
  } finally {
    rmSync(root, { recursive: true, force: true })
  }
}

test('valid nested View to Component to Composable to API facade chain and pure tool pass', () => {
  const result = fixture({
    'views/nested/Page.vue': `<script setup>import Box from '@/components/nested/Box.vue'; import { productionDate } from '@/lib/productionTime.js'</script>`,
    'components/nested/Box.vue': `<script setup>import { useData } from '@/composables/nested/useData.js'</script>`,
    'composables/nested/useData.js': `import { api } from '@/lib/api.js'; export const useData = () => api.domains.orders.listOrders()`,
    'lib/api.js': `export * from './api/orders.js'`,
    'lib/api/orders.js': `import { request } from './client.js'`,
    'lib/api/client.js': `export const request = () => fetch('/api/orders')`,
    'lib/productionTime.js': `export const productionDate = () => '2026-10-14'`,
  })
  assert.deepEqual(result.violations, [])
})

for (const [name, files, expected] of [
  ['nested View importing API implementation', {
    'views/nested/Page.vue': `import { request } from '@/lib/api/client.js'`,
    'lib/api/client.js': `export const request = () => {}`,
  }, 'cannot depend on api-implementation'],
  ['nested View importing API facade without migration', {
    'views/nested/Page.vue': `import { api } from '@/lib/api.js'`,
    'lib/api.js': `export const api = {}`,
  }, 'cannot depend on api-facade'],
  ['Component importing unlisted lib module', {
    'components/nested/Box.vue': `import { helper } from '@/lib/unsafe.js'`,
    'lib/unsafe.js': `export const helper = () => 1`,
  }, 'cannot depend on support'],
  ['Component importing a View', {
    'components/nested/Box.vue': `import Page from '@/views/nested/Page.vue'`,
    'views/nested/Page.vue': `<template><main/></template>`,
  }, 'cannot depend on views'],
  ['Composable importing a Component', {
    'composables/nested/useData.js': `export { default } from '@/components/Box.vue'`,
    'components/Box.vue': `<template><div/></template>`,
  }, 'cannot depend on components'],
  ['View using fetch directly', {
    'views/nested/Page.vue': `<script setup>fetch('/api/orders')</script>`,
  }, 'direct HTTP transport'],
  ['Vue template invoking fetch directly', {
    'views/Page.vue': `<template><button @click="fetch('/api/orders')">Load</button></template>`,
  }, 'direct HTTP transport'],
  ['Vue template importing API implementation', {
    'views/Page.vue': `<template><button @click="import('@/lib/api/client.js')">Load</button></template>`,
    'lib/api/client.js': `export const request = () => {}`,
  }, 'cannot depend on api-implementation'],
  ['Component importing an HTTP client', {
    'components/nested/Box.vue': `import axios from 'axios'`,
  }, 'HTTP client axios'],
  ['relative import escaping src', {
    'views/Page.vue': `import secret from '../../secret.js'`,
  }, '!outside-src'],
  ['unresolved internal dependency', {
    'views/Page.vue': `import thing from '@/lib/missing.js'`,
  }, '!unresolved'],
  ['Vite absolute-path API import', {
    'views/Page.vue': `import { request } from '/src/lib/api/client.js'`,
    'lib/api/client.js': `export const request = () => {}`,
  }, 'cannot depend on api-implementation'],
  ['external URL module', {
    'views/Page.vue': `import client from 'https://example.invalid/client.js'`,
  }, 'unapproved external module'],
  ['API implementation depending on a Composable', {
    'lib/api/orders.js': `import { useData } from '@/composables/useData.js'`,
    'composables/useData.js': `export const useData = () => {}`,
  }, 'cannot depend on composables'],
  ['TypeScript nested Component depending on a View', {
    'components/nested/model.ts': `export { default } from '@/views/Page.vue'`,
    'views/Page.vue': `<template><main/></template>`,
  }, 'cannot depend on views'],
  ['Vue external script depending on an API implementation', {
    'views/Page.vue': `<script src="@/lib/api/client.js"></script>`,
    'lib/api/client.js': `export const request = () => {}`,
  }, 'cannot depend on api-implementation'],
  ['application context indirectly importing a View', {
    'lib/auth.js': `export { default } from '@/views/Page.vue'`,
    'views/Page.vue': `<template><main/></template>`,
  }, 'cannot depend on views'],
  ['application context accessing transport instead of the facade', {
    'lib/auth.js': `const send = globalThis.fetch; export const login = () => send('/api/auth/login')`,
  }, 'direct HTTP transport'],
  ['support utility introducing an API dependency', {
    'lib/report-utils.js': `import { api } from './api.js'`,
    'lib/api.js': `export const api = {}`,
  }, 'cannot depend on api-facade'],
]) {
  test(`blocks ${name}`, () => {
    assert.ok(fixture(files).violations.some((violation) => violation.includes(expected)))
  })
}

test('frozen exception must refer to an existing, exact edge', () => {
  const files = {
    'views/Page.vue': `import { api } from '@/lib/api.js'`,
    'lib/api.js': `export const api = {}`,
    'lib/productionTime.js': `export const productionDate = () => '2026-10-14'`,
  }
  const edge = 'views/Page.vue -> lib/api.js'
  const baseline = fixture(files, new Map([[edge, null]])).legacyEvidence
  const edges = new Map(Object.entries(baseline))
  assert.deepEqual(fixture(files, edges).violations, [])
  assert.ok(fixture({}, edges).violations.includes(`obsolete legacy exception: ${edge}`))
  assert.ok(fixture({ ...files, 'views/Page.vue': `import { api } from '@/lib/api.js'; api.domains.orders.listOrders()` }, edges)
    .violations.includes(`legacy import or references changed: ${edge}`))
  assert.ok(fixture({ ...files,
    'views/Page.vue': `<script setup>import { api } from '@/lib/api.js'</script><template><button @click="api.domains.orders.listOrders()">Load</button></template>`,
  }, edges).violations.includes(`legacy import or references changed: ${edge}`))
})

test('the migrated inventory drawer cannot regain its direct API dependency', () => {
  const baseline = JSON.parse(readFileSync(new URL('../../scripts/frontend-layer-baseline.json', import.meta.url), 'utf8'))
  const component = 'components/inventory/ProductInventoryDrawer.vue'
  const composable = 'composables/inventory/useProductInventoryDrawer.js'
  assert.equal(Object.hasOwn(baseline, `${component} -> lib/api.js`), false)
  const files = {
    [component]: readFileSync(new URL(`../../src/${component}`, import.meta.url), 'utf8'),
    [composable]: readFileSync(new URL(`../../src/${composable}`, import.meta.url), 'utf8'),
    'lib/api.js': 'export const api = {}',
  }
  assert.deepEqual(fixture(files).violations, [])
  const restored = fixture({
    ...files,
    [component]: files[component].replace('<script setup>', `<script setup>\nimport { api } from '@/lib/api.js'`),
  })
  assert.ok(restored.violations.some(violation => violation.includes('cannot depend on api-facade')))
})

for (const [consumer, composable] of [
  ['components/schedule/ScheduleCapacityDashboard.vue', 'composables/gantt/useScheduleRevisionComparison.js'],
  ['views/GanttChart.vue', 'composables/gantt/useSchedulePriority.js'],
]) {
  test(`the migrated ${consumer} cannot regain its API or store dependency`, () => {
    const baseline = JSON.parse(readFileSync(new URL('../../scripts/frontend-layer-baseline.json', import.meta.url), 'utf8'))
    const files = {
      [consumer]: readFileSync(new URL(`../../src/${consumer}`, import.meta.url), 'utf8'),
      [composable]: readFileSync(new URL(`../../src/${composable}`, import.meta.url), 'utf8'),
      'lib/api.js': 'export const api = {}',
      'lib/store.js': 'export const showToast = () => {}',
    }
    const script = files[consumer].match(/<script[^>]*>([\s\S]*?)<\/script>/)[1]
    for (const specifier of importSpecifiers(script)) {
      if (!specifier.startsWith('@/')) continue
      const dependency = specifier.slice(2)
      if (!Object.hasOwn(files, dependency)) {
        files[dependency] = dependency.endsWith('.vue') ? '<template><div/></template>' : 'export const placeholder = () => {}'
      }
    }
    assert.deepEqual(fixture(files).violations, [])
    for (const [target, imported] of [['lib/api.js', 'api'], ['lib/store.js', 'showToast']]) {
      assert.equal(Object.hasOwn(baseline, `${consumer} -> ${target}`), false)
      const restored = fixture({
        ...files,
        [consumer]: files[consumer].replace(/<script(?: setup)?>/, `$&\nimport { ${imported} } from '@/${target}'`),
      })
      assert.ok(restored.violations.some(violation => violation.includes(`${consumer} -> ${target}`)), restored.violations.join('\n'))
    }
  })
}

test('baseline manifest rejects extension and base drift', () => {
  const baseline = JSON.parse(readFileSync(new URL('../../scripts/frontend-layer-baseline.json', import.meta.url), 'utf8'))
  assert.doesNotThrow(() => validateBaselineManifest(baseline))

  const extended = { ...baseline, 'views/NewPage.vue -> lib/api.js': '0'.repeat(64) }
  assert.doesNotThrow(() => validateBaselineManifest(extended))
  assert.deepEqual(baselineBootstrapDrift(extended), [
    'baseline manifest changed before a committed base manifest exists',
  ])
  assert.deepEqual(baselineDriftAgainstBase(extended, baseline), [
    'baseline edge is new or changed relative to base: views/NewPage.vue -> lib/api.js',
  ])

  const changed = { ...baseline, [Object.keys(baseline)[0]]: '0'.repeat(64) }
  assert.deepEqual(baselineDriftAgainstBase(changed, baseline), [
    `baseline edge is new or changed relative to base: ${Object.keys(baseline)[0]}`,
  ])
})

test('a whitelisted presentation utility loses its exception if it gains imports', () => {
  const result = fixture({
    'lib/productionTime.js': `import { api } from './api.js'; export const productionDate = () => api.domains.orders.listOrders()`,
    'lib/api.js': `export const api = {}`,
  })
  assert.ok(result.violations.some((violation) => violation.includes('presentation utility must have no imports')))
})

test('static imports, reexports and literal dynamic imports are checked', () => {
  assert.deepEqual([...importSpecifiers(`import '@/x.js'; export { x } from '../y.js'; import('@/z.js')`)],
    ['@/x.js', '../y.js', '@/z.js'])
})

for (const [name, body, expected] of [
  ['computed dynamic import', `const module = '@/lib/api.js'; import(module)`, 'nonliteral module import'],
  ['template literal API import', 'import(`@/lib/api.js`)', 'cannot depend on api-facade'],
  ['CommonJS API import', `const api = require('@/lib/api.js')`, 'cannot depend on api-facade'],
  ['computed window fetch', `window['fetch']('/api/orders')`, 'direct HTTP transport'],
  ['aliased fetch', `const send = globalThis.fetch; send('/api/orders')`, 'direct HTTP transport'],
  ['destructured fetch', `const { fetch: send } = window; send('/api/orders')`, 'direct HTTP transport'],
  ['module glob', `const modules = import.meta.glob('@/lib/api/*.js')`, 'module glob'],
]) {
  test(`blocks ${name}`, () => {
    const result = fixture({ 'views/nested/Page.vue': body, 'lib/api.js': `export const api = {}` })
    assert.ok(result.violations.some((violation) => violation.includes(expected)), result.violations.join('\n'))
  })
}

test('comments and strings containing import syntax or transport names are not code', () => {
  const result = fixture({
    'views/Page.vue': `<script setup>// import { api } from '@/lib/api.js'\nconst message = "fetch('/api/orders')"</script>`,
  })
  assert.deepEqual(result.violations, [])
})

test('legacy exceptions cannot authorize an API implementation import', () => {
  const result = fixture({
    'views/Page.vue': `import { request } from '@/lib/api/client.js'`,
    'lib/api/client.js': `export const request = () => {}`,
  }, new Map([['views/Page.vue -> lib/api/client.js', null]]))
  assert.ok(result.violations.some((violation) => violation.includes('cannot depend on api-implementation')))
})

test('formatting and comments do not change a legacy import reference digest', () => {
  const files = { 'views/Page.vue': `import { api } from '@/lib/api.js'; api.domains.orders.listOrders()`, 'lib/api.js': `export const api = {}` }
  const edge = 'views/Page.vue -> lib/api.js'
  const edges = new Map(Object.entries(fixture(files, new Map([[edge, null]])).legacyEvidence))
  assert.deepEqual(fixture({ ...files,
    'views/Page.vue': `import { api } from "@/lib/api.js"; // explanation\n\napi.domains.orders.listOrders();`,
  }, edges).violations, [])
})
