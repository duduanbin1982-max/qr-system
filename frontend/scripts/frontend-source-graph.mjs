import { readdirSync, readFileSync } from 'node:fs'
import { dirname, extname, isAbsolute, join, relative, resolve, sep } from 'node:path'
import { parse as parseJavaScript } from '@babel/parser'
import { parse as parseVue } from 'vue/compiler-sfc'

const sourceExtensions = new Set(['.js', '.mjs', '.jsx', '.ts', '.tsx', '.vue'])
const transportNames = new Set(['fetch', 'XMLHttpRequest', 'axios', 'WebSocket', 'EventSource', 'sendBeacon'])
const browserStateNames = new Set(['window', 'document', 'navigator', 'localStorage', 'sessionStorage', 'indexedDB'])

export function sourceFiles(directory) {
  return readdirSync(directory, { withFileTypes: true }).flatMap((entry) => {
    const path = join(directory, entry.name)
    if (entry.isDirectory()) return sourceFiles(path)
    return sourceExtensions.has(extname(path)) ? [resolve(path)] : []
  })
}

export function isWithin(root, path) {
  const rest = relative(root, path)
  return rest === '' || (rest !== '..' && !rest.startsWith(`..${sep}`) && !isAbsolute(rest))
}

export function resolveSourceImport(root, importer, specifier, knownFiles) {
  const base = specifier.startsWith('@/')
    ? resolve(root, specifier.slice(2))
    : specifier.startsWith('/src/') ? resolve(root, specifier.slice(5))
      : specifier.startsWith('.') ? resolve(dirname(importer), specifier) : null
  if (!base) return null
  if (!isWithin(root, base)) return { error: 'outside-src' }
  const candidates = extname(base) ? [base] : [
    base, ...[...sourceExtensions].map((ext) => `${base}${ext}`),
    ...[...sourceExtensions].map((ext) => join(base, `index${ext}`)),
  ]
  const path = candidates.find((candidate) => knownFiles.has(candidate))
  return path ? { path } : { error: 'unresolved' }
}

function literalString(node) {
  if (node?.type === 'StringLiteral') return node.value
  if (node?.type === 'TemplateLiteral' && node.expressions.length === 0) return node.quasis[0].value.cooked
  if (node?.type === 'BinaryExpression' && node.operator === '+') {
    const left = literalString(node.left)
    const right = literalString(node.right)
    if (left !== null && right !== null) return left + right
  }
  return null
}

function normalizeNode(node) {
  if (Array.isArray(node)) return node.map(normalizeNode)
  if (!node || typeof node !== 'object') return node
  return Object.fromEntries(Object.entries(node)
    .filter(([key]) => !['start', 'end', 'loc', 'extra', 'leadingComments', 'trailingComments', 'innerComments'].includes(key))
    .map(([key, value]) => [key, normalizeNode(value)]))
}

function walk(node, visit, parent = null, ancestors = []) {
  if (!node || typeof node !== 'object') return
  if (Array.isArray(node)) {
    for (const item of node) walk(item, visit, parent, ancestors)
    return
  }
  if (node.type) visit(node, parent, ancestors)
  for (const [key, value] of Object.entries(node)) {
    if (!['loc', 'comments', 'tokens'].includes(key)) walk(value, visit, node, [...ancestors, node])
  }
}

function namedMember(node) {
  return node.computed ? literalString(node.property) : node.property?.name
}

export function analyzeSource(content, filename = 'fixture.js') {
  const imports = []
  const issues = []
  const transports = []
  const browserState = []
  const templatePrograms = []
  let scripts = [{ content, lang: extname(filename).slice(1), lineOffset: 0 }]
  if (extname(filename) === '.vue') {
    const { descriptor, errors } = parseVue(content, { filename })
    if (errors.length) throw new Error(`${filename}: ${errors.map(String).join('; ')}`)
    scripts = [descriptor.script, descriptor.scriptSetup].filter(Boolean).map((script) => {
      if (script.src) imports.push({ specifier: script.src, kind: 'script-src', line: script.loc.start.line })
      return { content: script.content, lang: script.lang || 'js', lineOffset: script.loc.start.line - 1 }
    })
    walk(descriptor.template?.ast, (node) => {
      if (node.type !== 4 || node.isStatic) return
      if (node.ast) templatePrograms.push({ ast: node.ast, lineOffset: (node.loc?.start.line || 1) - 1 })
      else if (/^[A-Za-z_$][\w$]*$/.test(node.content)) {
        templatePrograms.push({ ast: parseJavaScript(node.content), lineOffset: (node.loc?.start.line || 1) - 1 })
      }
    })
  }
  const parsedScripts = scripts.map((script) => ({
    ast: parseJavaScript(script.content, {
      sourceType: 'unambiguous', createImportExpressions: true,
      plugins: [
        ...(['ts', 'tsx'].includes(script.lang) ? ['typescript'] : []),
        ...(['jsx', 'tsx'].includes(script.lang) ? ['jsx'] : []),
      ],
    }).program,
    lineOffset: script.lineOffset,
  }))
  for (const script of [...parsedScripts, ...templatePrograms]) {
    walk(script.ast, (node, parent) => {
      const line = (node.loc?.start.line || 1) + script.lineOffset
      if (['ImportDeclaration', 'ExportNamedDeclaration', 'ExportAllDeclaration'].includes(node.type) && node.source) {
        const bindings = (node.specifiers || []).map((item) => item.local?.name).filter(Boolean)
        const references = []
        walk([...parsedScripts, ...templatePrograms].map((part) => part.ast), (candidate, owner, ancestors) => {
          if (candidate.type !== 'Identifier' || !bindings.includes(candidate.name)) return
          if (owner?.type?.startsWith('Import')) return
          if (['MemberExpression', 'OptionalMemberExpression', 'ObjectProperty'].includes(owner?.type)
            && (owner.property === candidate || owner.key === candidate) && !owner.computed && !owner.shorthand) return
          let expression = candidate
          for (const ancestor of [...ancestors].reverse()) {
            if (!['MemberExpression', 'OptionalMemberExpression'].includes(ancestor.type) || ancestor.object !== expression) break
            expression = ancestor
          }
          references.push(JSON.stringify(normalizeNode(expression)))
        })
        imports.push({ specifier: node.source.value, kind: node.type, line,
          evidence: { declaration: normalizeNode(node), references: references.sort() } })
      }
      if (node.type === 'ImportExpression' || (node.type === 'CallExpression' && ['require', 'Import'].includes(node.callee?.name || node.callee?.type))) {
        const argument = node.type === 'ImportExpression' ? node.source : node.arguments[0]
        const specifier = literalString(argument)
        if (specifier !== null) imports.push({ specifier, kind: node.type, line, evidence: normalizeNode(node) })
        else issues.push(`line ${line}: nonliteral module import cannot be checked`)
      }
      if (node.type === 'CallExpression' && ['MemberExpression', 'OptionalMemberExpression'].includes(node.callee?.type)) {
        if (['glob', 'globEager'].includes(namedMember(node.callee))) {
          issues.push(`line ${line}: module glob must be replaced with explicit imports`)
        }
      }
      if (node.type === 'Identifier') {
        const nonReferenceProperty = ['MemberExpression', 'OptionalMemberExpression', 'ObjectProperty', 'ObjectMethod'].includes(parent?.type)
          && (parent.property === node || parent.key === node) && !parent.computed && !parent.shorthand
        if (!nonReferenceProperty && transportNames.has(node.name)) transports.push(`line ${line}: ${node.name}`)
        if (!nonReferenceProperty && browserStateNames.has(node.name)) browserState.push(`line ${line}: ${node.name}`)
      }
      if (['MemberExpression', 'OptionalMemberExpression'].includes(node.type) && transportNames.has(namedMember(node))) {
        transports.push(`line ${line}: ${namedMember(node)}`)
      }
      if (['MemberExpression', 'OptionalMemberExpression'].includes(node.type) && browserStateNames.has(namedMember(node))) {
        browserState.push(`line ${line}: ${namedMember(node)}`)
      }
      if (node.type === 'ObjectProperty' && parent?.type === 'ObjectPattern') {
        const name = node.computed ? literalString(node.key) : node.key?.name
        if (transportNames.has(name)) transports.push(`line ${line}: ${name}`)
      }
    })
  }
  return { imports, issues, transports, browserState }
}

export function readSource(path) {
  return analyzeSource(readFileSync(path, 'utf8'), path)
}
