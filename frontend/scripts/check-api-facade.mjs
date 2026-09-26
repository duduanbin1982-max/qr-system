import { readdirSync, readFileSync } from 'node:fs'
import { dirname, extname, isAbsolute, join, relative, resolve, sep } from 'node:path'
import { fileURLToPath } from 'node:url'

import * as facadeExports from '../src/lib/api.js'


const sourceRoot = fileURLToPath(new URL('../src/', import.meta.url))
const apiFacadePath = resolve(sourceRoot, 'lib/api.js')
const apiImplementationRoot = resolve(sourceRoot, 'lib/api')
const { api, apiMethodCount, apiNamespaces } = facadeExports
const violations = []

function sourceFiles(directory) {
  return readdirSync(directory, { withFileTypes: true }).flatMap((entry) => {
    const path = join(directory, entry.name)
    if (entry.isDirectory()) return sourceFiles(path)
    return ['.js', '.vue'].includes(extname(entry.name)) ? [path] : []
  })
}

const sourcePaths = sourceFiles(sourceRoot).map((path) => resolve(path))
const knownSourcePaths = new Set(sourcePaths)

function importSpecifiers(content) {
  const specifiers = new Set()
  const patterns = [
    /(?:import|export)\s+(?:[^'\"]*?\s+from\s*)?['\"]([^'\"]+)['\"]/g,
    /import\s*\(\s*['\"]([^'\"]+)['\"]\s*\)/g,
  ]
  for (const pattern of patterns) {
    for (const match of content.matchAll(pattern)) specifiers.add(match[1])
  }
  return specifiers
}

function resolveInternalImport(importer, specifier) {
  let basePath
  if (specifier.startsWith('@/')) {
    basePath = resolve(sourceRoot, specifier.slice(2))
  } else if (specifier.startsWith('.')) {
    basePath = resolve(dirname(importer), specifier)
  } else {
    return null
  }

  const candidates = extname(basePath)
    ? [basePath]
    : [basePath, `${basePath}.js`, `${basePath}.vue`, join(basePath, 'index.js'), join(basePath, 'index.vue')]
  return candidates.find((candidate) => knownSourcePaths.has(resolve(candidate))) || null
}

function isWithin(directory, path) {
  const pathFromDirectory = relative(directory, path)
  return pathFromDirectory === '' || (!pathFromDirectory.startsWith(`..${sep}`) && pathFromDirectory !== '..' && !isAbsolute(pathFromDirectory))
}

for (const path of sourcePaths) {
  const resolvedPath = resolve(path)
  const content = readFileSync(path, 'utf8')
  if (resolvedPath !== apiFacadePath) {
    if (/\bapi\.domains\.http\b/.test(content)) {
      violations.push(`${relative(sourceRoot, path)}:domains.http`)
    }
    for (const match of content.matchAll(/\bapi\.domains\.([A-Za-z_$][A-Za-z0-9_$]*)\.([A-Za-z_$][A-Za-z0-9_$]*)\s*\(/g)) {
      const [, namespace, method] = match
      if (!apiNamespaces[namespace] || typeof apiNamespaces[namespace][method] !== 'function') {
        violations.push(`${relative(sourceRoot, path)}:${namespace}.${method}`)
      }
    }
    for (const match of content.matchAll(/\bapi\.(?!domains\b|js\b)([A-Za-z_$][A-Za-z0-9_$]*)/g)) {
      violations.push(`${relative(sourceRoot, path)}:${match[1]}`)
    }
  }

  const importerIsApiImplementation = isWithin(apiImplementationRoot, resolvedPath)
  if (
    resolvedPath !== apiFacadePath
    && !importerIsApiImplementation
    && (/\bfetch\s*\(/.test(content) || /\bXMLHttpRequest\b|\baxios\b/.test(content))
  ) {
    violations.push(`${relative(sourceRoot, path)}:direct network transport`)
  }

  for (const specifier of importSpecifiers(content)) {
    const dependency = resolveInternalImport(resolvedPath, specifier)
    if (
      dependency
      && isWithin(apiImplementationRoot, dependency)
      && resolvedPath !== apiFacadePath
      && !importerIsApiImplementation
    ) {
      violations.push(`${relative(sourceRoot, path)}:direct API implementation import ${specifier}`)
    }
  }
}

if (Object.keys(api).length !== 1 || api.domains !== apiNamespaces) {
  throw new Error('API facade must expose only the domain namespace root')
}
for (const transportHelper of ['request', 'uploadFile', 'buildQuery', 'handleApiError']) {
  if (transportHelper in facadeExports) {
    violations.push(`lib/api.js:low-level transport export ${transportHelper}`)
  }
}
if ('http' in apiNamespaces) {
  throw new Error('Generic HTTP namespace must remain private to domain API modules')
}
if (violations.length) {
  throw new Error(`API facade boundary violations:\n${violations.join('\n')}`)
}

process.stdout.write(
  `API facade check passed: ${Object.keys(apiNamespaces).length} namespaces, ${apiMethodCount} unique domain methods\n`,
)
