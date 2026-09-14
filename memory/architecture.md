# Architecture

> English-only stack/structure facts, not prose -- replace an outdated line, don't append.
> Update or re-read only when the stack changes, or on request. Cap ~400 tokens
> (see [[development]]).

- Language/runtime: Python 3.10+, standard library only, no third-party dependency.
- Single entry point: `arbor.py` (commands: `init`, `memory`, `session`).
- Memory: Markdown vault in `memory/`, three time rings -- hot (`NOW.md`), warm
  (rules/architecture/decisions/bugs/investigations), cold (`archive/`, excluded from
  retrieval). See [[decisions#DEC-20260914-001 Context Arbor memory topology]].
- Entries (TASK/BUG/DEC/INV) may carry typed `Relations:` edges to other entry IDs;
  `memory trace <ID>` walks them locally, no model. See
  [[decisions#DEC-20260914-003 Typed Relations field and local trace]].
- Retrieval (`memory query`): local lexical top-k, no model/network, excludes
  templates/archive, weights the hot ring and `links.md` anchors above general matches.
- Session state: `.arbor/session-state.md`; Claude Code hooks snapshot/restore it around
  native compaction (`session gauge/snapshot/restore`).
- Agent adapters point to `NOW.md` and search on demand; the vault is never loaded in full.
