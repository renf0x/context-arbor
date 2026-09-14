# Architecture

Context Arbor is a standard-library Python CLI with `init`, `memory` and `session` entry points.

Memory uses three time rings:

- Hot: `NOW.md`, limited to the active task and preferred by local retrieval.
- Warm: rules, architecture, decisions, bugs and investigations.
- Cold: archived completed entries, excluded from normal retrieval.

`links.md` adds sparse bilingual aliases and Obsidian links across the rings. Retrieval is local,
excludes templates and archives, and weights hot or linked facts above general journal matches.
No model, provider key or network request participates in retrieval.

Session state lives in `.arbor/session-state.md`; legacy `.ctx` state migrates on first read.
Claude Code hooks can snapshot and restore session state around native compaction. Agent adapters
point to `NOW.md` and search on demand instead of loading the vault.
