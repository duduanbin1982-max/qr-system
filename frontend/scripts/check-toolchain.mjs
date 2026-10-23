// Keep this entry dependency-free so it also runs before npm ci.
import { spawnSync } from 'node:child_process'
import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'
import { fileURLToPath, pathToFileURL } from 'node:url'

const projectRoot = fileURLToPath(new URL('../../', import.meta.url))

export function readToolchain(root = projectRoot) {
  const readJson = (name) => JSON.parse(readFileSync(resolve(root, name), 'utf8'))
  const manifest = readJson('package.json')
  const lockfile = readJson('package-lock.json')
  const node = manifest.engines?.node
  const npm = manifest.engines?.npm
  if (![node, npm].every((value) => /^\d+\.\d+\.\d+$/.test(value ?? ''))) {
    throw new Error('engines.node and engines.npm must pin exact versions')
  }
  for (const name of ['.nvmrc', '.node-version']) {
    if (readFileSync(resolve(root, name), 'utf8').trim() !== node) {
      throw new Error(`${name} must match engines.node (${node})`)
    }
  }
  if (manifest.packageManager !== `npm@${npm}`) {
    throw new Error('packageManager must match engines.npm')
  }
  for (const [key, name, version] of [
    ['runtime', 'node', node], ['packageManager', 'npm', npm],
  ]) {
    const engine = manifest.devEngines?.[key]
    if (engine?.name !== name || engine.version !== version || engine.onFail !== 'error') {
      throw new Error(`devEngines.${key} must enforce ${name}@${version}`)
    }
  }
  if (lockfile.lockfileVersion !== 3
    || lockfile.packages?.['']?.engines?.node !== node
    || lockfile.packages?.['']?.engines?.npm !== npm) {
    throw new Error('package-lock.json root engines must match package.json')
  }
  const strictSettings = readFileSync(resolve(root, '.npmrc'), 'utf8').split(/\r?\n/)
    .map((line) => line.trim()).filter((line) => /^engine-strict\s*=/.test(line))
  if (strictSettings.length !== 1 || !/^engine-strict\s*=\s*true$/.test(strictSettings[0])) {
    throw new Error('.npmrc must enable engine-strict=true')
  }
  return Object.freeze({ node, npm })
}

export function assertToolchain(expected, actual) {
  if (actual.node !== expected.node || actual.npm !== expected.npm) {
    throw new Error(
      `Toolchain mismatch: required Node ${expected.node} / npm ${expected.npm}; `
      + `received Node ${actual.node} / npm ${actual.npm}. `
      + 'Select the pinned Node distribution before installing, testing or building.',
    )
  }
}

function npmVersion() {
  // npm_execpath identifies the npm that invoked this script; user-agent text
  // alone is not a version check. Standalone shell entry points use PATH.
  const fromNpm = process.env.npm_execpath
  const options = { encoding: 'utf8', timeout: 10_000 }
  const result = fromNpm
    ? spawnSync(process.execPath, [fromNpm, '--version'], options)
    : process.platform === 'win32'
      ? spawnSync('npm.cmd --version', { ...options, shell: true })
      : spawnSync('npm', ['--version'], options)
  if (result.error || result.status !== 0) {
    throw new Error('Cannot determine the active npm version; select the pinned Node/npm distribution')
  }
  return result.stdout.trim()
}

export function checkToolchain() {
  const expected = readToolchain()
  assertToolchain(expected, { node: process.versions.node, npm: npmVersion() })
  return expected
}

if (process.argv[1] && import.meta.url === pathToFileURL(resolve(process.argv[1])).href) {
  try {
    const { node, npm } = checkToolchain()
    console.log(`Toolchain check passed: Node ${node}, npm ${npm}`)
  } catch (error) {
    console.error(error.message)
    process.exitCode = 1
  }
}
