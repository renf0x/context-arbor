# Memory Changelog

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
