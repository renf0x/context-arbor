# Investigation Log

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
