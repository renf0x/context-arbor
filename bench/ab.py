#!/usr/bin/env python3
"""A/B benchmark: does installing Context Arbor change what a real Claude Code session spends?

    python bench/ab.py plan   --suite code --reps 3
    python bench/ab.py run    --suite code --reps 3 --model sonnet --budget 20
    python bench/ab.py report --suite code --model sonnet

Each job is one headless `claude -p` session in a fresh copy of the project (see harness.py).
Results are appended to bench/results/<suite>-<package>.jsonl, so an interrupted run resumes
where it stopped and a report can be rebuilt at any time. This tool calls a model; Context
Arbor itself never does, and this directory is not part of what `install.py` ships.
"""
from __future__ import annotations

import argparse
import json
import random
import sys
import tempfile
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import analyze  # noqa: E402
import harness  # noqa: E402
import suites  # noqa: E402

RESULTS = HERE / "results"
RAW = HERE / "_raw"


def make_tasks(suite: str, package: str) -> list[suites.Task]:
    with tempfile.TemporaryDirectory() as tmp:
        ref = Path(tmp)
        if suite.startswith("code"):
            suites.copy_package(package, ref)
        return suites.SUITES[suite](ref, package)


def plan_jobs(args, tasks: list[suites.Task]) -> list[harness.Job]:
    chosen = [t for t in tasks if not args.tasks or any(s in t.id for s in args.tasks.split(","))]
    rng = random.Random(args.seed)
    blocks = [(t, rep) for t in chosen for rep in range(1, args.reps + 1)]
    rng.shuffle(blocks)
    jobs = []
    for task, rep in blocks:  # arms interleaved, order inside a block randomised
        arms = list(args.arms.split(","))
        rng.shuffle(arms)
        jobs += [harness.Job(args.suite, task, arm, rep, args.model) for arm in arms]
    return jobs


def results_path(args) -> Path:
    return RESULTS / f"{args.suite}-{args.package}.jsonl"


def done_ids(path: Path, retry_failed: bool, targets: dict[str, str]) -> set[str]:
    """Jobs that already have a record for the same target (a task id whose target changed is not done)."""
    if not path.exists():
        return set()
    ids = set()
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            row = json.loads(line)
            if row.get("target") != targets.get(row["task"]):
                continue
            if row.get("valid") or not retry_failed:
                ids.add(row["job"])
    return ids


def cmd_plan(args) -> int:
    tasks = make_tasks(args.suite, args.package)
    jobs = plan_jobs(args, tasks)
    skip = done_ids(results_path(args), args.retry_failed, {t.id: t.meta.get("target") for t in tasks})
    todo = [j for j in jobs if j.id not in skip]
    print(f"{len(tasks)} tasks in suite {args.suite!r}; {len(jobs)} jobs planned, {len(todo)} still to run")
    for t in tasks:
        print(f"  {t.id:26} {t.scorer:10} {t.meta.get('target')}")
    return 0


def cmd_run(args) -> int:
    tasks = make_tasks(args.suite, args.package)
    jobs = plan_jobs(args, tasks)
    path = results_path(args)
    path.parent.mkdir(parents=True, exist_ok=True)
    skip = done_ids(path, args.retry_failed, {t.id: t.meta.get("target") for t in tasks})
    todo = [j for j in jobs if j.id not in skip]
    print(f"{len(todo)} jobs to run ({len(jobs) - len(todo)} already done), model={args.model}, "
          f"budget=${args.budget:.2f}, workers={args.workers}", flush=True)
    work = Path(args.work or Path(tempfile.gettempdir()) / "arbor-bench")
    lock = threading.Lock()
    state = {"spent": 0.0, "n": 0, "stop": False}

    def one(job: harness.Job):
        if state["stop"]:
            return None
        record = harness.run_job(job, work, RAW, args.package, args.cap, args.effort, args.keep)
        record["package_version"] = args.package_version
        record["target"] = job.task.meta.get("target")
        with lock:
            with path.open("a", encoding="utf-8") as fh:
                fh.write(json.dumps(record, ensure_ascii=False) + "\n")
            state["spent"] += record.get("cost_usd", 0.0)
            state["n"] += 1
            if state["spent"] >= args.budget:
                state["stop"] = True
            flag = "ok " if record.get("valid") else "ERR"
            print(f"[{state['n']}/{len(todo)}] {flag} {job.arm:7} {job.task.id:24} rep{job.rep} "
                  f"score={record.get('score', 0):.2f} turns={record.get('turns', '-')} "
                  f"ctx={record.get('context_processed', 0) / 1000:.0f}k "
                  f"cost=${record.get('cost_usd', 0):.3f} spent=${state['spent']:.2f} "
                  f"{record.get('subtype', '')}", flush=True)
        return record

    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        for future in as_completed([pool.submit(one, j) for j in todo]):
            future.result()
    if state["stop"]:
        print(f"stopped: budget ${args.budget:.2f} reached (spent ${state['spent']:.2f}); "
              f"re-run the same command to continue", flush=True)
    return 0


def cmd_resummarize(args) -> int:
    """Recompute every measurement from the saved raw transcripts (scores are kept)."""
    path = results_path(args)
    rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    keep = {"answer", "score", "valid", "final_text", "stderr"}
    changed = 0
    for row in rows:
        if not row.get("valid"):
            continue  # a failed attempt has no trustworthy transcript
        raw = RAW / (row["job"].replace("/", "_") + ".jsonl")
        if not raw.exists():
            continue
        fresh = harness.summarize(raw.read_text(encoding="utf-8").splitlines())
        for key, val in fresh.items():
            if key not in keep and row.get(key) != val:
                row[key] = val
                changed += 1
    path.with_suffix(".jsonl.bak").write_text(path.read_text(encoding="utf-8"), encoding="utf-8")
    path.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows), encoding="utf-8")
    print(f"{len(rows)} records, {changed} fields updated")
    return 0


def cmd_report(args) -> int:
    path = results_path(args)
    if not path.exists():
        print(f"no results at {path}", file=sys.stderr)
        return 1
    rows = analyze.load(path, args.model)
    title = f"Context Arbor A/B — suite {args.suite} ({args.package}), model {args.model or 'all'}"
    arms = {r["arm"] for r in rows}
    comparisons = [(b, o) for b, o in (("control", "arbor"), ("control", "nomem"), ("nomem", "arbor"), ("arbor", "jev"), ("control", "jev"))
                   if b in arms and o in arms]
    summaries = [analyze.summarize_all(rows, b, o) for b, o in comparisons]
    md = "\n".join(analyze.render_markdown(s, f"{title}: {s['other']} vs {s['base']}") for s in summaries)
    stem = f"report-{args.suite}-{args.package}-{args.model or 'all'}"
    (RESULTS / f"{stem}.md").write_text(md, encoding="utf-8")
    (RESULTS / f"{stem}.html").write_text(
        analyze.render_html(summaries, title, args.note or ""), encoding="utf-8")
    print(md)
    print(f"written: {RESULTS / (stem + '.html')}")
    return 0


def main(argv: list[str] | None = None) -> int:
    for stream in (sys.stdout, sys.stderr):  # Windows consoles default to a legacy code page
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")
    parser =argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="cmd", required=True)
    for name, fn in (("plan", cmd_plan), ("run", cmd_run), ("report", cmd_report),
                     ("resummarize", cmd_resummarize)):
        p = sub.add_parser(name)
        p.set_defaults(fn=fn)
        p.add_argument("--suite", default="code", choices=sorted(suites.SUITES))
        p.add_argument("--package", default="", help="library for the code suite (default paramiko)")
        p.add_argument("--model", default="sonnet")
        p.add_argument("--tasks", default="", help="comma-separated substrings of task ids")
        p.add_argument("--arms", default="control,nomem,arbor")
        p.add_argument("--reps", type=int, default=3)
        p.add_argument("--seed", type=int, default=1)
        p.add_argument("--retry-failed", action="store_true")
        if name == "run":
            p.add_argument("--budget", type=float, default=15.0, help="stop starting jobs after this many USD (list price)")
            p.add_argument("--cap", type=float, default=2.0, help="per-run --max-budget-usd")
            p.add_argument("--workers", type=int, default=2)
            p.add_argument("--effort", default="medium")
            p.add_argument("--work", default="")
            p.add_argument("--keep", action="store_true", help="keep the working directories")
        if name == "report":
            p.add_argument("--note", default="")
    args = parser.parse_args(argv)
    args.package = args.package or ("paramiko" if args.suite.startswith("code") else args.suite)
    try:
        args.package_version = _package_version(args.package)
    except Exception:  # noqa: BLE001 - a missing version must not stop a run
        args.package_version = ""
    return args.fn(args)


def _package_version(package: str) -> str:
    import importlib.metadata
    return importlib.metadata.version(package)


if __name__ == "__main__":
    raise SystemExit(main())
