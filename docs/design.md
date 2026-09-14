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

Session state lives in `.arbor/session-state.md`. Claude hooks may snapshot it before native
compaction and restore it afterwards. No billing collector, read gate, repository digest,
message translator or external model dependency is part of the design.
