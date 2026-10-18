import assert from 'node:assert/strict'
import { spawnSync } from 'node:child_process'
import { mkdtempSync, mkdirSync, readFileSync, rmSync, writeFileSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { dirname, join } from 'node:path'
import { fileURLToPath } from 'node:url'
import { test } from 'node:test'

import { assertToolchain, readToolchain } from '../../scripts/check-toolchain.mjs'

const root = fileURLToPath(new URL('../../../', import.meta.url))
const expected = readToolchain(root)

function fixture(run) {
  const directory = mkdtempSync(join(tmpdir(), 'qr-toolchain-'))
  for (const name of ['package.json', 'package-lock.json', '.nvmrc', '.node-version', '.npmrc']) {
    writeFileSync(join(directory, name), readFileSync(join(root, name)))
  }
  try {
    return run(directory)
  } finally {
    rmSync(directory, { recursive: true, force: true })
  }
}

function editJson(directory, name, edit) {
  const path = join(directory, name)
  const data = JSON.parse(readFileSync(path, 'utf8'))
  edit(data)
  writeFileSync(path, JSON.stringify(data))
}

function npmCi(cwd) {
  const args = ['ci', '--ignore-scripts', '--offline', '--no-audit', '--no-fund']
  return process.env.npm_execpath
    ? spawnSync(process.execPath, [process.env.npm_execpath, ...args], { cwd, encoding: 'utf8', timeout: 30_000 })
    : process.platform === 'win32'
      ? spawnSync('npm.cmd ci --ignore-scripts --offline --no-audit --no-fund', {
        cwd, encoding: 'utf8', shell: true, timeout: 30_000,
      })
      : spawnSync('npm', args, { cwd, encoding: 'utf8', timeout: 30_000 })
}

test('the checked-in configuration agrees and returns an immutable pin', () => {
  assert.ok(Object.isFrozen(expected))
  assert.doesNotThrow(() => assertToolchain(expected, expected))
})

for (const [description, actual] of [
  ['older Node', { ...expected, node: '20.20.2' }],
  ['different Node patch', { ...expected, node: '24.0.0' }],
  ['unapproved Node major', { ...expected, node: '25.2.1' }],
  ['older npm', { ...expected, npm: '10.8.2' }],
  ['different npm patch', { ...expected, npm: '11.6.2' }],
]) {
  test(`rejects ${description} before a build can start`, () => {
    assert.throws(() => assertToolchain(expected, actual), /Toolchain mismatch/)
  })
}

for (const name of ['.nvmrc', '.node-version']) {
  test(`rejects drift in ${name}`, () => fixture((directory) => {
    writeFileSync(join(directory, name), '20.20.2\n')
    assert.throws(() => readToolchain(directory), /must match engines.node/)
  }))
}

for (const [description, edit, message] of [
  ['a loose Node engine range', (data) => { data.engines.node = '>=20' }, /pin exact versions/],
  ['a loose npm engine range', (data) => { data.engines.npm = '^11' }, /pin exact versions/],
  ['a stale packageManager', (data) => { data.packageManager = 'npm@10.8.2' }, /packageManager must match/],
  ['missing devEngines', (data) => { delete data.devEngines }, /devEngines.runtime/],
  ['warning-only Node enforcement', (data) => { data.devEngines.runtime.onFail = 'warn' }, /devEngines.runtime/],
  ['a stale npm devEngine', (data) => { data.devEngines.packageManager.version = '10.8.2' }, /devEngines.packageManager/],
]) {
  test(`rejects ${description}`, () => fixture((directory) => {
    editJson(directory, 'package.json', edit)
    assert.throws(() => readToolchain(directory), message)
  }))
}

for (const key of ['node', 'npm']) {
  test(`rejects a stale lockfile ${key} engine`, () => fixture((directory) => {
    editJson(directory, 'package-lock.json', (data) => { data.packages[''].engines[key] = '0.0.0' })
    assert.throws(() => readToolchain(directory), /root engines must match/)
  }))
}

test('rejects disabling strict install checks', () => fixture((directory) => {
  writeFileSync(join(directory, '.npmrc'), 'engine-strict=false\n')
  assert.throws(() => readToolchain(directory), /engine-strict=true/)
}))

test('rejects duplicate strict settings that npm could resolve differently', () => fixture((directory) => {
  writeFileSync(join(directory, '.npmrc'), 'engine-strict=true\nengine-strict=false\n')
  assert.throws(() => readToolchain(directory), /engine-strict=true/)
}))

test('the CLI checks a clean checkout without installed project dependencies', () => fixture((directory) => {
  const cli = join(directory, 'frontend/scripts/check-toolchain.mjs')
  mkdirSync(dirname(cli), { recursive: true })
  writeFileSync(cli, readFileSync(join(root, 'frontend/scripts/check-toolchain.mjs')))
  const result = spawnSync(process.execPath, [cli], { cwd: directory, encoding: 'utf8', timeout: 30_000 })
  assert.equal(result.status, 0, result.stderr)
  assert.match(result.stdout, /Toolchain check passed/)
  editJson(directory, 'package.json', (data) => { data.packageManager = 'npm@0.0.0' })
  const drift = spawnSync(process.execPath, [cli], { cwd: directory, encoding: 'utf8', timeout: 30_000 })
  assert.equal(drift.status, 1)
  assert.match(drift.stderr, /packageManager must match/)
}))

for (const key of ['node', 'npm']) {
  test(`npm ci --ignore-scripts rejects the wrong ${key} before deleting node_modules`, () => fixture((directory) => {
    // No project dependencies or registry access: exercise npm's install gate,
    // including the deployment install mode that skips lifecycle scripts.
    const manifest = JSON.parse(readFileSync(join(directory, 'package.json'), 'utf8'))
    delete manifest.dependencies
    delete manifest.devDependencies
    delete manifest.overrides
    manifest.engines[key] = '0.0.0'
    const devKey = key === 'node' ? 'runtime' : 'packageManager'
    manifest.devEngines[devKey].version = '0.0.0'
    writeFileSync(join(directory, 'package.json'), JSON.stringify(manifest))
    writeFileSync(join(directory, 'package-lock.json'), JSON.stringify({
      name: manifest.name, version: manifest.version, lockfileVersion: 3,
      packages: { '': { name: manifest.name, version: manifest.version, engines: manifest.engines } },
    }))
    mkdirSync(join(directory, 'node_modules'))
    const sentinel = join(directory, 'node_modules/before-install')
    writeFileSync(sentinel, 'unchanged')
    const result = npmCi(directory)
    assert.notEqual(result.status, null, result.error?.message)
    assert.notEqual(result.status, 0)
    assert.match(result.stderr, /EBAD(?:DEV)?ENGINES?/)
    assert.equal(readFileSync(sentinel, 'utf8'), 'unchanged')
  }))
}
