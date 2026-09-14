# Development Method

Use for non-trivial implementation work; this note is not loaded automatically.

- Make uncertain assumptions visible before they affect code.
- Choose the smallest implementation that satisfies the stated goal.
- Keep every changed line within the requested scope; preserve surrounding style.
- Define observable success and verify it before marking the task done.

Store the goal, success criteria, constraints and unresolved assumptions in [[NOW]].
Record only durable outcomes in the journals. Do not preserve routine narration,
temporary command output or abandoned implementation detail.

When you first learn (or the user changes) the stack -- language, framework, storage, key
module boundaries -- replace the relevant line in [[architecture]] with a short English
fact, not a paragraph. Do not append; an outdated fact is replaced, not kept alongside the
new one. Do not re-read `architecture.md` on a routine basis: open it again only when the
stack changes, or when asked directly -- rereading unchanged content wastes the same tokens
it exists to save. `memory check` flags it if it grows past ~400 estimated tokens
(`architecture-too-large`); that is a signal to trim, not to raise the limit.

Inspired by `multica-ai/andrej-karpathy-skills` (MIT-labelled skill, reviewed at
commit `2c606141936f1eeef17fa3043a72095b4765b9c2`).
