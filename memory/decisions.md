# Decision Log

## DEC-20260914-001 Context Arbor memory topology

- Status: active
- Date: 2026-09-14
- Decision: Use hot, warm and cold time rings connected by sparse bilingual links.
- Reason: Active context must stay small while durable facts remain locally retrievable.
- Consequences: `NOW.md` replaces `handoff.md`; archives are excluded from normal search.
- Relations:
- Links: [[NOW]], [[architecture]], [[links]]

## DEC-20260914-002 Development guidance

- Status: active
- Date: 2026-09-14
- Decision: Encode the Karpathy-inspired principles in task fields and an on-demand note.
- Reason: A full always-loaded skill adds prompt tokens on every task.
- Consequences: Tasks record success, constraints, assumptions, scope and verification without
  injecting the source skill into every agent session.
- Relations:
- Links: [[development]], [[NOW]]

## DEC-20260914-003 Typed Relations field and local trace

- Status: active
- Date: 2026-09-14
- Decision: Add an optional `Relations:` field to TASK/BUG/DEC/INV entries
  (`supersedes`, `caused-by`, `blocks`, `depends-on`, `relates-to`; direction is
  always this entry -> target) and a deterministic `python arbor.py memory
  trace <ID>` command that follows those edges up to `--depth` hops in both
  directions. `memory check` flags an unknown relation type and a dangling
  target (a referenced ID no entry defines).
- Reason: Full Graph Engineering does not earn its cost for this project
  (INV-20260914-002), but multi-hop questions like "what led to this decision"
  are real and currently require the agent to read several notes by hand. A
  hand-filled typed edge answers that without a model, a database or an
  extraction step -- agents fill the field the same way they already fill
  every other field when writing a note.
- Consequences: One more optional field per template (empty by default, no
  cost to entries that skip it). `memory check` gained two issue codes,
  `unknown-relation-type` and `dangling-relation`. The vocabulary is
  deliberately narrow (5 types) -- widen it only for a real recurring
  question, not speculatively.
- Relations: relates-to:INV-20260914-002
- Links: [[architecture]], `arbor.py` (`_relations_graph`, `cmd_memory_trace`)

## DEC-20260914-004 architecture.md gets a size cap and an update trigger

- Status: active
- Date: 2026-09-14
- Decision: Cap `memory/architecture.md` at ~400 estimated tokens
  (`ARCHITECTURE_MAX_TOKENS`, checked by `memory check` as
  `architecture-too-large`), require English-only bullet facts rather than
  prose, and add one line to the always-loaded adapter blocks: update the
  note (replace, not append) only when the stack changes or is supplemented,
  and re-read it only then or on direct request.
- Reason: The note had no size limit, no format rule and nothing telling an
  agent to write to it -- its entire history was one commit. A file nobody is
  told to maintain, with no cap forcing conciseness, was the weakest link in
  the vault compared to NOW.md (size-capped) and the DEC/BUG/INV journals
  (entry-triggered, now graph-linked).
- Consequences: One more line in the prompt loaded every session (small, one
  time). This project's own `architecture.md` was rewritten to the new
  format as the first real instance.
- Relations: relates-to:DEC-20260914-001
- Links: [[architecture]], `arbor.py` (`ARCHITECTURE_MAX_TOKENS`, `memory_check`)

## DEC-20260929-005 Code index instead of whole-file reads

- Status: active
- Date: 2026-09-29
- Decision: Add `arbor code index|map|find|outline|show|refs`: a local symbol and file table
  (`.arbor/code-index.json`, refreshed by a stat pass on every call; Python through `ast`,
  other languages through line rules; `.gitignore`, secrets and the memory vault excluded)
  queried with short commands whose output is bounded. This lifts the earlier design line
  "no repository digest" (docs/design.md, v0.3.0). It is a digest the agent asks for, not a
  read gate: nothing blocks a normal file read.
- Reason: Measured on this project, cache read is the bulk of input tokens
  (INV-20260929-003): every turn re-sends the whole context, so cost grows with turns times
  context size. Text pulled in by whole-file reads and wide greps is re-sent on every later
  turn. A symbol table lets the agent fetch one function, or a map, instead.
- Consequences: Two lines in the adapter blocks (about +45 tokens per session); untouched
  stock blocks of earlier releases are upgraded in place, edited ones are left alone.
  Non-Python extraction is approximate, so `code show FILE:START-END` stays the exact
  fallback. No saving is claimed; `arbor stats` measures. The top-level names `map`,
  `digest` and `read` stay rejected (tests): these commands live under `code`.
- Relations: relates-to:INV-20260929-003
- Links: [[architecture]], `arbor.py` (`_code_index`, `_code_find`, `cmd_code_show`)

## DEC-20260929-006 /clear replaces /compact

- Status: active
- Date: 2026-09-29
- Decision: Make `/clear` the model-free way to shrink context. A `SessionEnd` hook (matcher
  `clear`) snapshots the session; `SessionStart` (clear, compact, resume) restores it together
  with the open task from `NOW.md`. `session compaction --mode off|manual|all` (kept in
  `.arbor/config.json`, default off) makes the `PreCompact` hook exit 2 -- the documented way
  to block compaction -- for `/compact` (manual) or also for auto-compaction (all), after
  taking a snapshot. The gauge line and the adapters now suggest `/clear`.
- Reason: `/compact` and auto-compact are model calls over the whole context; `/clear` is not.
  `DISABLE_COMPACT` and `DISABLE_AUTO_COMPACT` are missing from the official docs and are
  reported not to hold (anthropics/claude-code#42394), so the documented hook is used.
- Consequences: Default stays `off` (RULE-001: a user's Claude Code is not changed silently).
  In mode `all` a session that reaches the window limit cannot auto-compact and must be
  cleared; its state is already saved. Existing installs get the hooks on the next
  `arbor init`. Verified against the hook contract in the docs and by unit tests; not yet
  observed inside a live interactive Claude Code session.
- Relations: relates-to:INV-20260929-003, relates-to:DEC-20260914-001
- Links: [[operations]], `arbor.py` (`cmd_session_compact_guard`, `CLAUDE_SETTINGS_JSON`)

## DEC-20260929-007 Static chronicle page

- Status: active
- Date: 2026-09-29
- Decision: `arbor ui` writes one self-contained HTML page (`.arbor/ui/index.html`) from the
  vault, `git log` and, when present, Claude Code transcripts: a chapter per day, ring token
  weights against their caps, arcs for typed relations, token usage, a code-map summary. Fixed
  rules choose headlines; no model, no server, no external resource (CSP `default-src 'none'`).
  Cost appears only when the user supplied prices (`stats --prices`).
- Reason: The user asked for a chronicle UI that needs no neural network. A static file needs
  no runtime and cannot send anything anywhere. Prices are user-supplied because a bundled
  table goes stale.
- Consequences: The first release drew a tree-ring cross-section and a core sample; neither had
  axes, labels or numbers, so it could not be read (user feedback, 2026-09-29). It was replaced
  by a plain stacked bar chart of events per day (axes, legend, columns link to the day's
  chapter) and a share bar for token classes. `stats` and `ui` read local transcripts (usage
  counts only), offline and read-only; they measure and claim no saving.
- Relations: relates-to:DEC-20260914-001, relates-to:INV-20260929-003
- Links: [[architecture]], `arbor.py` (`render_ui`, `cmd_ui`, `collect_usage`)

## DEC-20261001-008 Jev is the one opt-in model call

- Status: active
- Date: 2026-10-01
- Decision: Ship Jev inside arbor.py, off by default, enabled per project with `jev on`; the
  OpenRouter key is stored encrypted per OS user and read only by the hook.
- Reason: On bench co-mem it cut memory reads 2290 -> 60 tokens per run and context -54% vs
  control at equal accuracy, where local keyword retrieval cannot match Russian prompts to an
  English vault. Everything else stays model-free.
- Relations: depends-on:INV-20261001-004
- Links: [[investigations#INV-20261001-004 Does Jev save memory-read tokens (bench co-mem)]]
