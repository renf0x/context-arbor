# Memory Changelog

## 2026-10-01 — Session hooks for the desktop app, opt-in Jev, served UI

- Session hooks now fire in the desktop app, whose clear opens a new `startup` session with
  no `SessionEnd(clear)`: restore snapshots the previous transcript itself; matchers widened.
- Added opt-in Jev (`arbor jev key|on|off|status|ask|hook`): a UserPromptSubmit hook asks an
  OpenRouter model which vault notes bear on the prompt and injects up to two. The key is
  stored encrypted per OS user (DPAPI / Keychain / Secret Service), never in the project
  (DEC-20261001-008, INV-20261001-004).
- `arbor ui --serve`: the chronicle on 127.0.0.1 with a Jev form (token, Host and Origin checks).
- Installers and package metadata point at the renamed repo renf0x/context-arbor.

## 2026-09-29 — Code index, /clear flow and chronicle page (v0.5.0)

- Added `arbor code index|map|find|outline|show|refs`: a stat-refreshed symbol table so an
  agent asks for one function or a project map instead of reading whole files
  (DEC-20260929-005). Lifts the old "no repository digest" line in docs/design.md.
- Replaced the neural /compact path: SessionEnd(clear) snapshots, SessionStart restores the
  state and the open task, `session compaction --mode` blocks /compact and auto-compact through
  the PreCompact hook, and the gauge now suggests /clear (DEC-20260929-006).
- Added `arbor stats` (token usage from local Claude Code transcripts, optional user-set
  prices) and `arbor ui` (static chronicle page: activity chart, memory rings, relation arcs,
  tokens). The first cut used a decorative tree-ring picture that could not be read; it was
  replaced by a labelled bar chart (DEC-20260929-007).
- Adapter blocks gained two lines; untouched stock blocks of v0.3/v0.4 are upgraded by
  `arbor init`, edited ones are kept.

## 2026-09-14 — architecture.md gets a real cap and an update trigger

- `memory/architecture.md` had no size limit, no update trigger and no instruction telling
  the agent to write to it -- the field's own history had exactly one commit. Added
  `ARCHITECTURE_MAX_TOKENS = 400` and a `memory check` issue code (`architecture-too-large`).
- Added one line to the always-loaded adapter blocks (`CLAUDE.md`/`AGENTS.md`/
  `AGENT_CONTEXT.md`): update the note (short English facts, replace not append) only when
  the stack changes or is supplemented, and re-read it only then or on direct request --
  never as routine per-session overhead.
- Rewrote this project's own `architecture.md` to the new format (bullet facts, links to
  `decisions.md`/`investigations.md` for rationale) as the first real instance.

## 2026-09-14 — Typed Relations field and local trace

- TASK/BUG/DEC/INV templates gained an optional `Relations:` field: a hand-filled, narrow
  (5-type) edge to another entry ID. Direction is always this entry -> target.
- Added `python arbor.py memory trace <ID> [--depth N] [--json]`: deterministic local
  traversal of those edges in both directions, no model, no database.
- `memory check` gained `unknown-relation-type` and `dangling-relation` issue codes.
- Evaluated and declined full Graph Engineering (typed knowledge graph, extraction,
  provenance) as not earning its cost here; see INV-20260914-002 and DEC-20260914-003.

## 2026-09-14 — Context Arbor v0.3.0

- Renamed the project, CLI, managed blocks and local state paths from CACP/ctx to Context Arbor.
- Replaced the root handoff with the Obsidian-native hot ring `memory/NOW.md`.
- Added weighted hot/warm/cold retrieval, sparse bilingual links and an active-memory size check.
- Integrated Karpathy-inspired development principles through task fields and an on-demand note.
- Removed historical CACP experiment records at the user's request.
