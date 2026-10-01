# A/B benchmark: does installing Context Arbor change what a real session spends?

This directory is a development tool. It calls a model (`claude -p`); Context Arbor itself never
does, and `install.py` does not ship this directory. Nothing here is needed to use Arbor.

## Question

Same project, same task, same model, same settings — once **without** Arbor and once **with** it
installed the documented way. Does the session read less, cost less, answer worse or better?

## Arms

| arm | what is in the project |
|---|---|
| `control` | the plain project |
| `nomem` | control + `.claude/settings.local.json` with `autoMemoryEnabled: false`, nothing else |
| `arbor` | `arbor.py` copied in, `python arbor.py init --agents claude`, code index built once |

`nomem` exists because Arbor's installer switches Claude Code's built-in Auto Memory off. That
saves context (about 3.4k tokens of system prompt) whether or not Arbor is installed, so without
this arm a saving from that switch would be credited to Arbor. Three comparisons are reported:
`arbor` vs `control` (what installing Arbor does), `nomem` vs `control` (the switch alone) and
`arbor` vs `nomem` (what Arbor itself adds).

## Isolation

* Every job is a fresh headless session (`--no-session-persistence`) in a fresh copy of the
  fixture, in a temporary directory outside this repository. No history, no earlier run, nothing
  from the session that wrote this benchmark can reach it.
* The fixtures are **not** this repository: the code suites use an installed third-party library
  (`paramiko`); the memory suites use a made-up project generated from a seeded RNG, which no
  model has seen.
* User settings, skills, MCP servers and sub-agents are switched off for every arm
  (`--setting-sources project,local --disable-slash-commands --strict-mcp-config`, tools limited to
  `Bash,Read,Grep,Glob,Edit,Write`). The prompt never mentions Arbor; the agent learns about it only
  from the `CLAUDE.md` block the installer wrote, as a real user's agent would.
* Arms are interleaved and their order inside each repetition is random (seeded).

## Tasks and scoring

Questions have one machine-computed correct answer, derived from the fixture with `ast`, never
typed in by hand; scorers are unit-tested (`tests/test_bench.py`). Suites:

* `code` — class location, parameter defaults, callers of a helper, subclasses, method count,
  exceptions raised, and a rename across files checked on the resulting tree. 2–3 targets per kind.
* `code-session` — six of those questions in one session, so the context built on the first is
  re-read on the rest.
* `memory`, `memory-large` — questions about a made-up project's written history (current value,
  what triggered a change, what replaced what, counts, and questions with no recorded answer).
  `control`/`nomem` get the history as one file per entry (the usual ADR layout) and a line in
  `CLAUDE.md`; `arbor` gets the same entries in Arbor's vault, rotated as a real vault would be.

## Measures

`context_processed` = input + cache-write + cache-read tokens summed over turns: what the model
had to read. It does not depend on cache state. `cost_steady` prices the same tokens in the
steady state a returning user is in (first-turn prefix already cached; cache write 1.25×, cache
read 0.1×, output 5×). The dollar figure from the API is reported too, but it depends on whether a
run happened to find its prefix cached, so it is not used for a verdict. Also: turns, tool output
that entered the context (estimated), output tokens, wall time, accuracy (0–1), and how often the
agent actually ran `arbor.py`.

## Decision rule (written before any result was looked at)

Effect = arbor ÷ control per task (geometric mean over its repetitions); overall = geometric mean
over tasks with a 95% bootstrap interval that resamples tasks and repetitions (10,000 draws, fixed
seed). A metric is **less** only if the whole interval is below 1, **more** only if it is above 1;
otherwise it is reported as *no significant difference*, which is not the same as *no effect*. For
accuracy the same rule applies to the difference around 0. Runs that error or time out are
listed and excluded from the pairs they belong to.

## Running

```sh
python bench/ab.py plan   --suite code --reps 3
python bench/ab.py run    --suite code --reps 3 --model sonnet --budget 12
python bench/ab.py resummarize --suite code        # re-derive measures from bench/_raw
python bench/ab.py report --suite code --model sonnet
```

Results are appended to `bench/results/<suite>-<package>.jsonl` (one line per session), so an
interrupted run resumes; raw transcripts go to `bench/_raw/` (git-ignored). Sessions use the
subscription's quota; the dollar figures are list-price equivalents.

## Limits

* One model family, one library, one made-up project: the result says what happened there.
* Short tasks are dominated by the fixed system prompt; long real sessions are not tested, only
  approximated by the six-question sessions. `/clear` + restore and the hooks' effect on a session
  that runs for hours are not measured.
* Arbor's `arbor.py` sits in the project tree of the `arbor` arm, as its installer puts it there.
* Sonnet answers these questions correctly almost always, so accuracy has little room to improve.
