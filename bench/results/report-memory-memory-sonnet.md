# Context Arbor A/B — suite memory (memory), model sonnet: arbor vs control

19 tasks, 57 paired runs (control vs arbor); 0 run(s) errored/timed out and are excluded.

Effect = arbor / control (geometric mean over tasks; 95% bootstrap interval over tasks). Below 1.00 means `arbor` used less.

| metric | effect | 95% interval | tasks lower | sign-test p | verdict |
|---|---|---|---|---|---|
| Context processed | 0.58 (-42%) | 0.53 – 0.64 | 19/19 | 0.00 | less |
| Cost, steady state | 0.64 (-36%) | 0.58 – 0.72 | 18/19 | 0.00 | less |
| Cost as billed in these runs (cache luck) | 0.42 (-58%) | 0.40 – 0.45 | 19/19 | 0.00 | less |
| Model calls (turns) | 0.73 (-27%) | 0.67 – 0.79 | 17/19 | 0.00 | less |
| Tool output entering context | 2.00 (+100%) | 1.36 – 2.82 | 4/19 | 0.02 | more |
| Output tokens | 0.53 (-47%) | 0.45 – 0.62 | 19/19 | 0.00 | less |
| Time | 0.99 (-1%) | 0.87 – 1.12 | 10/19 | 1.00 | no significant difference |

Accuracy (task score 0–1): control 1.00, arbor 1.00; difference +0.00 (95% interval +0.00 – +0.00) → no significant difference.

| mean per run | control | arbor |
|---|---|---|
| Context processed | 53,283 | 30,422 |
| Cost, steady state | 6,799 | 4,286 |
| Cost as billed in these runs (cache luck) | 0.044 | 0.019 |
| Model calls (turns) | 2.877 | 2.053 |
| Tool output entering context | 345 | 464 |
| Output tokens | 380 | 195 |
| Time | 8.096 | 7.632 |
| Context at the first turn | 17,958 | 14,301 |
| `arbor.py` commands run | 0.000 | 1.000 |

Adoption: 57 of 57 sessions (100%).

Per task (arbor / control, context processed):

- memory-absent1: 0.54
- memory-absent2: 0.53
- memory-cause1: 0.48
- memory-cause2: 0.53
- memory-cause3: 0.54
- memory-cause4: 0.40
- memory-count1: 0.71
- memory-count2: 0.68
- memory-current1: 0.49
- memory-current2: 0.69
- memory-current3: 0.48
- memory-current4: 0.52
- memory-current5: 0.65
- memory-replaced1: 0.81
- memory-replaced2: 0.82
- memory-replaced3: 0.62
- memory-supersedes1: 0.70
- memory-supersedes2: 0.54
- memory-supersedes3: 0.54

# Context Arbor A/B — suite memory (memory), model sonnet: nomem vs control

19 tasks, 57 paired runs (control vs nomem); 0 run(s) errored/timed out and are excluded.

Effect = nomem / control (geometric mean over tasks; 95% bootstrap interval over tasks). Below 1.00 means `nomem` used less.

| metric | effect | 95% interval | tasks lower | sign-test p | verdict |
|---|---|---|---|---|---|
| Context processed | 0.78 (-22%) | 0.71 – 0.87 | 16/19 | 0.00 | less |
| Cost, steady state | 0.82 (-18%) | 0.74 – 0.90 | 17/19 | 0.00 | less |
| Cost as billed in these runs (cache luck) | 0.49 (-51%) | 0.46 – 0.53 | 19/19 | 0.00 | less |
| Model calls (turns) | 1.00 (+0%) | 0.91 – 1.11 | 6/19 | 0.17 | no significant difference |
| Tool output entering context | 0.95 (-5%) | 0.80 – 1.14 | 12/19 | 0.36 | no significant difference |
| Output tokens | 1.03 (+3%) | 0.88 – 1.21 | 8/19 | 0.65 | no significant difference |
| Time | 1.00 (+0%) | 0.89 – 1.15 | 11/19 | 0.65 | no significant difference |

Accuracy (task score 0–1): control 1.00, nomem 1.00; difference +0.00 (95% interval +0.00 – +0.00) → no significant difference.

| mean per run | control | nomem |
|---|---|---|
| Context processed | 53,283 | 42,045 |
| Cost, steady state | 6,799 | 5,657 |
| Cost as billed in these runs (cache luck) | 0.044 | 0.022 |
| Model calls (turns) | 2.877 | 2.895 |
| Tool output entering context | 345 | 314 |
| Output tokens | 380 | 393 |
| Time | 8.096 | 8.146 |
| Context at the first turn | 17,958 | 13,970 |
| `arbor.py` commands run | 0.000 | 0.000 |

Per task (nomem / control, context processed):

- memory-absent1: 0.52
- memory-absent2: 0.52
- memory-cause1: 0.71
- memory-cause2: 0.79
- memory-cause3: 0.87
- memory-cause4: 0.65
- memory-count1: 0.78
- memory-count2: 0.62
- memory-current1: 0.78
- memory-current2: 1.25
- memory-current3: 0.78
- memory-current4: 1.04
- memory-current5: 1.03
- memory-replaced1: 0.90
- memory-replaced2: 0.90
- memory-replaced3: 0.68
- memory-supersedes1: 0.90
- memory-supersedes2: 0.78
- memory-supersedes3: 0.78

# Context Arbor A/B — suite memory (memory), model sonnet: arbor vs nomem

19 tasks, 57 paired runs (nomem vs arbor); 0 run(s) errored/timed out and are excluded.

Effect = arbor / nomem (geometric mean over tasks; 95% bootstrap interval over tasks). Below 1.00 means `arbor` used less.

| metric | effect | 95% interval | tasks lower | sign-test p | verdict |
|---|---|---|---|---|---|
| Context processed | 0.74 (-26%) | 0.67 – 0.83 | 16/19 | 0.00 | less |
| Cost, steady state | 0.79 (-21%) | 0.69 – 0.90 | 12/19 | 0.36 | less |
| Cost as billed in these runs (cache luck) | 0.86 (-14%) | 0.77 – 0.97 | 13/19 | 0.17 | less |
| Model calls (turns) | 0.73 (-27%) | 0.66 – 0.80 | 16/19 | 0.00 | less |
| Tool output entering context | 2.11 (+111%) | 1.46 – 2.95 | 3/19 | 0.00 | more |
| Output tokens | 0.52 (-48%) | 0.43 – 0.63 | 17/19 | 0.00 | less |
| Time | 0.98 (-2%) | 0.85 – 1.13 | 10/19 | 1.00 | no significant difference |

Accuracy (task score 0–1): nomem 1.00, arbor 1.00; difference +0.00 (95% interval +0.00 – +0.00) → no significant difference.

| mean per run | nomem | arbor |
|---|---|---|
| Context processed | 42,045 | 30,422 |
| Cost, steady state | 5,657 | 4,286 |
| Cost as billed in these runs (cache luck) | 0.022 | 0.019 |
| Model calls (turns) | 2.895 | 2.053 |
| Tool output entering context | 314 | 464 |
| Output tokens | 393 | 195 |
| Time | 8.146 | 7.632 |
| Context at the first turn | 13,970 | 14,301 |
| `arbor.py` commands run | 0.000 | 1.000 |

Adoption: 57 of 57 sessions (100%).

Per task (arbor / nomem, context processed):

- memory-absent1: 1.04
- memory-absent2: 1.03
- memory-cause1: 0.67
- memory-cause2: 0.68
- memory-cause3: 0.62
- memory-cause4: 0.61
- memory-count1: 0.91
- memory-count2: 1.10
- memory-current1: 0.62
- memory-current2: 0.55
- memory-current3: 0.62
- memory-current4: 0.50
- memory-current5: 0.63
- memory-replaced1: 0.91
- memory-replaced2: 0.91
- memory-replaced3: 0.91
- memory-supersedes1: 0.78
- memory-supersedes2: 0.69
- memory-supersedes3: 0.69
