"""Memory suite: a made-up project ("Meridian") with a written history of decisions, bugs and
investigations, and questions whose answers exist only in that history.

The project is fictional and its values are drawn from a seeded RNG, so no model has seen it
and none can answer from training data: an answer is right only if it was found in the notes.
The same history is written twice, field for field:

  * control / nomem: one file per entry under docs/decisions, docs/bugs, docs/investigations
    (the usual ADR layout), plus one line in CLAUDE.md saying where they are;
  * arbor: Context Arbor's vault (memory/decisions.md, bugs.md, investigations.md), rotated the
    way `arbor memory rotate` rotates when a journal outgrows its cap.

Two sizes: `memory` (about 60 entries, ~9k tokens) and `memory-large` (about 230 entries).
"""
from __future__ import annotations

import datetime
import random
import re
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path

COMPONENTS = ["rate quoting", "label printing", "tracking sync", "webhook delivery", "address validation",
              "customs forms", "returns portal", "billing export", "carrier onboarding", "audit log",
              "session auth", "search index", "invoice mailer", "pickup scheduling", "fraud screening",
              "inventory feed", "notification hub", "partner gateway", "report builder", "sandbox mode"]
NUMERIC = [("retry limit", "attempts", 2, 9), ("cache TTL", "seconds", 30, 900),
           ("request timeout", "ms", 800, 9000), ("page size", "items", 20, 500),
           ("batch size", "records", 50, 2000), ("log retention", "days", 7, 365),
           ("token lifetime", "minutes", 5, 240), ("rate limit", "requests per minute", 30, 1200)]
CHOICE = [("hash algorithm", ["blake2b", "sha3-256", "argon2id", "scrypt"]),
          ("queue backend", ["RabbitMQ", "NATS", "SQS", "Redis Streams"]),
          ("serialization format", ["MessagePack", "Avro", "Protobuf", "CBOR"]),
          ("storage engine", ["SQLite", "Postgres", "DuckDB", "LMDB"])]
SYMPTOMS = ["requests failed during the morning peak", "duplicate records appeared after a retry",
            "stale data was served to customers", "the nightly job ran past its window",
            "support saw intermittent 502 responses", "memory grew until the worker was killed"]
RATIONALES = ["Matches the default agreed with the carrier during onboarding.",
              "Keeps behaviour the same as the previous internal tool.",
              "Chosen as the smallest value that passed the acceptance tests.",
              "Agreed in the architecture review; revisit if traffic grows.",
              "Follows the vendor's published recommendation."]


@dataclass
class Entry:
    id: str
    kind: str  # DEC BUG INV
    date: str
    title: str
    status: str
    fields: list[tuple[str, str]]
    relations: list[tuple[str, str]] = field(default_factory=list)
    topic: tuple[str, str] = ("", "")


@dataclass
class History:
    entries: list[Entry]
    topics: list[dict]
    absent: list[tuple[str, str]]


def _fmt(value, unit) -> str:
    return f"{value} {unit}".strip()


def build_history(seed: int, topics: int) -> History:
    rng = random.Random(seed)
    pairs = [(c, p) for c in COMPONENTS for p in [n[0] for n in NUMERIC] + [n[0] for n in CHOICE]]
    rng.shuffle(pairs)
    chosen, absent = pairs[:topics], pairs[topics:topics + 4]
    specs = {n[0]: n for n in NUMERIC}
    specs.update({n[0]: n for n in CHOICE})
    entries: list[Entry] = []
    info: list[dict] = []
    counters: dict[str, int] = {}
    day = [0]

    def new_id(kind: str) -> tuple[str, str]:
        day[0] += rng.choice([0, 1, 1, 2, 3])
        date = (datetime.date(2024, 1, 8) + datetime.timedelta(days=day[0])).isoformat()
        key = f"{kind}{date}"
        counters[key] = counters.get(key, 0) + 1
        return f"{kind}-{date.replace('-', '')}-{counters[key]:03d}", date

    def draw(spec, avoid=None):
        if len(spec) == 4:
            _n, unit, lo, hi = spec
            while True:
                value = rng.randint(lo, hi)
                if value != avoid:
                    return str(value), unit
        _n, options = spec
        return rng.choice([o for o in options if o != avoid]), ""

    for component, param in chosen:
        spec = specs[param]
        v1, unit = draw(spec)
        first_id, first_date = new_id("DEC")
        two = rng.random() < 0.65
        first = Entry(first_id, "DEC", first_date, f"Set {component} {param} to {_fmt(v1, unit)}",
                      "superseded" if two else "active",
                      [("Decision", f"The {param} of {component} is {_fmt(v1, unit)}."),
                       ("Reason", rng.choice(RATIONALES))], topic=(component, param))
        entries.append(first)
        topic = {"component": component, "param": param, "unit": unit, "v1": v1, "dec1": first_id, "v2": None}
        if two:
            v2, _ = draw(spec, avoid=v1)
            trigger_kind = rng.choice(["BUG", "INV"])
            trig_id, trig_date = new_id(trigger_kind)
            if trigger_kind == "BUG":
                trigger = Entry(trig_id, "BUG", trig_date, f"{component.capitalize()}: {rng.choice(SYMPTOMS)}",
                                "resolved",
                                [("Symptom", f"In {component}, {rng.choice(SYMPTOMS)}."),
                                 ("Cause", f"The {param} of {_fmt(v1, unit)} set in {first_id} did not fit real load."),
                                 ("Resolution", f"Changed the {param} to {_fmt(v2, unit)}."),
                                 ("Regression test", f"test_{component.replace(' ', '_')}_{param.replace(' ', '_')}")],
                                [("caused-by", first_id)], (component, param))
            else:
                p95a, p95b = rng.randint(180, 900), rng.randint(60, 179)
                trigger = Entry(trig_id, "INV", trig_date, f"Measure {component} {param} under load", "closed",
                                [("Question", f"Is a {param} of {_fmt(v1, unit)} right for {component}?"),
                                 ("Findings", f"At {_fmt(v1, unit)} the p95 latency was {p95a} ms; "
                                              f"at {_fmt(v2, unit)} it was {p95b} ms."),
                                 ("Conclusion", f"Use {_fmt(v2, unit)}.")],
                                [("relates-to", first_id)], (component, param))
            entries.append(trigger)
            second_id, second_date = new_id("DEC")
            entries.append(Entry(
                second_id, "DEC", second_date, f"Change {component} {param} to {_fmt(v2, unit)}", "active",
                [("Decision", f"The {param} of {component} is now {_fmt(v2, unit)}."),
                 ("Reason", f"Follows {trig_id}.")],
                [("supersedes", first_id), ("caused-by" if trigger_kind == "BUG" else "relates-to", trig_id)],
                (component, param)))
            topic.update(v2=v2, trigger=trig_id, trigger_kind=trigger_kind, dec2=second_id)
        info.append(topic)
    return History(entries, info, absent)


# ---------------------------------------------------------------- rendering

def entry_block(e: Entry) -> str:
    fields = [("Status", e.status), ("Date", e.date), *e.fields,
              ("Relations", ", ".join(f"{t}:{i}" for t, i in e.relations)), ("Links", "")]
    return f"## {e.id} {e.title}\n\n" + "\n".join(f"- {k}: {v}".rstrip() for k, v in fields) + "\n"


def slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")[:50]


FOLDERS = {"DEC": "decisions", "BUG": "bugs", "INV": "investigations"}
CONTROL_POINTER = ("# Project notes\n\nThe written history of this project lives in `docs/`: one file per "
                   "entry in `docs/decisions/`, `docs/bugs/` and `docs/investigations/`.\n")


def write_docs(proj: Path, hist: History) -> None:
    for e in hist.entries:
        folder = proj / "docs" / FOLDERS[e.kind]
        folder.mkdir(parents=True, exist_ok=True)
        (folder / f"{e.id}-{slug(e.title)}.md").write_text(entry_block(e), encoding="utf-8")
    (proj / "CLAUDE.md").write_text(CONTROL_POINTER, encoding="utf-8")


def write_stub_code(proj: Path) -> None:
    pkg = proj / "meridian"
    pkg.mkdir(parents=True, exist_ok=True)
    (pkg / "__init__.py").write_text('"""Meridian: a rate-shopping and shipping API."""\n', encoding="utf-8")
    for name in ("quoting", "labels", "tracking", "webhooks", "audit", "auth"):
        (pkg / f"{name}.py").write_text(
            f'"""{name.capitalize()} module of Meridian."""\n\n\ndef handle(request):\n'
            f'    """Entry point for {name}; behaviour is described in the project history."""\n'
            f'    return {{"module": "{name}", "ok": True}}\n', encoding="utf-8")


def write_vault(proj: Path, hist: History) -> list[str]:
    """Fill Context Arbor's vault with the history, then rotate the way a real vault would.
    Returns the `memory check` complaints (there should be none)."""
    memory = proj / "memory"
    headers = {"DEC": "# Decision Log", "BUG": "# Bug Log", "INV": "# Investigation Log"}
    names = {"DEC": "decisions.md", "BUG": "bugs.md", "INV": "investigations.md"}
    for kind, header in headers.items():
        blocks = [entry_block(e) for e in reversed(hist.entries) if e.kind == kind]  # newest first
        (memory / names[kind]).write_text(header + "\n\n" + "\n".join(blocks), encoding="utf-8")
    run = lambda *a: subprocess.run([sys.executable, "arbor.py", *a], cwd=proj, capture_output=True, text=True, timeout=120)
    run("memory", "rotate")
    check = run("memory", "check")
    return [] if "OK" in check.stdout else check.stdout.splitlines()


# ---------------------------------------------------------------- questions

def _tasks(hist: History, suite: str, seed: int):
    from suites import FOOTER, Task  # local import: suites imports this module at the bottom
    rng = random.Random(seed + 1)
    lead = ("This project keeps a written history of its decisions, bugs and investigations. Answer from "
            "that history, and if the answer is not recorded there, say so instead of guessing. ")
    two = [t for t in hist.topics if t["v2"] is not None]
    rng.shuffle(two)
    tasks = []

    def add(kind, i, question, expected, scorer, **meta):
        tasks.append(Task(f"{suite}-{kind}{i}", kind, lead + question + FOOTER, expected, scorer,
                          {"package": suite, **meta}))

    for i, t in enumerate(two[:5], 1):
        add("current", i, f"What is the {t['param']} of {t['component']} in force now? Answer as "
            f'{{"value": ...}} (just the value, without the unit).', t["v2"], "value", target=t["dec2"])
    for i, t in enumerate(two[5:9], 1):
        add("cause", i, f"The {t['param']} of {t['component']} was changed at some point. Which bug or "
            f'investigation triggered the change? Answer as {{"id": "<entry id>"}}.', t["trigger"], "id",
            target=t["trigger"])
    for i, t in enumerate(two[9:12], 1):
        add("replaced", i, f"Which decision replaced {t['dec1']}? Answer as {{\"id\": \"<entry id>\"}}.",
            t["dec2"], "id", target=t["dec1"])
    for i, t in enumerate(two[12:15], 1):
        add("supersedes", i, f"Which earlier decision did {t['dec2']} supersede? Answer as "
            f'{{"id": "<entry id>"}}.', t["dec1"], "id", target=t["dec2"])
    by_component: dict[str, int] = {}
    for e in hist.entries:
        if e.kind == "DEC":
            by_component[e.topic[0]] = by_component.get(e.topic[0], 0) + 1
    counts = sorted(by_component.items(), key=lambda kv: (-kv[1], kv[0]))
    for i, (component, n) in enumerate(counts[:2], 1):
        add("count", i, f"How many decisions in the history concern {component}? Count every decision, "
            f"including ones that were later superseded. Answer as a JSON integer.", n, "int", target=component)
    for i, (component, param) in enumerate(hist.absent[:2], 1):
        add("absent", i, f"What was decided about the {param} of {component}? Answer as "
            f'{{"value": ...}}, or {{"value": null}} if nothing is recorded.', None, "absent",
            target=f"{component}/{param}")
    return tasks


def _make(suite: str, topics: int, seed: int):
    def tasks(root: Path, package: str, seed: int = seed):
        return _tasks(build_history(seed, topics), suite, seed)
    return tasks


SPECS = {"memory": (24, 20260930), "memory-large": (90, 20260930)}


def history_for(suite: str) -> History:
    topics, seed = SPECS[suite]
    return build_history(seed, topics)


TASK_BUILDERS = {name: _make(name, topics, seed) for name, (topics, seed) in SPECS.items()}
