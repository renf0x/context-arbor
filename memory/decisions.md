# Decision Log

## DEC-20260914-001 Context Arbor memory topology

- Status: active
- Date: 2026-09-14
- Decision: Use hot, warm and cold time rings connected by sparse bilingual links.
- Reason: Active context must stay small while durable facts remain locally retrievable.
- Consequences: `NOW.md` replaces `handoff.md`; archives are excluded from normal search.
- Links: [[NOW]], [[architecture]], [[links]]

## DEC-20260914-002 Development guidance

- Status: active
- Date: 2026-09-14
- Decision: Encode the Karpathy-inspired principles in task fields and an on-demand note.
- Reason: A full always-loaded skill adds prompt tokens on every task.
- Consequences: Tasks record success, constraints, assumptions, scope and verification without
  injecting the source skill into every agent session.
- Links: [[development]], [[NOW]]
