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

## INV-20261002-001 Do cognee and Graphiti earn a place in Arbor; can agent caches move into a graph

- Status: closed
- Date: 2026-10-02
- Question: Should Arbor adopt cognee or Graphiti (graph memory for agents), and can the Claude/Codex cache be moved into such a system so agents query it instead of reading it?
- Findings: Graphiti (getzep, Apache-2.0): temporal knowledge graph; every write (add_episode, even add_triplet) calls an LLM for extraction, dedup and fact invalidation (~10 calls for a turn with 5 entities and 6 facts, >20 with custom types; issue #467 reports ~$0.80 per ~40 short chats on OpenAI defaults); needs Neo4j/FalkorDB/Neptune (Kuzu deprecated) plus embeddings. Reads are LLM-free hybrid search (BM25 + cosine + BFS, RRF/MMR/cross-encoder). Zep paper, LongMemEval (chat memory): context 115k -> 1.6k tokens, accuracy 60.2 -> 71.2% (gpt-4o); DMR 94.8% vs 94.4% full context. cognee v1.6.1 (Apache-2.0): remember/recall/improve/forget on Postgres+pgvector (graph-on-Postgres is a demo), optional GLiNER local extraction. Its Claude Code plugin (cognee-integrations) uses 7 hooks, captures prompts, tool traces and answers, bootstraps a local server (:8011, uv + venv), extracts with an LLM (without a key via `claude -p`, i.e. the same Claude limits) and injects up to 12,000 chars on every prompt over 5 chars, plus a symbol map on Read. Measured here on 2026-10-02: cache read is 98.3% of input in this project's Claude sessions (142.6M over 715 turns; fixed prefix ~57k tokens, the skills listing ~10k of it) and 96.2% in Codex (208.9M of 217.2M, 18 rollouts). Transcripts on disk (Claude 3.2 GB, Codex 212 MB) are not read by agents unless a session is resumed; prompts + answers are ~1% of this project's transcript text, tool results ~41%. Our bench already prices push injection: Jev -45% context on co-mem but +46% on co.
- Conclusion: Cache read is the live context re-sent on every turn; it cannot be moved into a graph, only shrunk. Do not adopt Graphiti or cognee as dependencies (a model on every write, a database server, extraction cost paid from the same limits). Borrow the model-free parts, each only with a bench suite that proves it: (1) a deterministic episode index over Claude + Codex transcripts with secret redaction (`history find/show/timeline`; SQLite FTS5 is available in stdlib, sqlite 3.45.3) and Codex rollouts in `stats`; (2) validity windows on entries (superseded hidden by default, `--as-of DATE`); (3) a provenance stamp on `memory add` (session id, commit). Keep injection pull-based.
- Relations: relates-to:INV-20260914-002
- Links: [[investigations#INV-20260914-002 Does Graph Engineering earn its cost here]], [[investigations#INV-20260929-003 What can Arbor do about cache-read cost]]

## INV-20261002-002 Long sessions without /clear: when compaction pays back

- Status: closed
- Date: 2026-10-02
- Question: User rejects /clear as a workflow. How can long sessions stay cheap without it?
- Findings: Claude Code docs (prompt-caching page): the model keeps nothing between requests, so the full context is re-sent every turn; a warm /compact sends the same prefix plus a summarization instruction and reads it from cache, so it costs about one turn of reading plus the summary output plus re-caching the short new context (cold cache after a break: full price). After compaction Claude Code re-reads up to five recently modified files and re-injects skill bodies (<=5k each), so the floor stays high. Auto-compact window is configurable: /autocompact 250k, setting autoCompactWindow, --autocompact, env CLAUDE_CODE_AUTO_COMPACT_WINDOW (100K-1M); default on native 1M models is ~967K. CLAUDE.md '# Compact instructions' customizes the summary; PreToolUse updatedInput can filter verbose command output; /rewind truncates to an already cached prefix. Codex config: model_auto_compact_token_limit, tool_output_token_limit, compact_prompt, experimental_compact_prompt_file. Contested Orbit data (stats --why): 4747 turns, cache read 98.1%; session 080a539a peaked at 796k and spent 40% of its cost at >=400k; session 833dcdd3 ran 102 manual /compact at ~152k -> 109k (rewrite 65.6k), one per 33 turns, which is about break-even at best (compaction 29% of its cost). A compaction from ~400k to ~110k pays back in ~10 turns (rates relative to input: cache read 0.1, 1h cache write 2, output 5).
- Conclusion: The cost problem was the 1M default threshold plus too-early manual compactions, not compaction itself; DEC-20260929-006 overstated its cost. Measured by replaying real sessions (`stats --simulate-compact`, see Results); the user chose compaction over /clear and asked to lift the block: implemented as DEC-20261002-001 (fixed window ~200k).
- Relations: relates-to:INV-20260929-003, relates-to:DEC-20261002-001
- Links: [[decisions#DEC-20260929-006 /clear replaces /compact]], [[investigations#INV-20261002-001 Do cognee and Graphiti earn a place in Arbor; can agent caches move into a graph]]
- Results: Contested Orbit, 4739 turns, model from 120 own compactions (carry 45.3k, rewrite 63.8k, summary ~3k): cost vs as recorded at 150k 0.88, 200k 0.85, 250k 0.90, 300k 0.95, 400k 1.09, default 967k 2.00 (manual /compact halved the cost against doing nothing). This project, 763 turns, fallback model: 150k 0.88, 200k 0.86, 250k 0.89, 300k 0.89, 400k 0.98. Long sessions save 16-27% at 200k. Suggested: autoCompactWindow 200k.

## INV-20261002-003 Jev as the agent's navigator for memory and code (instead of Graphiti for code)

- Status: open
- Date: 2026-10-02
- Question: Can Jev walk the memory (and code) so the agent only asks it and gets an answer or exact places to look? Should Graphiti be connected for reading large code?
- Findings: Jev = OpenRouter Decisions API (~typesafe/jev-latest): one yes/no question per candidate with a probability, no generated text; only section titles leave the machine. `jev ask` already exists in pointer mode. Live 2026-10-02: Russian memory question -> INV-20260914-002 at p=0.59 (correct), 14 candidates, $0.000063, 1.4 s; code question -> no match (Jev only sees JEV_FILES sections: NOW, bugs, decisions, knowledge, investigations). Graphiti does not fit code: every write is LLM extraction (~10+ calls per chunk, re-run on each change), needs Neo4j/FalkorDB + embeddings, ignores code snippets by default (issue #1299), and returns text facts rather than file:line places; static indexes (Arbor code index, LSP, cognee code graph) give places for free.
- Conclusion: Do not connect Graphiti or graphify for code: Arbor's index answers more for fewer tokens, and graphify's query output is broad and truncated. Jev is worth building as a pull-mode navigator: `jev ask` = local `memory query` merged with Jev over every section, hits expanded by their Relations (that recovers the cause questions), `--show` for bounded bodies; `jev ask --code` = the two-hop search above, printing `code show FILE:SYMBOL` pointers. Its value is meaning and language (Russian question, English code); for exact names `code find` stays first. Next: implement, then bench pull mode on the code and co-mem suites. Possible small fix found on the way: `code refs` caps its output, so `class X(SSHException)` lines of a common name get cut; rank definition and base-class lines first.
- Relations: relates-to:INV-20261002-001
- Links: [[investigations#INV-20261002-001 Do cognee and Graphiti earn a place in Arbor; can agent caches move into a graph]]
- Results: 2026-10-02, no model unless stated. graphify 0.9.73 (PyPI graphifyy, Graphify-Labs/graphify), `extract --code-only` on the bench paramiko fixture: 6.9 s vs 1.4 s for `code index`; graph.json 1.7 MB (+1.4 MB cache) vs 0.15 MB; 1656 nodes, 3145 edges. On the 13 bench code tasks (is the answer in the output): `graphify query` 48% at ~2100 tokens (8 of 13 truncated at its 2k budget), +`explain` 51%, `explain` alone 43% at 266 (no signatures or bodies; cross-object calls such as transport._set_K_H are not linked, so callers are missed); `code find` 29% at 260, find + show/refs/outline 95% at 797. graphify's own benchmark on paramiko: 4.8x fewer tokens than reading the whole corpus (the 71.5x is its showcase corpus). Its skill is 41.7k chars; `claude install` adds PreToolUse hooks on Bash|Grep|Read|Glob. Jev pull mode, live (OpenRouter, ~typesafe/jev-latest): code, two hops over the code index (all files, then symbols of the top 3; ~187 yes/no questions, 1.8 s, ~$0.0008 per question): 12 Russian descriptive questions on paramiko -> right symbol top-1 7/12, top-5 11/12; `code find` with the Russian text top-5 3/12, with an English rewording top-1 4/12, top-5 9/12; `graphify query` (English) 7/12 somewhere in ~2k tokens. Memory, bench memory suite (69 sections incl. archive, 9 questions): Jev with Russian wording top-3 5/9 (5/5 current values, 0/4 causes: it sees titles only and the cause sits in the DEC's Relations), `memory query` Russian 0/9, English 8/9; $0.0024 total, 1.0 s each.
