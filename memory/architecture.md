# Architecture

> English-only stack/structure facts, not prose -- replace an outdated line, don't append.
> Update or re-read only when the stack changes, or on request. Cap ~400 tokens
> (see [[development]]).

- Runtime: Python 3.10+, standard library only. One file, `arbor.py`: init, memory, code, session, stats, ui.
- Memory: Markdown vault `memory/`; hot `NOW.md`, warm rules/architecture/journals, cold `archive/` (never retrieved). [[decisions#DEC-20260914-001 Context Arbor memory topology]]
- Entries (TASK/BUG/DEC/INV) may carry typed `Relations:`; `memory trace` walks them. [[decisions#DEC-20260914-003 Typed Relations field and local trace]]
- `memory query`: lexical top-k, hot ring and `links.md` weighted, no model.
- Code index `.arbor/code-index.json`, stat-refreshed (Python `ast`, line rules elsewhere): `code map|find|outline|show|refs`. [[decisions#DEC-20260929-005 Code index instead of whole-file reads]]
- Session state `.arbor/session-state.md`; hooks: gauge, snapshot (PreCompact, SessionEnd clear), restore, compact-guard (opt-in block). [[decisions#DEC-20260929-006 /clear replaces /compact]]
- `stats` reads Claude Code transcripts (usage only); `ui` writes static `.arbor/ui/index.html`, no server. [[decisions#DEC-20260929-007 Static chronicle page]]
- Adapters point to `NOW.md` and on-demand commands; the vault is never loaded whole.
