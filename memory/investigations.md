# Investigation Log

## INV-20261001-004 Does Jev save memory-read tokens (bench co-mem)

- Status: closed
- Date: 2026-10-01
- Question: Does the Jev UserPromptSubmit hook (an OpenRouter model picks vault notes and
  injects them) cut memory-read tokens versus control and plain Arbor?
- Findings: Suite co-mem, sonnet, 6 tasks x 3 runs per arm, 0 errors. Score: control 0.97,
  arbor 0.97, jev 1.00. Memory-read tokens per run: control 2290, arbor 2940, jev 60
  (memory calls 2.8 / 2.6 / 0.1). Jev vs control: context -54%, steady cost -67%, turns -41%,
  time -36%, 6/6 tasks lower (sign p=0.03). Arbor vs control: no significant difference.
  Jev's top note was the right one in 18/18 runs; its own spend was $0.0073 total, ~0.9 s
  latency per prompt. Bench spend $2.87.
- Conclusion: Jev saves memory reads on this suite; plain Arbor retrieval does not beat the
  agent's own reads. Limits: 6 tasks built so the vault holds the answer, one vault, one
  model; Jev is a paid external model call per prompt, unlike Arbor (no model). Do not ship
  it as default without a suite where memory is irrelevant (to price false injections).
- Relations:
- Links: bench/results/report-co-mem-co-mem-sonnet.html

## INV-20260929-003 What can Arbor do about cache-read cost

- Status: closed
- Date: 2026-09-29
- Question: Can Arbor remove cache as a factor in token cost, and can /compact be replaced
  without a model?
- Findings: In one working session on this project, cache reads were 96.4% of all input
  (5.5M of 5.7M tokens over 34 turns, average context about 167k). Cache read is the sum of
  the context size at every turn, so cost grows with turns times context. Arbor runs beside
  the agent shell and cannot change how the shell caches. It can shrink what is multiplied:
  how much text enters the context (targeted lookups instead of whole-file reads) and how long
  a context lives (a free /clear plus restore). /compact and auto-compact are model calls;
  /clear is not. Documented hooks: PreCompact can block compaction (exit 2), SessionEnd
  carries transcript_path, SessionStart stdout is added to the context.
- Conclusion: The cache cannot be removed, but the base it multiplies can be reduced. Ship a
  code index, a /clear-based flow and a `stats` command that measures; claim nothing until it
  is measured on real sessions.
- Relations:
- Links: [[decisions#DEC-20260929-005 Code index instead of whole-file reads]], [[decisions#DEC-20260929-006 /clear replaces /compact]]

## INV-20260914-002 Does Graph Engineering earn its cost here

- Status: closed
- Date: 2026-09-14
- Question: Should Context Arbor adopt Graph Engineering (typed knowledge graph, extraction
  pipeline, provenance metadata) as described in the "Graph Engineering for AI Agents" article?
- Findings: The article's own criterion needs at least 2 of 5 signals (connected multi-hop
  queries, time-varying relations, provenance requirements, shared multi-agent state,
  cross-session compounding) before a graph earns its cost. Context Arbor scores at most 1.5:
  multi-agent sharing is already solved by the flat file vault, and cross-session compounding is
  what the rings already do. A full typed graph also needs an extraction step that almost always
  calls a model, which conflicts with the "no model, stdlib only" boundary in [[architecture]].
- Conclusion: Do not adopt full Graph Engineering. Instead add the one cheap, aligned part: a
  narrow `Relations:` field entries fill in by hand (no extraction), plus a deterministic local
  traversal command. This is a schema of ~5 types, not a knowledge graph.
- Relations: relates-to:DEC-20260914-003
- Links: [[decisions#DEC-20260914-003 Typed Relations field and local trace]]

## INV-20260914-001 Karpathy-inspired rules

- Status: closed
- Date: 2026-09-14
- Question: Can the guidelines improve development structure without permanent prompt overhead?
- Findings: The source skill contains four useful principles but loading it verbatim would add a
  repeated instruction block. The same intent can be represented as fields in active task notes.
- Conclusion: Keep the detailed method on demand and make task state structurally verifiable.
- Relations:
- Links: [[development]], [[decisions#DEC-20260914-002 Development guidance]]
