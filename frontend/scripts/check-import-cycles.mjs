import { relative } from 'node:path'
import { fileURLToPath } from 'node:url'
import { readSource, resolveSourceImport, sourceFiles } from './frontend-source-graph.mjs'


const sourceRoot = fileURLToPath(new URL('../src/', import.meta.url))

const files = sourceFiles(sourceRoot)
const knownFiles = new Set(files)

const graph = new Map(files.map((path) => [path, new Set()]))
for (const path of files) {
  const source = readSource(path)
  if (source.issues.length) throw new Error(`${path}: ${source.issues.join('; ')}`)
  for (const { specifier } of source.imports) {
    const dependency = resolveSourceImport(sourceRoot, path, specifier, knownFiles)
    if (dependency?.path) graph.get(path).add(dependency.path)
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
