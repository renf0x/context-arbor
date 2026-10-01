# Context Arbor A/B — suite code-session (paramiko), model sonnet: arbor vs control

4 tasks, 16 paired runs (control vs arbor); 0 run(s) errored/timed out and are excluded.

Effect = arbor / control (geometric mean over tasks; 95% bootstrap interval over tasks). Below 1.00 means `arbor` used less.

| metric | effect | 95% interval | tasks lower | sign-test p | verdict |
|---|---|---|---|---|---|
| Context processed | 1.07 (+7%) | 0.84 – 1.33 | 1/4 | 0.62 | no significant difference |
| Cost, steady state | 1.23 (+23%) | 1.00 – 1.51 | 0/4 | 0.12 | more |
| Cost as billed in these runs (cache luck) | 1.05 (+5%) | 0.88 – 1.27 | 2/4 | 1.00 | no significant difference |
| Model calls (turns) | 1.13 (+13%) | 0.90 – 1.38 | 1/4 | 0.62 | no significant difference |
| Tool output entering context | 1.47 (+47%) | 0.95 – 2.16 | 0/4 | 0.12 | no significant difference |
| Output tokens | 1.25 (+25%) | 0.98 – 1.50 | 0/4 | 0.12 | no significant difference |
| Time | 1.20 (+20%) | 0.98 – 1.42 | 0/4 | 0.12 | no significant difference |

Accuracy (task score 0–1): control 0.95, arbor 1.00; difference +0.05 (95% interval +0.01 – +0.08) → better.

| mean per run | control | arbor |
|---|---|---|
| Context processed | 140,747 | 148,929 |
| Cost, steady state | 27,874 | 34,042 |
| Cost as billed in these runs (cache luck) | 0.127 | 0.135 |
| Model calls (turns) | 5.562 | 6.250 |
| Tool output entering context | 5,490 | 8,102 |
| Output tokens | 2,804 | 3,481 |
| Time | 29 | 34 |
| Context at the first turn | 18,135 | 14,687 |
| `arbor.py` commands run | 0.000 | 0.000 |

Adoption: 0 of 16 sessions (0%).

Per task (arbor / control, context processed):

- paramiko-session1: 1.23
- paramiko-session2: 0.86
- paramiko-session3: 1.15
- paramiko-session4: 1.09

# Context Arbor A/B — suite code-session (paramiko), model sonnet: nomem vs control

4 tasks, 16 paired runs (control vs nomem); 0 run(s) errored/timed out and are excluded.

Effect = nomem / control (geometric mean over tasks; 95% bootstrap interval over tasks). Below 1.00 means `nomem` used less.

| metric | effect | 95% interval | tasks lower | sign-test p | verdict |
|---|---|---|---|---|---|
| Context processed | 1.03 (+3%) | 0.85 – 1.23 | 2/4 | 1.00 | no significant difference |
| Cost, steady state | 1.05 (+5%) | 0.82 – 1.30 | 2/4 | 1.00 | no significant difference |
| Cost as billed in these runs (cache luck) | 0.89 (-11%) | 0.74 – 1.05 | 4/4 | 0.12 | no significant difference |
| Model calls (turns) | 1.18 (+18%) | 1.01 – 1.36 | 0/4 | 0.12 | more |
| Tool output entering context | 1.04 (+4%) | 0.63 – 1.54 | 2/4 | 1.00 | no significant difference |
| Output tokens | 1.16 (+16%) | 1.00 – 1.34 | 0/4 | 0.12 | more |
| Time | 1.13 (+13%) | 0.95 – 1.35 | 1/4 | 0.62 | no significant difference |

Accuracy (task score 0–1): control 0.95, nomem 0.91; difference -0.04 (95% interval -0.27 – +0.08) → no significant difference.

| mean per run | control | nomem |
|---|---|---|
| Context processed | 140,747 | 140,702 |
| Cost, steady state | 27,874 | 28,636 |
| Cost as billed in these runs (cache luck) | 0.127 | 0.114 |
| Model calls (turns) | 5.562 | 6.438 |
| Tool output entering context | 5,490 | 5,662 |
| Output tokens | 2,804 | 3,182 |
| Time | 29 | 32 |
| Context at the first turn | 18,135 | 14,144 |
| `arbor.py` commands run | 0.000 | 0.000 |

Per task (nomem / control, context processed):

- paramiko-session1: 1.00
- paramiko-session2: 0.97
- paramiko-session3: 1.22
- paramiko-session4: 0.94

# Context Arbor A/B — suite code-session (paramiko), model sonnet: arbor vs nomem

4 tasks, 16 paired runs (nomem vs arbor); 0 run(s) errored/timed out and are excluded.

Effect = arbor / nomem (geometric mean over tasks; 95% bootstrap interval over tasks). Below 1.00 means `arbor` used less.

| metric | effect | 95% interval | tasks lower | sign-test p | verdict |
|---|---|---|---|---|---|
| Context processed | 1.04 (+4%) | 0.88 – 1.25 | 2/4 | 1.00 | no significant difference |
| Cost, steady state | 1.17 (+17%) | 0.99 – 1.41 | 1/4 | 0.62 | no significant difference |
| Cost as billed in these runs (cache luck) | 1.17 (+17%) | 1.03 – 1.38 | 0/4 | 0.12 | more |
| Model calls (turns) | 0.96 (-4%) | 0.82 – 1.13 | 3/4 | 0.62 | no significant difference |
| Tool output entering context | 1.41 (+41%) | 1.00 – 2.05 | 1/4 | 0.62 | more |
| Output tokens | 1.07 (+7%) | 0.89 – 1.26 | 1/4 | 0.62 | no significant difference |
| Time | 1.06 (+6%) | 0.90 – 1.25 | 1/4 | 0.62 | no significant difference |

Accuracy (task score 0–1): nomem 0.91, arbor 1.00; difference +0.09 (95% interval -0.01 – +0.29) → no significant difference.

| mean per run | nomem | arbor |
|---|---|---|
| Context processed | 140,702 | 148,929 |
| Cost, steady state | 28,636 | 34,042 |
| Cost as billed in these runs (cache luck) | 0.114 | 0.135 |
| Model calls (turns) | 6.438 | 6.250 |
| Tool output entering context | 5,662 | 8,102 |
| Output tokens | 3,182 | 3,481 |
| Time | 32 | 34 |
| Context at the first turn | 14,144 | 14,687 |
| `arbor.py` commands run | 0.000 | 0.000 |

Adoption: 0 of 16 sessions (0%).

Per task (arbor / nomem, context processed):

- paramiko-session1: 1.23
- paramiko-session2: 0.89
- paramiko-session3: 0.94
- paramiko-session4: 1.16
