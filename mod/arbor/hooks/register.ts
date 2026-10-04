import type { EngineInterface, Register } from 'claude-code'

// Context Arbor inside Claude Code. The logic stays in the project's arbor.py: this module
// only calls it (no shell, cwd = project root) and hooks the engine where a settings hook
// cannot reach. A project without arbor.py leaves every hook a pass-through.

type $ = EngineInterface

const OUTPUT_CHARS = 12_000 // a tool answer the model reads, at most
const TASK_CHARS = 1_500 // active task attached to the start context
const JEV_NOTES_MAX = 300 // notes one Jev call may weigh
const JEV_SNIPPET = 300 // characters of each note the picker reads
const HAIKU_USD = { input: 1e-6, cacheWrite: 1.25e-6, cacheRead: 0.1e-6, output: 5e-6 } // Haiku 4.5, per token
const USER_ORIGINS = new Set(['composer', 'bridge', 'sdk'])
const CLOSED = /^(closed|done|resolved|archived)$/i
const MANAGED_BLOCK = /# Context Arbor: memory and sessions[^\n]*\n[\s\S]*?Context Arbor invokes no model\.[^\n]*/

const KEEP = [
  'Context Arbor: the summary must keep',
  '1) the active task, its acceptance criteria and where it stands (memory/NOW.md);',
  '2) decisions made and why, and approaches ruled out;',
  '3) files changed and what changed in each;',
  '4) open questions and the next step;',
  "5) the user's explicit rules, corrections and preferences, verbatim where short.",
  'Drop tool output, file dumps and search results: mcp__arbor__code_show and mcp__arbor__memory_query bring them back.',
].join('\n')

const SLIM_BLOCK = [
  '# Context Arbor: memory and sessions (arbor mod)',
  '',
  'Find before you open: mcp__arbor__memory_query (vault notes), mcp__arbor__jev_ask (by meaning; code=true for code),',
  'mcp__arbor__code_map, code_find, code_outline, code_show (FILE:SYMBOL or FILE:START-END); read large files in parts.',
  'The active task from memory/NOW.md is attached as `arbor` when there is one. Keep NOW.md to the active task; store durable outcomes in linked notes.',
  'Update `memory/architecture.md` only when the stack or structure changes (short English facts, ~400 tokens).',
  'Preserve user rules. Update their checksum only after explicit user approval.',
  'Save state at milestones with mcp__arbor__session_save. The mod compacts long sessions between turns: compact, never restart.',
].join('\n')

type Tool = {
  name: string
  description: string
  inputSchema: Record<string, unknown>
  argv: (a: Record<string, unknown>) => string[]
  stdin?: (a: Record<string, unknown>) => string
}

const str = (v: unknown) => (typeof v === 'string' ? v : '')
const int = (v: unknown) => (typeof v === 'number' && Number.isFinite(v) && v > 0 ? [String(Math.floor(v))] : [])
const opt = (flag: string, v: unknown) => {
  const value = typeof v === 'number' ? int(v) : str(v) ? [str(v)] : []
  return value.length ? [flag, ...value] : []
}
const obj = (properties: Record<string, unknown>, required: string[] = []) => ({ type: 'object', properties, required })
const S = (description: string) => ({ type: 'string', description })
const N = (description: string) => ({ type: 'integer', description, minimum: 1 })
const B = (description: string) => ({ type: 'boolean', description })

const TOOLS: Tool[] = [
  {
    name: 'memory_query',
    description: "Search the project's durable notes (memory/: decisions, bugs, investigations, knowledge) by words. Returns ranked sections with paths and snippets.",
    inputSchema: obj({ question: S('What to look for'), top: N('Hits to return (default 5)') }, ['question']),
    argv: a => ['memory', 'query', str(a.question), ...opt('--top', a.top)],
  },
  {
    name: 'jev_ask',
    description: 'Search by meaning, any language: the vault notes (archive and linked entries included) or, with code=true, the code index. Costs a fraction of a cent when Jev is on; falls back to word search otherwise.',
    inputSchema: obj({
      question: S('The question'), code: B('Search the code instead of the notes'),
      show: B('Print the bodies too (bounded)'), top: N('Results to keep'),
      dir: S('With code=true: only files under this path prefix'),
    }, ['question']),
    argv: a => ['jev', 'ask', str(a.question), ...(a.code === true ? ['--code'] : []), ...(a.show === true ? ['--show'] : []),
      ...opt('--top', a.top), ...opt('--dir', a.dir)],
  },
  {
    name: 'code_map',
    description: 'Overview of the code: files, languages and main symbols within a token budget. Start here before opening files.',
    inputSchema: obj({ dir: S('Only this directory'), budget: N('Token budget of the map') }),
    argv: a => ['code', 'map', ...opt('--dir', a.dir), ...opt('--budget', a.budget)],
  },
  {
    name: 'code_find',
    description: 'Find symbols (functions, classes, sections) by topic in the code index. Returns file:line ranges for code_show.',
    inputSchema: obj({ query: S('Topic or name'), top: N('Hits to return'), kind: S('Only this symbol kind (function, class, ...)') }, ['query']),
    argv: a => ['code', 'find', str(a.query), ...opt('--top', a.top), ...opt('--kind', a.kind)],
  },
  {
    name: 'code_outline',
    description: "A file's symbols with their line ranges, without its body.",
    inputSchema: obj({ file: S('Path relative to the project root'), limit: N('Symbols to list') }, ['file']),
    argv: a => ['code', 'outline', str(a.file), ...opt('--limit', a.limit)],
  },
  {
    name: 'code_show',
    description: 'Print one symbol or line range: FILE:SYMBOL or FILE:START-END. The cheap way to read a part of a large file.',
    inputSchema: obj({ target: S('FILE:SYMBOL or FILE:START-END'), max_lines: N('Lines to print at most') }, ['target']),
    argv: a => ['code', 'show', str(a.target), ...opt('--max-lines', a.max_lines)],
  },
  {
    name: 'session_save',
    description: 'Save the session distillate (task, decisions, changed files, open questions) so it survives compaction and restarts. Call at milestones.',
    inputSchema: obj({ note: S('The distillate, short and factual') }, ['note']),
    argv: () => ['session', 'save', '--stdin'],
    stdin: a => str(a.note),
  },
]

// Options and session state. A reload starts both over; session.start fills them again.
const cfg = { python: 'python', guardKb: 40, compactAt: 'auto', slim: true, jevProvider: 'arbor', jevModel: 'haiku', recordTurns: true }
const st = {
  root: '', // project root holding arbor.py; '' keeps the mod inert
  window: 0, // compaction target in tokens; 0 = never
  settingsJevHook: false, // `arbor.py jev hook` already runs as a settings hook
  settingsSnapshot: false, // PreCompact `session snapshot` already runs as a settings hook
  jevEnabled: false, // `arbor.py jev on`, for jevProvider=arbor
  jevLast: '',
  compacting: false,
  guarded: new Set<string>(), // files whose whole read was answered with an outline once
}

function cap(text: string, limit = OUTPUT_CHARS) {
  return text.length <= limit ? text : `${text.slice(0, limit)}\n... [${text.length - limit} more characters cut: narrow the query]`
}

function k(n: number) {
  return n >= 1e6 ? `${(n / 1e6).toFixed(2)}M` : n >= 1e4 ? `${Math.round(n / 1e3)}k` : n >= 1e3 ? `${(n / 1e3).toFixed(1)}k` : String(n)
}

function rel(path: string) {
  const p = path.replace(/\\/g, '/')
  const r = st.root.replace(/\\/g, '/').replace(/\/$/, '') + '/'
  return p.toLowerCase().startsWith(r.toLowerCase()) ? p.slice(r.length) : /^[a-z]:\/|^\//i.test(p) ? '' : p.replace(/^\.\//, '')
}

async function run($: $, args: string[], stdin?: string, timeoutMs = 30_000) {
  const r = await $.process.run([cfg.python, 'arbor.py', ...args], {
    cwd: st.root, stdin: stdin ?? '', timeoutMs, env: { PYTHONIOENCODING: 'utf-8', PYTHONUTF8: '1' },
  })
  return { code: r.exitCode, out: r.stdout, err: r.stderr }
}

async function runJson<T>($: $, args: string[], stdin?: string, timeoutMs?: number): Promise<T | null> {
  try {
    const r = await run($, args, stdin, timeoutMs)
    return r.code === 0 ? (JSON.parse(r.out) as T) : null
  } catch {
    return null
  }
}

async function status($: $, ctx?: { tokens?: number; window: number }, usd?: number) {
  if (!st.root) return
  const parts = ['arbor']
  if (ctx?.tokens !== undefined) {
    const target = st.window ? Math.min(st.window, ctx.window) : ctx.window
    parts.push(`ctx ${k(ctx.tokens)}/${k(target)}${st.window ? '' : ' (no auto)'}`)
  }
  if (usd !== undefined) parts.push(`$${usd.toFixed(2)}`)
  if (st.jevLast) parts.push(st.jevLast)
  $.ui.status(parts.join(' · '))
}

async function activeTask($: $) {
  try {
    const text = await $.fs.read(`${st.root}/memory/NOW.md`)
    const blocks = text.split(/^(?=## )/m).filter(b => {
      const head = b.split('\n', 1)[0] ?? ''
      if (!/^## TASK/.test(head) || /YYYYMMDD|template/i.test(head)) return false
      const state = /^- Status:\s*(\S+)/m.exec(b)?.[1] ?? ''
      return !CLOSED.test(state)
    })
    const joined = blocks.map(b => b.trim()).join('\n\n')
    return joined ? cap(joined, TASK_CHARS) : ''
  } catch {
    return ''
  }
}

async function keepInstructions($: $) {
  const task = await activeTask($)
  return task ? `${KEEP}\n\nActive task:\n${task}` : KEEP
}

async function compactNow($: $) {
  if (st.compacting || !st.window) return
  const usage = await $.session.usage()
  const tokens = usage.context.tokens
  if (tokens === undefined || tokens < Math.min(st.window, usage.context.window)) return
  st.compacting = true
  try {
    const result = await $.session.compact({ instructions: await keepInstructions($) })
    if (!('skip' in result)) {
      $.ui.toast(`arbor: compacted ${k(result.tokensBefore ?? tokens)} → ${k(result.tokensAfter ?? 0)} at the ${k(st.window)} window`, { timeoutMs: 6000 })
    }
  } catch {
    // a turn started meanwhile: the next turn.complete tries again
  } finally {
    st.compacting = false
  }
}

async function warmUp($: $) {
  if (cfg.compactAt === 'auto') {
    const w = await runJson<{ window: number }>($, ['session', 'compaction', '--json'], '', 120_000)
    st.window = w?.window || 200_000
  }
  const jev = await runJson<{ enabled: boolean }>($, ['jev', 'status', '--json'])
  st.jevEnabled = Boolean(jev?.enabled)
  const usage = await $.session.usage()
  await status($, usage.context, usage.cost?.usd)
}

type TurnUsage = { model: string; input_tokens: number; output_tokens: number; cache_read_input_tokens?: number | null; cache_creation_input_tokens?: number | null }

async function recordTurn($: $, usage: TurnUsage, agent: boolean, ms: number) {
  try {
    const now = await $.session.usage()
    const record = {
      session: await $.session.id(), agent, model: usage.model,
      input: usage.input_tokens, output: usage.output_tokens,
      cache_read: usage.cache_read_input_tokens ?? 0, cache_write: usage.cache_creation_input_tokens ?? 0,
      ms, context: now.context.tokens ?? 0, usd_total: now.cost?.usd,
    }
    await run($, ['session', 'record-turn', '--stdin'], JSON.stringify(record))
  } catch {
    // accounting never breaks a turn
  }
}

async function snapshot($: $) {
  try {
    await run($, ['session', 'snapshot', '--session', await $.session.id()], '{}')
  } catch {
    // the snapshot is a floor, never a gate
  }
}

async function jevArbor($: $, prompt: string) {
  const r = await run($, ['jev', 'hook'], JSON.stringify({ prompt }), 20_000)
  if (r.code !== 0 || !r.out.trim()) return ''
  const out = JSON.parse(r.out) as { hookSpecificOutput?: { additionalContext?: string } }
  const context = out.hookSpecificOutput?.additionalContext ?? ''
  st.jevLast = context ? `jev ${(context.match(/^### /gm) ?? []).length}` : ''
  return context
}

type Entry = { id: string; file: string; title: string; body: string }
type Entries = { config: { spent_today: number; daily_cap_usd: number; top: number }; entries: Entry[] }

async function jevLog($: $, log: Record<string, unknown>) {
  try {
    await run($, ['jev', 'log'], JSON.stringify(log))
  } catch {
    // a lost log line costs a row in the UI, nothing more
  }
}

async function jevClaude($: $, prompt: string) {
  const payload = await runJson<Entries>($, ['jev', 'entries', '--json'])
  if (!payload || !payload.entries.length || payload.config.spent_today >= payload.config.daily_cap_usd) return ''
  const entries = payload.entries.slice(0, JEV_NOTES_MAX)
  const top = Math.max(1, payload.config.top)
  const started = Date.now()
  const answer = await $.model.complete({
    model: cfg.jevModel,
    effort: 'low',
    maxTokens: 200,
    timeoutMs: 15_000,
    system: `You pick which project notes a developer needs to carry out a request. A note counts only when it records a bug, decision or rule that bears directly on the request. Answer with JSON only: {"ids": ["n3"]}, at most ${top} ids, most relevant first; {"ids": []} when none bears on it.`,
    prompt: `<request>\n${prompt.slice(0, 4000)}\n</request>\n\nNotes (id | file | title | start):\n` +
      entries.map(n => `${n.id} | ${n.file} | ${n.title} | ${n.body.slice(0, JEV_SNIPPET).replace(/\s+/g, ' ')}`).join('\n'),
  })
  const u = answer.usage
  const cost = (u?.input_tokens ?? 0) * HAIKU_USD.input + (u?.cache_creation_input_tokens ?? 0) * HAIKU_USD.cacheWrite +
    (u?.cache_read_input_tokens ?? 0) * HAIKU_USD.cacheRead + (u?.output_tokens ?? 0) * HAIKU_USD.output
  let picked: Entry[] = []
  if (answer.isAnswered) {
    try {
      const ids = (JSON.parse(/\{[\s\S]*\}/.exec(answer.text)?.[0] ?? '{}') as { ids?: unknown }).ids
      const byId = new Map(entries.map(n => [n.id, n]))
      picked = (Array.isArray(ids) ? ids : []).map(id => byId.get(String(id))).filter((n): n is Entry => Boolean(n)).slice(0, top)
    } catch {
      picked = []
    }
  }
  await jevLog($, {
    source: 'claude', kind: 'memory', entries: entries.length, questions: entries.length, requests: 1,
    cost, latency_s: (Date.now() - started) / 1000, model: cfg.jevModel,
    injected: picked.map(n => n.title), top: picked.map(n => ({ title: n.title, p: 1 })),
    ...(answer.isAnswered ? {} : { error: String(answer.reason) }),
  })
  st.jevLast = picked.length ? `jev ${picked.length}` : ''
  if (!picked.length) return ''
  return [
    '[jev] Notes from memory/ that a model matched to this request. They may be out of date or wrong: check them against the code before relying on them. More, by meaning: mcp__arbor__jev_ask.',
    ...picked.map(n => `### ${n.file}: ${n.title}\n${n.body}`),
  ].join('\n\n')
}

async function callTool($: $, tool: Tool, args: Record<string, unknown>) {
  if (!st.root) return { deny: 'arbor: no arbor.py at the project root' }
  try {
    const r = await run($, tool.argv(args), tool.stdin?.(args), 120_000)
    const text = r.out.trim() || r.err.trim() || '(no output)'
    return { result: cap(r.code === 0 ? text : `[exit ${r.code}] ${text}${r.out.trim() && r.err.trim() ? `\n${r.err.trim()}` : ''}`) }
  } catch (err) {
    return { deny: `arbor: ${tool.name} failed: ${String(err).slice(0, 200)}` }
  }
}

// The denial text for a whole Read of a large indexed file, or '' to let it through.
async function readGuard($: $, path: string) {
  const file = rel(path)
  if (!file || st.guarded.has(file)) return ''
  const stat = await $.fs.stat(path)
  if (stat.kind !== 'file' || stat.size < cfg.guardKb * 1024) return ''
  const outline = await run($, ['code', 'outline', file, '--limit', '40'])
  if (outline.code !== 0 || !outline.out.trim()) return ''
  st.guarded.add(file)
  return `arbor: ${file} is ${Math.round(stat.size / 1024)} KB (~${k(Math.round(stat.size / 4))} tokens) and stays in context for the rest of the session. ` +
    `Read only the part you need: Read with offset/limit, or mcp__arbor__code_show "${file}:SYMBOL" / "${file}:START-END". ` +
    `Its outline is below. Asking for the whole file again goes through.\n\n${cap(outline.out.trim(), 6000)}`
}

async function start($: $) {
  try {
    const candidate = await $.session.root()
    if (!(await $.fs.exists(`${candidate}/arbor.py`))) return
    st.root = candidate
  } catch {
    return
  }
  for (const tool of TOOLS) {
    await $.tool.register({ name: tool.name, description: tool.description, inputSchema: tool.inputSchema })
  }
  try {
    const hooks = JSON.stringify((await $.settings.read()).hooks ?? {})
    st.settingsJevHook = hooks.includes('jev hook')
    st.settingsSnapshot = hooks.includes('session snapshot')
  } catch {
    // unreadable settings: assume none
  }
  if (cfg.compactAt !== 'off' && cfg.compactAt !== 'auto') st.window = Number.parseInt(cfg.compactAt, 10) * 1000
  $.clock.after(0, () => void warmUp($))
}

type InstructionFile = { content: string }

function slimmed<F extends InstructionFile>(files?: readonly F[]) {
  return files?.map(f => (MANAGED_BLOCK.test(f.content) ? { ...f, content: f.content.replace(/\r\n/g, '\n').replace(MANAGED_BLOCK, SLIM_BLOCK) } : f))
}

async function jevNote($: $, text: string) {
  try {
    if (cfg.jevProvider === 'claude') return await jevClaude($, text)
    return st.jevEnabled ? await jevArbor($, text) : ''
  } catch {
    return ''
  }
}

export const register: Register = (on, options) => {
  cfg.python = String(options.python || 'python')
  cfg.guardKb = Number(options.readGuardKb ?? 40)
  cfg.compactAt = String(options.compactAt || 'auto')
  cfg.slim = options.slimInstructions !== false
  cfg.jevProvider = String(options.jevProvider || 'arbor')
  cfg.jevModel = String(options.jevModel || 'haiku')
  cfg.recordTurns = options.recordTurns !== false

  // ---- session start: find arbor.py, list the tools, read the window ----------------------
  on('session.start', async ($, e, next) => {
    const started = await next(e)
    await start($)
    return started
  })

  // ---- 1. the tools -------------------------------------------------------------------------
  for (const tool of TOOLS) {
    on('tool.call', { tool: `mcp__arbor__${tool.name}` }, async ($, e) => callTool($, tool, e as unknown as Record<string, unknown>))
  }

  // ---- 2. whole reads of large indexed files answer with the outline first -----------------
  on('tool.call', { tool: 'Read' }, async ($, e, next) => {
    const input = e as unknown as { file_path?: string; offset?: number; limit?: number; pages?: string }
    if (!st.root || cfg.guardKb <= 0 || input.offset !== undefined || input.limit !== undefined || input.pages || !input.file_path) return next(e)
    let deny = ''
    try {
      deny = await readGuard($, input.file_path)
    } catch {
      deny = ''
    }
    return deny ? { deny } : next(e)
  })

  // ---- 3. status line, keep-instructions, compaction between turns ------------------------
  on('session.measure', async ($, e, next) => {
    const r = await next(e)
    await status($, e.context, e.cost?.usd)
    return r
  })

  on('session.compact', async ($, e, next) => {
    if (!st.root || e.agentId) return next(e)
    if (!st.settingsSnapshot && e.trigger !== 'precompute') await snapshot($)
    const ours = await keepInstructions($)
    return next({ ...e, instructions: e.instructions ? `${e.instructions}\n\n${ours}` : ours })
  })

  on('turn.complete', async ($, e, next) => {
    const r = await next(e)
    if (!st.root) return r
    const usage = e.usage
    if (cfg.recordTurns && usage) {
      const agent = Boolean(e.agentId)
      const ms = e.durationMs
      $.clock.after(0, () => void recordTurn($, usage, agent, ms))
    }
    if (!e.agentId && !e.isAborted && st.window) $.clock.after(1500, () => void compactNow($))
    return r
  })

  // ---- 4. lean start context: short CLAUDE.md block plus the active task --------------------
  on('prompt.context', async ($, e, next) => {
    if (!st.root || !cfg.slim) return next(e)
    const down = slimmed(e.instructionFiles)
    const r = await next(down ? { ...e, instructionFiles: down } : e)
    const again = slimmed(r.instructionFiles)
    const task = await activeTask($)
    const blocks = task ? [...r.blocks.filter(b => b.name !== 'arbor'), { name: 'arbor', text: `Active task (memory/NOW.md):\n\n${task}` }] : r.blocks
    return again && again.some((f, i) => f !== r.instructionFiles?.[i]) ? { ...r, blocks, instructionFiles: again } : { ...r, blocks }
  })

  // ---- 5. Jev: the notes a model matches to the prompt ride along with it -------------------
  on('prompt.submit', async ($, e, next) => {
    const text = e.text.trim()
    if (!st.root || cfg.jevProvider === 'off' || st.settingsJevHook || !USER_ORIGINS.has(e.origin.kind) || !text || text.startsWith('/')) return next(e)
    const note = await jevNote($, text)
    return next(note ? { ...e, context: [...(e.context ?? []), note] } : e)
  })
}
