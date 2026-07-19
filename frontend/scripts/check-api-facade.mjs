import { api, apiNamespaces } from '../src/lib/api.js'

const namespaceNames = new Set(Object.keys(apiNamespaces))
const flatMethodCount = Object.keys(api).filter((key) => key !== 'domains').length

if (flatMethodCount === 0) {
  throw new Error('API compatibility facade has no flat methods')
}
if (api.domains !== apiNamespaces) {
  throw new Error('API domain namespace root is not exposed by the facade')
}

process.stdout.write(
  `API facade check passed: ${namespaceNames.size} namespaces, ${flatMethodCount} compatibility methods\n`,
)
