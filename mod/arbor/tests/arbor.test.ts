import { expect, mock, test } from 'claude-code/testing'
import type { Engine } from 'claude-code/testing'
import type { On } from 'claude-code'

// The world beneath the mod: a project at /proj with arbor.py, a 100 KB file, an active task.
const ROOT = '/proj'
const NOW = '# Now\n\n## TASK-20261004-001 Mod for Claude Code\n\n- Status: active\n- Goal: points 1-6\n\n## TASK-20261001-001 Old\n\n- Status: done\n'
const CLAUDE_MD = '# Project\n\n# Context Arbor: memory and sessions\n\nlong text\nOpen the vault with `python arbor.py memory open`. Context Arbor invokes no model.\n\n# Other rules\n'

function world(on: On, runs: string[][], root = ROOT) {
  mock.clock(on)
  on('session.start', async (_$, e) => ({ cwd: e.cwd }))
  on('session.root', async () => ({ value: root }))
  on('session.id', async () => ({ value: 'sess-1' }))
  // the engine hands paths over absolute, in the platform's form (C:\proj\arbor.py on Windows)
  on('fs.exists', async (_$, e) => ({ value: e.path.split(/[/\\]/).slice(-2).join('/') === 'proj/arbor.py' }))
  on('fs.read', async (_$, e) => ({ value: e.path.endsWith('NOW.md') ? NOW : '' }))
  on('fs.stat', async () => ({ value: { kind: 'file' as const, size: 100_000, mtimeMs: 0, isLink: false } }))
  on('settings.read', async () => ({ value: { hooks: {} } }))
  on('tool.register', async (_$, e) => ({ value: { tool: e.name } }))
  on('process.run', async (_$, e) => {
    runs.push([...e.argv])
    const out = e.argv.includes('outline') ? 'big.py\n  def huge  1-900\n' : e.argv.includes('find') ? 'arbor.py:10 cmd_x' : ''
    return { value: { exitCode: 0, stdout: out, stderr: '', isStdoutTruncated: false, isStderrTruncated: false } }
  })
}

async function started($: Engine) {
  await $.session.start({ cwd: ROOT, surface: null, isInteractive: true })
}

test('a whole read of a large file answers with the outline once, then goes through', async ($, on) => {
  const runs: string[][] = []
  world(on, runs)
  on('tool.call', { tool: 'Read' }, async () => ({ result: 'whole file' }) as never)
  await started($)
  const first = await $.tool.call({ tool: 'Read', file_path: `${ROOT}/big.py` } as never)
  expect(first.deny).toContain('big.py is 98 KB')
  expect(first.deny).toContain('def huge')
  expect(runs).toContainEqual(['python', 'arbor.py', 'code', 'outline', 'big.py', '--limit', '40'])
  const second = await $.tool.call({ tool: 'Read', file_path: `${ROOT}/big.py` } as never)
  expect(second.result).toBe('whole file')
  const part = await $.tool.call({ tool: 'Read', file_path: `${ROOT}/other.py`, offset: 1, limit: 50 } as never)
  expect(part.result).toBe('whole file')
})

test('the arbor tools run arbor.py with their argv', async ($, on) => {
  const runs: string[][] = []
  world(on, runs)
  await started($)
  const r = await $.tool.call({ tool: 'mcp__arbor__code_find', query: 'compaction', top: 3 } as never)
  expect(r.result).toBe('arbor.py:10 cmd_x')
  expect(runs).toContainEqual(['python', 'arbor.py', 'code', 'find', 'compaction', '--top', '3'])
})

test('the start context gets the lean block and the active task only', async ($, on) => {
  world(on, [])
  on('prompt.context', async (_$, e) => ({ blocks: e.blocks, instructionFiles: e.instructionFiles }))
  await started($)
  const r = await $.prompt.context({ blocks: [], instructionFiles: [{ path: `${ROOT}/CLAUDE.md`, kind: 'project', content: CLAUDE_MD }] })
  const content = r.instructionFiles?.[0]?.content ?? ''
  expect(content).toContain('(arbor mod)')
  expect(content).toContain('# Other rules')
  expect(content).not.toContain('long text')
  const task = r.blocks.find(b => b.name === 'arbor')?.text ?? ''
  expect(task).toContain('TASK-20261004-001')
  expect(task).not.toContain('TASK-20261001-001')
})

test('a compaction keeps the task and snapshots when settings have no snapshot hook', async ($, on) => {
  const runs: string[][] = []
  world(on, runs)
  let instructions = ''
  on('session.compact', async (_$, e) => {
    instructions = e.instructions ?? ''
    return { messages: e.messages }
  })
  await started($)
  await $.session.compact({ trigger: 'manual', instructions: 'focus on tests', messages: [{ role: 'user', text: 'hi', toolUses: [] }] })
  expect(instructions.startsWith('focus on tests')).toBe(true)
  expect(instructions).toContain('the summary must keep')
  expect(instructions).toContain('TASK-20261004-001')
  expect(runs).toContainEqual(['python', 'arbor.py', 'session', 'snapshot', '--session', 'sess-1'])
})

test('without arbor.py the mod stays out of the way', async ($, on) => {
  const runs: string[][] = []
  world(on, runs, '/elsewhere')
  on('tool.call', { tool: 'Read' }, async () => ({ result: 'whole file' }) as never)
  await started($)
  const r = await $.tool.call({ tool: 'Read', file_path: '/elsewhere/big.py' } as never)
  expect(r.result).toBe('whole file')
  expect(runs).toEqual([])
})
