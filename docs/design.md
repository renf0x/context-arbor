# Context Arbor design

Context Arbor is an agent-neutral, standard-library Python CLI for local project memory,
Obsidian navigation and session continuity.

The vault is a linked graph organized by time:

1. Hot ring: `memory/NOW.md`, capped at roughly 1500 estimated tokens.
2. Warm ring: durable rules, decisions, bugs, architecture and investigations.
3. Cold ring: completed entries under `memory/archive/`, excluded from normal retrieval.

Sparse entries in `memory/links.md` connect Russian and English terminology to relevant
notes. Local lexical retrieval weights the hot ring and anchors, excludes templates and
archives, and returns bounded sections rather than whole files.

Karpathy-inspired development guidance is encoded in task fields and kept in an on-demand
note. It does not add the upstream skill body to every agent prompt. The integration favors
observable success, explicit uncertainty, small scope and verification.

Session state lives in `.arbor/session-state.md`. Claude hooks may snapshot it before native
compaction and restore it afterwards. No billing collector, read gate, repository digest,
message translator or external model dependency is part of the design.
