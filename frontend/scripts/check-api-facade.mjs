import { readdirSync, readFileSync } from 'node:fs'
import { extname, join, relative } from 'node:path'
import { fileURLToPath } from 'node:url'

import { api, apiMethodCount, apiNamespaces } from '../src/lib/api.js'


const sourceRoot = fileURLToPath(new URL('../src/', import.meta.url))
const violations = []

function sourceFiles(directory) {
  return readdirSync(directory, { withFileTypes: true }).flatMap((entry) => {
    const path = join(directory, entry.name)
    if (entry.isDirectory()) return sourceFiles(path)
    return ['.js', '.vue'].includes(extname(entry.name)) ? [path] : []
  })
}

for (const path of sourceFiles(sourceRoot)) {
  if (path === fileURLToPath(new URL('../src/lib/api.js', import.meta.url))) continue
  const content = readFileSync(path, 'utf8')
  for (const match of content.matchAll(/\bapi\.(?!domains\b|js\b)([A-Za-z_$][A-Za-z0-9_$]*)/g)) {
    violations.push(`${relative(sourceRoot, path)}:${match[1]}`)
  }
}

if (Object.keys(api).length !== 1 || api.domains !== apiNamespaces) {
  throw new Error('API facade must expose only the domain namespace root')
}
if (violations.length) {
  throw new Error(`Flat API calls are forbidden:\n${violations.join('\n')}`)
}

process.stdout.write(
  `API facade check passed: ${Object.keys(apiNamespaces).length} namespaces, ${apiMethodCount} unique domain methods\n`,
)
