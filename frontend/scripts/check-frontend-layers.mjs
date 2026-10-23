import { createHash } from 'node:crypto'
import { execFileSync } from 'node:child_process'
import { readFileSync } from 'node:fs'
import { relative, resolve, sep } from 'node:path'
import { fileURLToPath } from 'node:url'
import { analyzeSource, readSource, resolveSourceImport, sourceFiles } from './frontend-source-graph.mjs'

const defaultSourceRoot = fileURLToPath(new URL('../src/', import.meta.url))

// Adding a lib module here requires reviewing that it has no IO, state or API calls.
export const PURE_PRESENTATION_MODULES = Object.freeze([
  'lib/productionTime.js',
])

// The older UI imports app context and API calls directly. These exact edges are
// frozen; new callers must move query/state coordination to a composable.
const baselinePath = fileURLToPath(new URL('./frontend-layer-baseline.json', import.meta.url))
const BASELINE_REPOSITORY_PATH = 'frontend/scripts/frontend-layer-baseline.json'
export const BASELINE_MANIFEST_DIGEST = '46bf396e2d964aa537fdb15db3d6a2fe4395767efd2897269f1ab9f99f7e03d9'

export function canonicalBaselineDigest(value) {
  const canonical = JSON.stringify(Object.fromEntries(Object.entries(value).sort(([left], [right]) => left < right ? -1 : left > right ? 1 : 0)))
  return createHash('sha256').update(canonical).digest('hex')
}

export function validateBaselineManifest(value) {
  if (!value || Array.isArray(value) || typeof value !== 'object'
    || Object.values(value).some((digest) => !/^[a-f0-9]{64}$/.test(digest))) {
    throw new Error('Frontend layer baseline must contain exact edges with SHA-256 reference digests')
  }
  return value
}

const baseline = validateBaselineManifest(JSON.parse(readFileSync(baselinePath, 'utf8')))

function gitBaseline(ref) {
  try {
    const content = execFileSync('git', ['show', `${ref}:${BASELINE_REPOSITORY_PATH}`], {
      cwd: fileURLToPath(new URL('../..', import.meta.url)),
      encoding: 'utf8',
      stdio: ['ignore', 'pipe', 'ignore'],
    })
    return JSON.parse(content)
  } catch {
    return null
  }
}

export function baselineDriftAgainstBase(current, base) {
  if (!base) return []
  return Object.entries(current)
    .filter(([edge, digest]) => !(edge in base) || base[edge] !== digest)
    .map(([edge]) => `baseline edge is new or changed relative to base: ${edge}`)
}

export function baselineBootstrapDrift(current) {
  return canonicalBaselineDigest(current) === BASELINE_MANIFEST_DIGEST
    ? []
    : ['baseline manifest changed before a committed base manifest exists']
}

function loadBaseBaseline() {
  const configured = process.env.FRONTEND_LAYER_BASE_REF
  const candidates = [
    configured,
    process.env.GITHUB_BASE_REF && `origin/${process.env.GITHUB_BASE_REF}`,
    process.env.GITHUB_BASE_REF && `github/${process.env.GITHUB_BASE_REF}`,
    'github/master',
    'origin/master',
    'master',
  ].filter(Boolean)
  for (const ref of candidates) {
    const value = gitBaseline(ref)
    if (value) return { ref, value }
  }
  return null
}

const LEGACY_EDGES = new Map(Object.entries(baseline))
const legacyTargets = new Set(['lib/api.js', 'lib/auth.js', 'lib/store.js', 'lib/router.js', 'lib/permissions.js', 'lib/report-utils.js'])
const allowedPackages = new Set(['vue', 'chart.js', 'html2canvas'])
const applicationContextModules = new Set([
  'lib/auth.js', 'lib/store.js', 'lib/router.js', 'lib/permissions.js',
  'lib/permissionCatalog.js', 'lib/permissionFallback.generated.js',
])
const allowedDependencyLayers = {
  views: new Set(['views', 'components', 'composables']),
  components: new Set(['components', 'composables']),
  composables: new Set(['composables', 'api-facade', 'application-context']),
  'application-context': new Set(['application-context', 'api-facade']),
  support: new Set(['support']),
  'api-implementation': new Set(['api-implementation']),
  'api-facade': new Set(['api-implementation']),
}

export function importSpecifiers(content) {
  return new Set(analyzeSource(content).imports.map((item) => item.specifier))
}

function layer(path) {
  if (path.startsWith('views/')) return 'views'
  if (path.startsWith('components/')) return 'components'
  if (path.startsWith('composables/')) return 'composables'
  if (path.startsWith('lib/api/')) return 'api-implementation'
  if (path === 'lib/api.js') return 'api-facade'
  if (applicationContextModules.has(path)) return 'application-context'
  if (path.startsWith('lib/')) return 'support'
  return 'other'
}

export function checkFrontendLayers(sourceRoot = defaultSourceRoot, { legacyEdges = LEGACY_EDGES } = {}) {
  const root = resolve(sourceRoot)
  const paths = sourceFiles(root)
  const knownFiles = new Set(paths)
  const violations = []
  const seenLegacy = new Set()
  const legacyEvidence = {}
  const sources = new Map()
  let edgeCount = 0

  for (const name of PURE_PRESENTATION_MODULES) {
    const path = resolve(root, name)
    if (!knownFiles.has(path)) {
      violations.push(`missing pure presentation module: ${name}`)
      continue
    }
    const source = readSource(path)
    sources.set(path, source)
    if (source.imports.length || source.issues.length || source.transports.length || source.browserState.length) {
      violations.push(`${name}: presentation utility must have no imports, browser state or HTTP transport`)
    }
  }

  for (const importer of paths) {
    const from = relative(root, importer).split(sep).join('/')
    const fromLayer = layer(from)
    if (!allowedDependencyLayers[fromLayer]) continue
    let source
    try {
      source = sources.get(importer) || readSource(importer)
    } catch (error) {
      violations.push(`${from}: parse error ${error.message}`)
      continue
    }
    violations.push(...source.issues.map((issue) => `${from}: ${issue}`))
    if (from !== 'lib/api/client.js' && source.transports.length) {
      violations.push(`${from}: direct HTTP transport ${source.transports.join(', ')}`)
    }
    const legacyImports = new Map()
    for (const record of source.imports) {
      const { specifier } = record
      if (from !== 'lib/api/client.js' && /^(?:axios|ofetch|node-fetch)(?:\/|$)/.test(specifier)) {
        violations.push(`${from}: HTTP client ${specifier}`)
      }
      const target = resolveSourceImport(root, importer, specifier, knownFiles)
      if (!target) {
        if (!allowedPackages.has(specifier)) violations.push(`${from}: unapproved external module ${specifier}`)
        continue
      }
      if (target.error) {
        // CSS and assets are handled by Vite, and do not participate in the JS layer graph.
        if (!/\.(?:css|svg|png|jpe?g|webp)$/.test(specifier)) violations.push(`${from}: !${target.error} ${specifier}`)
        continue
      }
      edgeCount++
      const to = relative(root, target.path).split(sep).join('/')
      const toLayer = layer(to)
      const edge = `${from} -> ${to}`
      const isPresentationConsumer = !['api-implementation', 'api-facade'].includes(fromLayer)
      const allowed = allowedDependencyLayers[fromLayer].has(toLayer)
        || (isPresentationConsumer && PURE_PRESENTATION_MODULES.includes(to))
        || (fromLayer === 'support' && to === 'lib/store.js')
      if (allowed) continue
      if (['views', 'components'].includes(fromLayer) && legacyTargets.has(to) && legacyEdges.has(edge)) {
        seenLegacy.add(edge)
        if (!legacyImports.has(edge)) legacyImports.set(edge, [])
        legacyImports.get(edge).push(JSON.stringify(record.evidence || record.kind))
        continue
      }
      violations.push(`${edge}: ${fromLayer} cannot depend on ${toLayer}`)
    }
    for (const [edge, evidence] of legacyImports) {
      const digest = createHash('sha256').update(JSON.stringify(evidence.sort())).digest('hex')
      legacyEvidence[edge] = digest
      if (legacyEdges.get(edge) && legacyEdges.get(edge) !== digest) {
        violations.push(`legacy import or references changed: ${edge}`)
      }
    }
  }
  for (const edge of legacyEdges.keys()) {
    if (!seenLegacy.has(edge)) violations.push(`obsolete legacy exception: ${edge}`)
  }
  return { violations, edgeCount, fileCount: paths.length, legacyCount: seenLegacy.size, legacyEvidence }
}

if (process.argv[1] && resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  const baselineBase = loadBaseBaseline()
  const baselineViolations = baselineBase
    ? baselineDriftAgainstBase(baseline, baselineBase.value)
    : baselineBootstrapDrift(baseline)
  const { violations, edgeCount, fileCount, legacyCount } = checkFrontendLayers()
  if (baselineViolations.length) {
    const baselineReference = baselineBase?.ref || 'bootstrap manifest digest'
    process.stderr.write(`Frontend layer baseline violations against ${baselineReference}:\n${baselineViolations.join('\n')}\n`)
    process.exitCode = 1
  }
  if (violations.length) {
    process.stderr.write(`Frontend layer violations:\n${violations.join('\n')}\n`)
    process.exitCode = 1
  }
  if (!baselineViolations.length && !violations.length) {
    process.stdout.write(`Frontend layer check passed: ${fileCount} files, ${edgeCount} edges, ${legacyCount} frozen legacy edges\n`)
  }
}
