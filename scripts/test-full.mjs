import { mkdirSync, writeFileSync } from 'node:fs'
import { dirname, resolve } from 'node:path'
import { spawnSync } from 'node:child_process'

const projectRoot = resolve(import.meta.dirname, '..')
const timestamp = new Date().toISOString().replace(/[:.]/g, '-')
const artifactDir = resolve(
  process.env.FULL_TEST_ARTIFACT_DIR || resolve(projectRoot, 'test-results', `full-${timestamp}`),
)
mkdirSync(artifactDir, { recursive: true })

const npmCommand = 'npm'
const pythonCommand = process.env.PYTHON || (process.platform === 'win32' ? 'python' : 'python3')
const steps = [
  {
    name: 'backend',
    command: pythonCommand,
    args: ['-m', 'pytest', '-q'],
  },
  {
    name: 'frontend-unit',
    command: npmCommand,
    args: ['run', 'test:unit'],
  },
  {
    name: 'architecture',
    command: npmCommand,
    args: ['run', 'check:architecture'],
  },
  {
    name: 'frontend-build',
    command: npmCommand,
    args: ['run', 'build'],
  },
  {
    name: 'e2e',
    command: npmCommand,
    args: ['run', 'test:e2e'],
  },
]
const startStep = process.env.FULL_TEST_FROM || steps[0].name
const startIndex = steps.findIndex((step) => step.name === startStep)
if (startIndex < 0) {
  console.error(`Unknown FULL_TEST_FROM step: ${startStep}`)
  process.exit(2)
}
const selectedSteps = steps.slice(startIndex)

const summary = {
  started_at: new Date().toISOString(),
  artifact_dir: artifactDir,
  start_step: startStep,
  planned_steps: selectedSteps.map((step) => step.name),
  steps: [],
}

for (const step of selectedSteps) {
  const started = Date.now()
  const command = process.platform === 'win32' && step.command === npmCommand
    ? process.env.ComSpec || 'cmd.exe'
    : step.command
  const args = process.platform === 'win32' && step.command === npmCommand
    ? ['/d', '/s', '/c', [npmCommand, ...step.args].join(' ')]
    : step.args
  const result = spawnSync(command, args, {
    cwd: projectRoot,
    env: process.env,
    encoding: 'utf8',
  })
  const durationMs = Date.now() - started
  const output = `${result.stdout || ''}${result.stderr || ''}`
  const logPath = resolve(artifactDir, `${step.name}.log`)
  writeFileSync(logPath, output, 'utf8')

  const status = result.error || result.status !== 0 ? 'failed' : 'passed'
  summary.steps.push({
    name: step.name,
    command: [step.command, ...step.args].join(' '),
    status,
    exit_code: result.error ? null : result.status,
    duration_ms: durationMs,
    log: logPath,
  })

  console.log(`[${status}] ${step.name} (${(durationMs / 1000).toFixed(1)}s)`)
  if (status === 'failed') {
    if (result.error) console.error(result.error)
    console.error(`See ${logPath}`)
    break
  }
}

summary.finished_at = new Date().toISOString()
summary.status = summary.steps.every((step) => step.status === 'passed')
  && summary.steps.length === selectedSteps.length
  ? 'passed'
  : 'failed'
const summaryPath = resolve(artifactDir, 'summary.json')
writeFileSync(summaryPath, `${JSON.stringify(summary, null, 2)}\n`, 'utf8')
console.log(`Summary: ${summaryPath}`)

if (summary.status !== 'passed') process.exit(1)
