# Context Arbor A/B — suite code (paramiko), model sonnet: arbor vs control

15 tasks, 60 paired runs (control vs arbor); 0 run(s) errored/timed out and are excluded.

Effect = arbor / control (geometric mean over tasks; 95% bootstrap interval over tasks). Below 1.00 means `arbor` used less.

| metric | effect | 95% interval | tasks lower | sign-test p | verdict |
|---|---|---|---|---|---|
| Context processed | 0.75 (-25%) | 0.67 – 0.83 | 14/15 | 0.00 | less |
| Cost, steady state | 0.80 (-20%) | 0.71 – 0.88 | 14/15 | 0.00 | less |
| Cost as billed in these runs (cache luck) | 0.52 (-48%) | 0.48 – 0.58 | 15/15 | 0.00 | less |
| Model calls (turns) | 0.92 (-8%) | 0.82 – 1.02 | 7/15 | 1.00 | no significant difference |
| Tool output entering context | 1.48 (+48%) | 0.93 – 2.56 | 7/15 | 1.00 | no significant difference |
| Output tokens | 0.89 (-11%) | 0.75 – 1.05 | 10/15 | 0.30 | no significant difference |
| Time | 1.04 (+4%) | 0.90 – 1.18 | 7/15 | 1.00 | no significant difference |

Accuracy (task score 0–1): control 1.00, arbor 0.99; difference -0.01 (95% interval -0.03 – +0.00) → no significant difference.

| mean per run | control | arbor |
|---|---|---|
| Context processed | 57,381 | 43,552 |
| Cost, steady state | 7,539 | 6,140 |
| Cost as billed in these runs (cache luck) | 0.046 | 0.026 |
| Model calls (turns) | 3.117 | 2.900 |
| Tool output entering context | 500 | 542 |
| Output tokens | 508 | 480 |
| Time | 9.510 | 9.833 |
| Context at the first turn | 17,724 | 14,274 |
| `arbor.py` commands run | 0.000 | 0.400 |

Adoption: the agent ran `arbor.py` in 20 of 60 sessions (33%). Context of those sessions vs the same task without Arbor: 0.80×; of the sessions that did not use it: 0.97× (descriptive, not an effect estimate).

Per task (arbor / control, context processed):

- paramiko-callers1: 0.74
- paramiko-callers2: 0.82
- paramiko-callers3: 1.02
- paramiko-class-line1: 0.82
- paramiko-class-line2: 0.81
- paramiko-defaults1: 0.66
- paramiko-defaults2: 0.79
- paramiko-method-count1: 0.87
- paramiko-method-count2: 0.61
- paramiko-raises1: 0.57
- paramiko-raises2: 0.47
- paramiko-rename1: 0.76
- paramiko-rename2: 0.82
- paramiko-subclasses1: 0.80
- paramiko-subclasses2: 0.81

# Context Arbor A/B — suite code (paramiko), model sonnet: nomem vs control

15 tasks, 60 paired runs (control vs nomem); 0 run(s) errored/timed out and are excluded.

Effect = nomem / control (geometric mean over tasks; 95% bootstrap interval over tasks). Below 1.00 means `nomem` used less.

| metric | effect | 95% interval | tasks lower | sign-test p | verdict |
|---|---|---|---|---|---|
| Context processed | 0.81 (-19%) | 0.76 – 0.87 | 15/15 | 0.00 | less |
| Cost, steady state | 0.88 (-12%) | 0.81 – 0.96 | 12/15 | 0.04 | less |
| Cost as billed in these runs (cache luck) | 0.51 (-49%) | 0.46 – 0.57 | 15/15 | 0.00 | less |
| Model calls (turns) | 1.04 (+4%) | 0.98 – 1.10 | 2/15 | 0.01 | no significant difference |
| Tool output entering context | 1.22 (+22%) | 0.97 – 1.62 | 3/15 | 0.04 | no significant difference |
| Output tokens | 1.03 (+3%) | 0.93 – 1.15 | 7/15 | 1.00 | no significant difference |
| Time | 0.99 (-1%) | 0.89 – 1.09 | 6/15 | 0.61 | no significant difference |

Accuracy (task score 0–1): control 1.00, nomem 0.97; difference -0.03 (95% interval -0.08 – +0.00) → no significant difference.

| mean per run | control | nomem |
|---|---|---|
| Context processed | 57,381 | 46,815 |
| Cost, steady state | 7,539 | 6,736 |
| Cost as billed in these runs (cache luck) | 0.046 | 0.025 |
| Model calls (turns) | 3.117 | 3.233 |
| Tool output entering context | 500 | 633 |
| Output tokens | 508 | 509 |
| Time | 9.510 | 9.330 |
| Context at the first turn | 17,724 | 13,737 |
| `arbor.py` commands run | 0.000 | 0.000 |

Per task (nomem / control, context processed):

- paramiko-callers1: 0.75
- paramiko-callers2: 0.79
- paramiko-callers3: 0.90
- paramiko-class-line1: 0.78
- paramiko-class-line2: 0.78
- paramiko-defaults1: 0.78
- paramiko-defaults2: 0.78
- paramiko-method-count1: 0.95
- paramiko-method-count2: 0.90
- paramiko-raises1: 0.88
- paramiko-raises2: 0.92
- paramiko-rename1: 0.79
- paramiko-rename2: 0.70
- paramiko-subclasses1: 0.78
- paramiko-subclasses2: 0.78

# Context Arbor A/B — suite code (paramiko), model sonnet: arbor vs nomem

15 tasks, 60 paired runs (nomem vs arbor); 0 run(s) errored/timed out and are excluded.

Effect = arbor / nomem (geometric mean over tasks; 95% bootstrap interval over tasks). Below 1.00 means `arbor` used less.

| metric | effect | 95% interval | tasks lower | sign-test p | verdict |
|---|---|---|---|---|---|
| Context processed | 0.92 (-8%) | 0.80 – 1.03 | 7/15 | 1.00 | no significant difference |
| Cost, steady state | 0.91 (-9%) | 0.78 – 1.03 | 8/15 | 1.00 | no significant difference |
| Cost as billed in these runs (cache luck) | 1.02 (+2%) | 0.90 – 1.14 | 4/15 | 0.12 | no significant difference |
| Model calls (turns) | 0.89 (-11%) | 0.78 – 0.99 | 8/15 | 1.00 | less |
| Tool output entering context | 1.15 (+15%) | 0.67 – 2.09 | 8/15 | 1.00 | no significant difference |
| Output tokens | 0.87 (-13%) | 0.72 – 1.03 | 10/15 | 0.30 | no significant difference |
| Time | 1.05 (+5%) | 0.95 – 1.16 | 6/15 | 0.61 | no significant difference |

Accuracy (task score 0–1): nomem 0.97, arbor 0.99; difference +0.02 (95% interval -0.03 – +0.07) → no significant difference.

| mean per run | nomem | arbor |
|---|---|---|
| Context processed | 46,815 | 43,552 |
| Cost, steady state | 6,736 | 6,140 |
| Cost as billed in these runs (cache luck) | 0.025 | 0.026 |
| Model calls (turns) | 3.233 | 2.900 |
| Tool output entering context | 633 | 542 |
| Output tokens | 509 | 480 |
| Time | 9.330 | 9.833 |
| Context at the first turn | 13,737 | 14,274 |
| `arbor.py` commands run | 0.000 | 0.400 |

Adoption: the agent ran `arbor.py` in 20 of 60 sessions (33%). Context of those sessions vs the same task without Arbor: 0.80×; of the sessions that did not use it: 0.97× (descriptive, not an effect estimate).

Per task (arbor / nomem, context processed):

- paramiko-callers1: 0.98
- paramiko-callers2: 1.03
- paramiko-callers3: 1.14
- paramiko-class-line1: 1.05
- paramiko-class-line2: 1.04
- paramiko-defaults1: 0.85
- paramiko-defaults2: 1.02
- paramiko-method-count1: 0.92
- paramiko-method-count2: 0.68
- paramiko-raises1: 0.65
- paramiko-raises2: 0.51
- paramiko-rename1: 0.96
- paramiko-rename2: 1.17
- paramiko-subclasses1: 1.03
- paramiko-subclasses2: 1.04
