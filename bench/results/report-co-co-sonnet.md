# Context Arbor A/B — suite co (co), model sonnet: arbor vs control

1 tasks, 3 paired runs (control vs arbor); 0 run(s) errored/timed out and are excluded.

Effect = arbor / control (geometric mean over tasks; 95% bootstrap interval over tasks). Below 1.00 means `arbor` used less.

| metric | effect | 95% interval | tasks lower | sign-test p | verdict |
|---|---|---|---|---|---|
| Context processed | 0.73 (-27%) | 0.54 – 1.00 | 1/1 | 1.00 | less |
| Cost, steady state | 0.72 (-28%) | 0.55 – 1.05 | 1/1 | 1.00 | no significant difference |
| Cost as billed in these runs (cache luck) | 0.63 (-37%) | 0.44 – 1.06 | 1/1 | 1.00 | no significant difference |
| Model calls (turns) | 0.98 (-2%) | 0.81 – 1.15 | 1/1 | 1.00 | no significant difference |
| Tool output entering context | 0.64 (-36%) | 0.49 – 1.03 | 1/1 | 1.00 | no significant difference |
| Output tokens | 0.83 (-17%) | 0.61 – 1.43 | 1/1 | 1.00 | no significant difference |
| Time | 0.81 (-19%) | 0.51 – 1.39 | 1/1 | 1.00 | no significant difference |

Accuracy (task score 0–1): control 1.00, arbor 1.00; difference +0.00 (95% interval +0.00 – +0.00) → no significant difference.

| mean per run | control | arbor |
|---|---|---|
| Context processed | 324,967 | 237,727 |
| Cost, steady state | 51,286 | 38,111 |
| Cost as billed in these runs (cache luck) | 0.211 | 0.142 |
| Model calls (turns) | 12 | 12 |
| Tool output entering context | 5,643 | 3,822 |
| Output tokens | 4,639 | 4,180 |
| Time | 70 | 58 |
| Context at the first turn | 17,990 | 14,350 |
| `arbor.py` commands run | 0.000 | 5.000 |

Adoption: 3 of 3 sessions (100%).

Per task (arbor / control, context processed):

- bug016-autosave: 0.73

# Context Arbor A/B — suite co (co), model sonnet: jev vs arbor

1 tasks, 3 paired runs (arbor vs jev); 0 run(s) errored/timed out and are excluded.

Effect = jev / arbor (geometric mean over tasks; 95% bootstrap interval over tasks). Below 1.00 means `jev` used less.

| metric | effect | 95% interval | tasks lower | sign-test p | verdict |
|---|---|---|---|---|---|
| Context processed | 1.46 (+46%) | 0.99 – 2.16 | 0/1 | 1.00 | no significant difference |
| Cost, steady state | 1.44 (+44%) | 1.01 – 1.97 | 0/1 | 1.00 | more |
| Cost as billed in these runs (cache luck) | 1.44 (+44%) | 1.04 – 1.93 | 0/1 | 1.00 | more |
| Model calls (turns) | 1.21 (+21%) | 1.00 – 1.53 | 0/1 | 1.00 | no significant difference |
| Tool output entering context | 1.35 (+35%) | 0.98 – 1.69 | 0/1 | 1.00 | no significant difference |
| Output tokens | 1.37 (+37%) | 0.89 – 2.03 | 0/1 | 1.00 | no significant difference |
| Time | 1.29 (+29%) | 0.70 – 2.54 | 0/1 | 1.00 | no significant difference |

Accuracy (task score 0–1): arbor 1.00, jev 1.00; difference +0.00 (95% interval +0.00 – +0.00) → no significant difference.

| mean per run | arbor | jev |
|---|---|---|
| Context processed | 237,727 | 401,913 |
| Cost, steady state | 38,111 | 62,080 |
| Cost as billed in these runs (cache luck) | 0.142 | 0.229 |
| Model calls (turns) | 12 | 15 |
| Tool output entering context | 3,822 | 5,518 |
| Output tokens | 4,180 | 6,901 |
| Time | 58 | 101 |
| Context at the first turn | 14,350 | 14,579 |
| `arbor.py` commands run | 5.000 | 0.000 |

Per task (jev / arbor, context processed):

- bug016-autosave: 1.46

# Context Arbor A/B — suite co (co), model sonnet: jev vs control

1 tasks, 3 paired runs (control vs jev); 0 run(s) errored/timed out and are excluded.

Effect = jev / control (geometric mean over tasks; 95% bootstrap interval over tasks). Below 1.00 means `jev` used less.

| metric | effect | 95% interval | tasks lower | sign-test p | verdict |
|---|---|---|---|---|---|
| Context processed | 1.06 (+6%) | 0.71 – 2.16 | 0/1 | 1.00 | no significant difference |
| Cost, steady state | 1.04 (+4%) | 0.65 – 2.07 | 0/1 | 1.00 | no significant difference |
| Cost as billed in these runs (cache luck) | 0.91 (-9%) | 0.46 – 2.04 | 1/1 | 1.00 | no significant difference |
| Model calls (turns) | 1.18 (+18%) | 0.94 – 1.77 | 0/1 | 1.00 | no significant difference |
| Tool output entering context | 0.86 (-14%) | 0.48 – 1.53 | 1/1 | 1.00 | no significant difference |
| Output tokens | 1.14 (+14%) | 0.58 – 2.89 | 0/1 | 1.00 | no significant difference |
| Time | 1.04 (+4%) | 0.52 – 3.53 | 0/1 | 1.00 | no significant difference |

Accuracy (task score 0–1): control 1.00, jev 1.00; difference +0.00 (95% interval +0.00 – +0.00) → no significant difference.

| mean per run | control | jev |
|---|---|---|
| Context processed | 324,967 | 401,913 |
| Cost, steady state | 51,286 | 62,080 |
| Cost as billed in these runs (cache luck) | 0.211 | 0.229 |
| Model calls (turns) | 12 | 15 |
| Tool output entering context | 5,643 | 5,518 |
| Output tokens | 4,639 | 6,901 |
| Time | 70 | 101 |
| Context at the first turn | 17,990 | 14,579 |
| `arbor.py` commands run | 0.000 | 0.000 |

Per task (jev / control, context processed):

- bug016-autosave: 1.06
