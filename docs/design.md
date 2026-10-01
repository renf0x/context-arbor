# Context Arbor design

Context Arbor is an agent-neutral, standard-library Python CLI for local project memory,
Obsidian navigation and session continuity.

The vault is a linked graph organized by time:

1. Hot ring: `memory/NOW.md`, capped at roughly 1500 estimated tokens.
2. Warm ring: durable rules, decisions, bugs, architecture and investigations.
   `architecture.md` is capped much tighter (~400 tokens, English-only facts, not
   prose) and is written or re-read only when the stack changes or on direct request --
   never as routine session overhead.
3. Cold ring: completed entries under `memory/archive/`, excluded from normal retrieval.

Sparse entries in `memory/links.md` connect Russian and English terminology to relevant
notes. Local lexical retrieval weights the hot ring and anchors, excludes templates and
archives, and returns bounded sections rather than whole files.

Entries may also declare a narrow, hand-filled `Relations:` edge to another entry ID
(five types; direction is always this entry -> target). `memory trace <ID>` walks those
edges locally for connected, multi-hop questions that lexical retrieval alone cannot
answer. This stops short of a knowledge graph on purpose: no extraction step (which would
need a model), no database, no schema beyond the five types -- see the "earns its cost"
evaluation in `memory/investigations.md` (INV-20260914-002).

Karpathy-inspired development guidance is encoded in task fields and kept in an on-demand
note. It does not add the upstream skill body to every agent prompt. The integration favors
observable success, explicit uncertainty, small scope and verification.

Session state lives in `.arbor/session-state.md`. Claude hooks snapshot it before the context
is dropped (`PreCompact`, and `SessionEnd` for any reason) and restore it, with the open task from
`NOW.md`, in the next context. The desktop app's clear starts a new session (`startup`) without
`SessionEnd`, so `restore` snapshots the project's previous transcript itself when it is newer
than the state (and under 12 h old). Model-based compaction is the costly path: `/compact` and
auto-compact re-read the whole context and write a summary, while `/clear` makes no model call.
`session compaction --mode` therefore lets a project block the former through the documented
`PreCompact` exit code, and the gauge and adapters point to `/clear`. The default is off.

Every turn re-sends the whole context, so what a session spends grows with turns times context
size (`memory/investigations.md`, INV-20260929-003). Arbor cannot change how the agent shell
caches; it can shrink what is multiplied. `arbor code map|find|outline|show|refs` answers "where
is X" from a stat-refreshed symbol table (`.arbor/code-index.json`; Python via `ast`, other
languages via line rules), returning one bounded slice instead of a whole file. It is a digest
the agent asks for, not a read gate -- nothing blocks a normal read -- and it replaces the
earlier "no repository digest" boundary (DEC-20260929-005).

`arbor stats` reads usage counts from the local Claude Code transcripts and reports them; prices
are supplied by the user, never bundled. `arbor ui` renders vault, git history and those counts
as one static HTML page with no model, server or external resource (DEC-20260929-007). Both
measure; neither claims a saving.

No billing collector, read gate, message translator or external model dependency is part of the
design.
