import { existsSync, readdirSync, readFileSync } from 'node:fs'
import { dirname, extname, join, relative, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'


const sourceRoot = fileURLToPath(new URL('../src/', import.meta.url))
const sourceExtensions = new Set(['.js', '.vue'])

function sourceFiles(directory) {
  return readdirSync(directory, { withFileTypes: true }).flatMap((entry) => {
    const path = join(directory, entry.name)
    if (entry.isDirectory()) return sourceFiles(path)
    return sourceExtensions.has(extname(entry.name)) ? [resolve(path)] : []
  })
}

const files = sourceFiles(sourceRoot)
const knownFiles = new Set(files)

function resolveSourceImport(importer, specifier) {
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
  return candidates.find((candidate) => knownFiles.has(candidate) && existsSync(candidate)) || null
}

function importSpecifiers(path) {
  const content = readFileSync(path, 'utf8')
  const specifiers = new Set()
  const staticImport = /(?:import|export)\s+(?:[^'\"]*?\s+from\s*)?['\"]([^'\"]+)['\"]/g
  const dynamicImport = /import\s*\(\s*['\"]([^'\"]+)['\"]\s*\)/g
  for (const pattern of [staticImport, dynamicImport]) {
    for (const match of content.matchAll(pattern)) specifiers.add(match[1])
  }
  return specifiers
}

const graph = new Map(files.map((path) => [path, new Set()]))
for (const path of files) {
  for (const specifier of importSpecifiers(path)) {
    const dependency = resolveSourceImport(path, specifier)
    if (dependency) graph.get(path).add(dependency)
  }
}

const indices = new Map()
const lowLinks = new Map()
const stack = []
const onStack = new Set()
const cycles = []

function visit(path) {
  indices.set(path, indices.size)
  lowLinks.set(path, indices.get(path))
  stack.push(path)
  onStack.add(path)

  for (const dependency of graph.get(path)) {
    if (!indices.has(dependency)) {
      visit(dependency)
      lowLinks.set(path, Math.min(lowLinks.get(path), lowLinks.get(dependency)))
    } else if (onStack.has(dependency)) {
      lowLinks.set(path, Math.min(lowLinks.get(path), indices.get(dependency)))
    }
  }

  if (lowLinks.get(path) !== indices.get(path)) return
  const component = []
  while (stack.length) {
    const dependency = stack.pop()
    onStack.delete(dependency)
    component.push(dependency)
    if (dependency === path) break
  }
  if (component.length > 1 || graph.get(path).has(path)) {
    cycles.push(component.map((item) => relative(sourceRoot, item)).sort())
  }
}

for (const path of files) {
  if (!indices.has(path)) visit(path)
}

if (cycles.length) {
  throw new Error(`Frontend import graph contains cycles:\n${cycles.map((cycle) => cycle.join(' -> ')).join('\n')}`)
}

const edgeCount = [...graph.values()].reduce((total, dependencies) => total + dependencies.size, 0)
process.stdout.write(`Frontend import cycle check passed: ${files.length} files, ${edgeCount} internal edges\n`)
