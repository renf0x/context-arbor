<!-- CONTEXT-ARBOR:START -->
# Context Arbor: memory and sessions

When prior project context is needed, read `memory/NOW.md` first and follow links on demand.
Search durable notes with `python arbor.py memory query "question"`; do not scan the vault.
Find code without opening whole files: `python arbor.py code map` (overview), `code find "topic"`, `code outline FILE`, `code show FILE:SYMBOL` (or `FILE:START-END`).
Keep only the active task in `memory/NOW.md`; store durable outcomes in linked notes.
Update `memory/architecture.md` only when the stack or structure changes (short English facts, ~400 tokens); otherwise leave it, and read it again only then or when asked directly.
Preserve user rules. Update their checksum only after explicit user approval.
Save state at milestones (`python arbor.py session save --note "..."`); `python arbor.py session restore` brings it back, possibly stale.
Long sessions: compact, don't restart; auto-compaction near 200k is cheapest (`/autocompact 200k`; Codex: `model_auto_compact_token_limit`).
When compacting, keep the task, decisions, changed files, open questions; drop tool output.
Open the vault with `python arbor.py memory open`. Context Arbor invokes no model.

<!-- CONTEXT-ARBOR:END -->
