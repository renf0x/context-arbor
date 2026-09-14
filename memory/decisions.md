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
