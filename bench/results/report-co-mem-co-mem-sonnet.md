# Context Arbor A/B — suite co-mem (co-mem), model sonnet: arbor vs control

6 tasks, 18 paired runs (control vs arbor); 0 run(s) errored/timed out and are excluded.

Effect = arbor / control (geometric mean over tasks; 95% bootstrap interval over tasks). Below 1.00 means `arbor` used less.

| metric | effect | 95% interval | tasks lower | sign-test p | verdict |
|---|---|---|---|---|---|
| Context processed | 0.84 (-16%) | 0.49 – 1.51 | 3/6 | 1.00 | no significant difference |
| Cost, steady state | 0.83 (-17%) | 0.45 – 1.54 | 4/6 | 0.69 | no significant difference |
| Cost as billed in these runs (cache luck) | 0.64 (-36%) | 0.42 – 1.00 | 5/6 | 0.22 | less |
| Model calls (turns) | 1.00 (+0%) | 0.62 – 1.64 | 3/6 | 1.00 | no significant difference |
| Tool output entering context | 0.91 (-9%) | 0.45 – 1.86 | 3/6 | 1.00 | no significant difference |
| Output tokens | 0.99 (-1%) | 0.66 – 1.53 | 3/6 | 1.00 | no significant difference |
| Time | 0.79 (-21%) | 0.59 – 1.05 | 5/6 | 0.22 | no significant difference |

Accuracy (task score 0–1): control 0.97, arbor 0.97; difference +0.00 (95% interval -0.11 – +0.11) → no significant difference.

| mean per run | control | arbor |
|---|---|---|
| Context processed | 74,278 | 73,911 |
| Cost, steady state | 14,066 | 14,500 |
| Cost as billed in these runs (cache luck) | 0.073 | 0.055 |
| Model calls (turns) | 3.667 | 4.056 |
| Tool output entering context | 2,840 | 3,227 |
| Output tokens | 969 | 968 |
| Time | 24 | 18 |
| Context at the first turn | 17,933 | 14,288 |
| `arbor.py` commands run | 0.000 | 2.222 |

Adoption: 18 of 18 sessions (100%).

Per task (arbor / control, context processed):

- mem-blender: 0.50
- mem-collisions: 2.64
- mem-dish: 1.24
- mem-headless: 0.38
- mem-planes: 1.15
- mem-quality: 0.51

# Context Arbor A/B — suite co-mem (co-mem), model sonnet: jev vs arbor

6 tasks, 18 paired runs (arbor vs jev); 0 run(s) errored/timed out and are excluded.

Effect = jev / arbor (geometric mean over tasks; 95% bootstrap interval over tasks). Below 1.00 means `jev` used less.

| metric | effect | 95% interval | tasks lower | sign-test p | verdict |
|---|---|---|---|---|---|
| Context processed | 0.55 (-45%) | 0.32 – 0.89 | 4/6 | 0.69 | less |
| Cost, steady state | 0.40 (-60%) | 0.20 – 0.75 | 5/6 | 0.22 | less |
| Cost as billed in these runs (cache luck) | 0.61 (-39%) | 0.39 – 0.92 | 5/6 | 0.22 | less |
| Model calls (turns) | 0.58 (-42%) | 0.36 – 0.90 | 4/6 | 0.69 | less |
| Tool output entering context | 0.26 (-74%) | 0.09 – 0.65 | 5/5 | 0.06 | less |
| Output tokens | 0.61 (-39%) | 0.35 – 0.99 | 5/6 | 0.22 | less |
| Time | 0.81 (-19%) | 0.55 – 1.14 | 4/6 | 0.69 | no significant difference |

Accuracy (task score 0–1): arbor 0.97, jev 1.00; difference +0.03 (95% interval +0.00 – +0.11) → no significant difference.

| mean per run | arbor | jev |
|---|---|---|
| Context processed | 73,911 | 40,308 |
| Cost, steady state | 14,500 | 6,205 |
| Cost as billed in these runs (cache luck) | 0.055 | 0.032 |
| Model calls (turns) | 4.056 | 2.444 |
| Tool output entering context | 3,227 | 801 |
| Output tokens | 968 | 645 |
| Time | 18 | 14 |
| Context at the first turn | 14,288 | 15,177 |
| `arbor.py` commands run | 2.222 | 0.500 |

Per task (jev / arbor, context processed):

- mem-blender: 0.68
- mem-collisions: 0.36
- mem-dish: 0.20
- mem-headless: 1.04
- mem-planes: 0.53
- mem-quality: 1.00

# Context Arbor A/B — suite co-mem (co-mem), model sonnet: jev vs control

6 tasks, 18 paired runs (control vs jev); 0 run(s) errored/timed out and are excluded.

Effect = jev / control (geometric mean over tasks; 95% bootstrap interval over tasks). Below 1.00 means `jev` used less.

| metric | effect | 95% interval | tasks lower | sign-test p | verdict |
|---|---|---|---|---|---|
| Context processed | 0.46 (-54%) | 0.31 – 0.72 | 6/6 | 0.03 | less |
| Cost, steady state | 0.33 (-67%) | 0.18 – 0.60 | 6/6 | 0.03 | less |
| Cost as billed in these runs (cache luck) | 0.39 (-61%) | 0.28 – 0.56 | 6/6 | 0.03 | less |
| Model calls (turns) | 0.59 (-41%) | 0.41 – 0.86 | 5/6 | 0.22 | less |
| Tool output entering context | 0.22 (-78%) | 0.07 – 0.69 | 4/5 | 0.38 | less |
| Output tokens | 0.60 (-40%) | 0.40 – 0.84 | 6/6 | 0.03 | less |
| Time | 0.64 (-36%) | 0.47 – 0.83 | 6/6 | 0.03 | less |

Accuracy (task score 0–1): control 0.97, jev 1.00; difference +0.03 (95% interval +0.00 – +0.11) → no significant difference.

| mean per run | control | jev |
|---|---|---|
| Context processed | 74,278 | 40,308 |
| Cost, steady state | 14,066 | 6,205 |
| Cost as billed in these runs (cache luck) | 0.073 | 0.032 |
| Model calls (turns) | 3.667 | 2.444 |
| Tool output entering context | 2,840 | 801 |
| Output tokens | 969 | 645 |
| Time | 24 | 14 |
| Context at the first turn | 17,933 | 15,177 |
| `arbor.py` commands run | 0.000 | 0.500 |

Per task (jev / control, context processed):

- mem-blender: 0.34
- mem-collisions: 0.94
- mem-dish: 0.25
- mem-headless: 0.39
- mem-planes: 0.60
- mem-quality: 0.51
