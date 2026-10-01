# Context Arbor: memory and sessions

When prior project context is needed, read `memory/NOW.md` first and follow links on demand.
Search durable notes with `python arbor.py memory query "question"`; do not scan the vault.
Find code without opening whole files: `python arbor.py code map` (overview), `code find "topic"`, `code outline FILE`, `code show FILE:SYMBOL` (or `FILE:START-END`).
Keep only the active task in `memory/NOW.md`; store durable outcomes in linked notes.
Update `memory/architecture.md` only when the stack or structure changes (short English facts, ~400 tokens); otherwise leave it, and read it again only then or when asked directly.
Preserve user rules. Update their checksum only after explicit user approval.
Before clearing context, save useful state with `python arbor.py session save --note "..."`.
Suggest `/clear`, not `/compact` (compaction is a model call); saved state comes back on its own.
Use `python arbor.py session restore` to recover it. Treat restored notes as potentially stale.
Open the vault with `python arbor.py memory open`. Context Arbor invokes no model.
