"""Paired statistics and the report (markdown + one static HTML page with plain charts).

Design, fixed before any result was looked at:
  * unit of analysis = task; each task is run `reps` times per arm, arms interleaved in random order
  * effect = arbor / control, per task the geometric mean over its repetitions
  * overall effect = geometric mean over tasks, with a 95% bootstrap interval that resamples
    tasks (and, inside a task, its repetitions) -- 10,000 draws, fixed seed
  * verdict per metric: "less" only if the whole interval is below 1, "more" only if it is above 1,
    otherwise "no significant difference" (which is not the same as "no effect")
  * a run that errored, timed out or hit its budget cap is reported, and excluded from the pairs
    it would have belonged to
"""
from __future__ import annotations

import html
import json
import math
import random
from pathlib import Path

METRICS = [  # key, label, unit, lower is better
    ("context_processed", "Context processed", "tokens", True),
    ("cost_steady", "Cost, steady state", "input-token equiv.", True),
    ("cost_usd", "Cost as billed in these runs (cache luck)", "USD", True),
    ("turns", "Model calls (turns)", "", True),
    ("tool_result_tokens_est", "Tool output entering context", "tokens (est.)", True),
    ("output", "Output tokens", "tokens", True),
    ("duration_s", "Time", "s", True),
]
BOOTSTRAP = 10_000


def load(path: Path, model: str | None = None) -> list[dict]:
    rows = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            rows.append(json.loads(line))
    if model:
        rows = [r for r in rows if r.get("model") == model]
    latest: dict[str, dict] = {}
    for row in rows:  # a re-run of the same job replaces the earlier record
        latest[row["job"]] = row
    return list(latest.values())


def value(row: dict, key: str) -> float:
    if key == "output":
        return float(row.get("tokens", {}).get("output", 0))
    return float(row.get(key, 0) or 0)


def pair_up(rows: list[dict], base: str = "control", other: str = "arbor") -> dict[str, dict[int, tuple[dict, dict]]]:
    """task -> rep -> (base, other) for reps where both arms produced a valid run."""
    by: dict[tuple, dict] = {}
    for row in rows:
        if row.get("valid"):
            by[(row["task"], row["rep"], row["arm"])] = row
    paired: dict[str, dict[int, tuple[dict, dict]]] = {}
    for (task, rep, arm), row in by.items():
        if arm == base and (task, rep, other) in by:
            paired.setdefault(task, {})[rep] = (row, by[(task, rep, other)])
    return paired


def _geomean(xs: list[float]) -> float:
    return math.exp(sum(math.log(x) for x in xs) / len(xs))


def ratio_effect(paired: dict, key: str, seed: int = 7) -> dict | None:
    """Geometric-mean ratio arbor/control with a cluster bootstrap interval."""
    per_task: dict[str, list[float]] = {}
    for task, reps in paired.items():
        ratios = [value(b, key) / value(a, key) for a, b in reps.values() if value(a, key) > 0 and value(b, key) > 0]
        if ratios:
            per_task[task] = ratios
    if not per_task:
        return None
    tasks = sorted(per_task)
    point = _geomean([_geomean(per_task[t]) for t in tasks])
    rng = random.Random(seed)
    draws = []
    for _ in range(BOOTSTRAP):
        chosen = [rng.choice(tasks) for _ in tasks]
        draws.append(_geomean([_geomean([rng.choice(per_task[t]) for _ in per_task[t]]) for t in chosen]))
    draws.sort()
    lo, hi = draws[int(0.025 * BOOTSTRAP)], draws[int(0.975 * BOOTSTRAP) - 1]
    below = sum(1 for t in tasks if _geomean(per_task[t]) < 1)
    return {"ratio": point, "lo": lo, "hi": hi, "tasks": len(tasks), "below": below,
            "runs": sum(len(v) for v in per_task.values()), "sign_p": sign_test(below, len(tasks)),
            "per_task": {t: _geomean(per_task[t]) for t in tasks}}


def sign_test(below: int, n: int) -> float:
    """Two-sided exact sign test on the number of tasks where arbor is lower."""
    k = min(below, n - below)
    return min(1.0, 2 * sum(math.comb(n, i) for i in range(k + 1)) / 2 ** n)


def score_effect(paired: dict, seed: int = 11) -> dict | None:
    """Mean task score per arm and the paired difference (arbor - control) with a bootstrap interval."""
    diffs: dict[str, list[float]] = {}
    for task, reps in paired.items():
        diffs[task] = [b.get("score", 0.0) - a.get("score", 0.0) for a, b in reps.values()]
    if not diffs:
        return None
    tasks = sorted(diffs)
    mean = lambda xs: sum(xs) / len(xs)
    point = mean([mean(diffs[t]) for t in tasks])
    rng = random.Random(seed)
    draws = sorted(mean([mean([rng.choice(diffs[t]) for _ in diffs[t]]) for t in [rng.choice(tasks) for _ in tasks]])
                   for _ in range(BOOTSTRAP))
    control = mean([mean([a.get("score", 0.0) for a, _ in paired[t].values()]) for t in tasks])
    arbor = mean([mean([b.get("score", 0.0) for _, b in paired[t].values()]) for t in tasks])
    return {"control": control, "arbor": arbor, "diff": point, "lo": draws[int(0.025 * BOOTSTRAP)],
            "hi": draws[int(0.975 * BOOTSTRAP) - 1], "tasks": len(tasks)}


def verdict(lo: float, hi: float, lower_is_better: bool = True, center: float = 1.0) -> str:
    if hi < center:
        return "less" if lower_is_better else "worse"
    if lo > center:
        return "more" if lower_is_better else "better"
    return "no significant difference"


def summarize_all(rows: list[dict], base: str = "control", other: str = "arbor") -> dict:
    paired = pair_up(rows, base, other)
    invalid = [r for r in rows if not r.get("valid") and r["arm"] in (base, other)]
    out = {"paired": paired, "invalid": invalid, "metrics": {}, "score": score_effect(paired),
           "rows": len(rows), "tasks": sorted(paired), "base": base, "other": other,
           "adoption": adoption(rows) if other == "arbor" else {}}
    for key, label, unit, _low in METRICS:
        out["metrics"][key] = ratio_effect(paired, key)
    used = {(t, rep) for t, reps in paired.items() for rep in reps}
    out["arm_means"] = {arm: {key: (sum(value(r, key) for r in rows if r["arm"] == arm and r.get("valid") and (r["task"], r["rep"]) in used)
                                    / max(1, sum(1 for r in rows if r["arm"] == arm and r.get("valid") and (r["task"], r["rep"]) in used)))
                              for key, *_ in METRICS + [("first_context", "", "", True), ("arbor_calls", "", "", True)]}
                        for arm in (base, other)}
    return out


def _num(v: float) -> str:
    return f"{v:,.3f}" if abs(v) < 10 else f"{v:,.0f}"


def adoption(rows: list[dict]) -> dict:
    """How often the agent ran `arbor.py` at all, and what those sessions looked like next to the
    same task's sessions in the `nomem` arm. Exploratory: it splits runs by something the agent
    chose, so it describes, and does not estimate an effect."""
    arbor = [r for r in rows if r["arm"] == "arbor" and r.get("valid")]
    if not arbor:
        return {}
    used = [r for r in arbor if r.get("arbor_calls", 0) > 0]
    per_task: dict[str, list[dict]] = {}
    for r in arbor:
        per_task.setdefault(r["task"], []).append(r)
    ref: dict[str, float] = {}
    for r in rows:
        if r["arm"] == "nomem" and r.get("valid"):
            ref.setdefault(r["task"], []).append(r["context_processed"])
    ref = {t: sum(v) / len(v) for t, v in ref.items()}

    def rel(rs: list[dict]) -> float | None:
        vals = [r["context_processed"] / ref[r["task"]] for r in rs if r["task"] in ref]
        return _geomean(vals) if vals else None

    return {"share": len(used) / len(arbor), "runs": len(arbor), "used": len(used),
            "rel_used": rel(used), "rel_unused": rel([r for r in arbor if r not in used]),
            "tasks": {t: sum(1 for r in rs if r.get("arbor_calls", 0) > 0) / len(rs)
                      for t, rs in sorted(per_task.items())}}


def _pct(ratio: float) -> str:
    change = (ratio - 1) * 100
    return f"{change:+.0f}%"


def render_markdown(summary: dict, title: str) -> str:
    base, other = summary["base"], summary["other"]
    lines = [f"# {title}", ""]
    n_pairs = sum(len(v) for v in summary["paired"].values())
    lines += [f"{len(summary['tasks'])} tasks, {n_pairs} paired runs ({base} vs {other}); "
              f"{len(summary['invalid'])} run(s) errored/timed out and are excluded.", "",
              f"Effect = {other} / {base} (geometric mean over tasks; 95% bootstrap interval over tasks). "
              f"Below 1.00 means `{other}` used less.", "",
              "| metric | effect | 95% interval | tasks lower | sign-test p | verdict |",
              "|---|---|---|---|---|---|"]
    for key, label, unit, low in METRICS:
        m = summary["metrics"].get(key)
        if not m:
            continue
        lines.append(f"| {label} | {m['ratio']:.2f} ({_pct(m['ratio'])}) | {m['lo']:.2f} – {m['hi']:.2f} | "
                     f"{m['below']}/{m['tasks']} | {m['sign_p']:.2f} | {verdict(m['lo'], m['hi'], low)} |")
    s = summary["score"]
    if s:
        lines += ["", f"Accuracy (task score 0–1): {base} {s['control']:.2f}, {other} {s['arbor']:.2f}; "
                      f"difference {s['diff']:+.2f} (95% interval {s['lo']:+.2f} – {s['hi']:+.2f}) → "
                      f"{verdict(s['lo'], s['hi'], False, 0.0)}."]
    means = summary["arm_means"]
    lines += ["", f"| mean per run | {base} | {other} |", "|---|---|---|"]
    for key, label, unit, _low in METRICS + [("first_context", "Context at the first turn", "tokens", True),
                                              ("arbor_calls", "`arbor.py` commands run", "", True)]:
        lines.append(f"| {label} | {_num(means[base][key])} | {_num(means[other][key])} |")
    if other == "arbor" and summary.get("adoption"):
        a = summary["adoption"]
        lines += ["", f"Adoption: the agent ran `arbor.py` in {a['used']} of {a['runs']} sessions ({a['share']:.0%}). "
                      f"Context of those sessions vs the same task without Arbor: "
                      f"{a['rel_used']:.2f}×; of the sessions that did not use it: {a['rel_unused']:.2f}× "
                      f"(descriptive, not an effect estimate)." if a["rel_used"] and a["rel_unused"] else
                      f"Adoption: {a['used']} of {a['runs']} sessions ({a['share']:.0%})."]
    lines += ["", f"Per task ({other} / {base}, context processed):", ""]
    m = summary["metrics"].get("context_processed")
    if m:
        for task, ratio in sorted(m["per_task"].items()):
            lines.append(f"- {task}: {ratio:.2f}")
    return "\n".join(lines) + "\n"


def _svg_forest(summary: dict) -> str:
    rows = [(label, summary["metrics"][key], low) for key, label, _u, low in METRICS if summary["metrics"].get(key)]
    if not rows:
        return ""
    lo_all = min(0.5, min(m["lo"] for _l, m, _b in rows) * 0.9)
    hi_all = max(2.0, max(m["hi"] for _l, m, _b in rows) * 1.1)
    left, right, top, step = 250, 660, 34, 38
    def x(v): return left + (math.log(v) - math.log(lo_all)) / (math.log(hi_all) - math.log(lo_all)) * (right - left)
    parts = [f'<line x1="{x(1):.1f}" y1="{top - 14}" x2="{x(1):.1f}" y2="{top + step * len(rows) - 12}" stroke="var(--ink)" stroke-width="1.5"/>']
    ticks = [t for t in (0.25, 0.5, 0.75, 1, 1.5, 2, 3, 4) if lo_all <= t <= hi_all]
    for t in ticks:
        parts.append(f'<text x="{x(t):.1f}" y="{top + step * len(rows) + 6}" text-anchor="middle" class="tick">{t:g}×</text>')
    for i, (label, m, low) in enumerate(rows):
        y = top + i * step
        v = verdict(m["lo"], m["hi"], low)
        color = "var(--good)" if v == "less" else "var(--bad)" if v == "more" else "var(--mute)"
        parts.append(f'<text x="{left - 14}" y="{y + 4}" text-anchor="end" class="lab">{html.escape(label)}</text>')
        parts.append(f'<line x1="{x(m["lo"]):.1f}" y1="{y}" x2="{x(m["hi"]):.1f}" y2="{y}" stroke="{color}" stroke-width="3" stroke-linecap="round"/>')
        parts.append(f'<circle cx="{x(m["ratio"]):.1f}" cy="{y}" r="6" fill="{color}"/>')
        parts.append(f'<text x="{right + 16}" y="{y + 4}" class="val">{m["ratio"]:.2f}×</text>')
    height = top + step * len(rows) + 30
    return (f'<svg viewBox="0 0 760 {height}" role="img" aria-label="effect of Context Arbor per metric">'
            f'<text x="{x(1) - 8:.1f}" y="14" text-anchor="end" class="tick">{html.escape(summary["other"])} uses less</text>'
            f'<text x="{x(1) + 8:.1f}" y="14" class="tick">{html.escape(summary["other"])} uses more</text>{"".join(parts)}</svg>')


def _bars(summary: dict, key: str, label: str) -> str:
    tasks = summary["tasks"]
    if not tasks:
        return ""
    mean = lambda xs: sum(xs) / len(xs)
    data = []
    for t in tasks:
        reps = summary["paired"][t].values()
        data.append((t, mean([value(a, key) for a, _ in reps]), mean([value(b, key) for _, b in reps])))
    peak = max(max(a, b) for _t, a, b in data) or 1
    rows = []
    for t, a, b in data:
        rows.append(f'<div class="row"><span class="name">{html.escape(t.split("-", 1)[-1])}</span>'
                    f'<div class="pair"><i class="bar c" style="width:{a / peak * 100:.1f}%"></i><b>{a:,.0f}</b>'
                    f'<i class="bar a" style="width:{b / peak * 100:.1f}%"></i><b>{b:,.0f}</b></div></div>')
    return f'<h3>{html.escape(label)}</h3><div class="bars">{"".join(rows)}</div>'


def _section_html(summary: dict) -> str:
    base, other = summary["base"], summary["other"]
    md_rows = []
    for key, label, unit, low in METRICS:
        m = summary["metrics"].get(key)
        if m:
            v = verdict(m["lo"], m["hi"], low)
            md_rows.append(f'<tr><td>{html.escape(label)}</td><td>{m["ratio"]:.2f}× <small>({_pct(m["ratio"])})</small></td>'
                           f'<td>{m["lo"]:.2f} – {m["hi"]:.2f}</td><td>{m["below"]}/{m["tasks"]}</td>'
                           f'<td class="v {v.split()[0]}">{html.escape(v)}</td></tr>')
    s = summary["score"]
    acc = ""
    if s:
        v = verdict(s["lo"], s["hi"], False, 0.0)
        acc = (f'<p class="big">Accuracy: {html.escape(base)} <b>{s["control"]:.2f}</b>, {html.escape(other)} <b>{s["arbor"]:.2f}</b> '
               f'— difference {s["diff"]:+.2f} (95% interval {s["lo"]:+.2f} … {s["hi"]:+.2f}), '
               f'<span class="v {v.split()[0]}">{html.escape(v)}</span>.</p>')
    ad = summary.get("adoption")
    if ad:
        acc += (f'<p class="note">Adoption: the agent ran <code>arbor.py</code> in {ad["used"]} of {ad["runs"]} '
                f'sessions ({ad["share"]:.0%}).</p>')
    n_pairs = sum(len(v) for v in summary["paired"].values())
    return f"""<section><h2>{html.escape(other)} vs {html.escape(base)}</h2>
<p class="sub">{len(summary['tasks'])} tasks · {n_pairs} paired runs · {len(summary['invalid'])} excluded (error/timeout)</p>
<p class="note">Each dot is {html.escape(other)} ÷ {html.escape(base)} (geometric mean over tasks) with its 95% interval. Left of the line = {html.escape(other)} used less; a grey interval that crosses the line = no significant difference.</p>
{_svg_forest(summary)}
<table><thead><tr><th>Metric</th><th>Effect</th><th>95% interval</th><th>Tasks lower</th><th>Verdict</th></tr></thead><tbody>{''.join(md_rows)}</tbody></table>
{acc}
<p class="key"><span><i style="background:var(--c)"></i>{html.escape(base)}</span><span><i style="background:var(--a)"></i>{html.escape(other)}</span></p>
{_bars(summary, 'context_processed', 'Context processed per task (tokens, mean over repetitions)')}
{_bars(summary, 'cost_usd', 'Cost at list price per task (USD)')}
</section>"""


def render_html(summaries: list[dict], title: str, note: str = "") -> str:
    body = "".join(_section_html(s) for s in summaries)
    return f"""<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{html.escape(title)}</title><style>
:root{{--bg:#fff;--ink:#1c1b18;--mute:#77726a;--line:#e4e0d8;--good:#2a7d46;--bad:#b4432c;--c:#9a948a;--a:#2f6f9f;color-scheme:light dark}}
@media (prefers-color-scheme:dark){{:root{{--bg:#151412;--ink:#ece8df;--mute:#a09a8e;--line:#2c2a26;--good:#6cc48a;--bad:#e08a70;--c:#7d786f;--a:#7fb4dc}}}}
body{{margin:0;background:var(--bg);color:var(--ink);font:16px/1.55 system-ui,"Segoe UI",sans-serif}}
main{{max-width:860px;margin:0 auto;padding:32px 20px 72px}}
h1{{font-size:28px;margin:0 0 6px}}h2{{margin:48px 0 6px;font-size:22px;padding-top:24px;border-top:1px solid var(--line)}}h3{{margin:26px 0 8px;font-size:15px}}
.sub{{color:var(--mute);margin:0 0 10px}}svg{{width:100%;height:auto}}
.lab{{font-size:13px;fill:var(--ink)}}.tick{{font-size:12px;fill:var(--mute)}}.val{{font-size:13px;fill:var(--ink);font-weight:600}}
table{{border-collapse:collapse;width:100%;font-size:14px}}th,td{{padding:8px 10px;border-bottom:1px solid var(--line);text-align:left}}
th{{color:var(--mute);font-weight:600}}.v{{font-weight:600}}.v.less,.v.better{{color:var(--good)}}.v.more,.v.worse{{color:var(--bad)}}.v.no{{color:var(--mute)}}
.big{{font-size:17px}}.bars .row{{display:grid;grid-template-columns:130px 1fr;gap:10px;align-items:center;margin:6px 0;font-size:13px}}
.pair{{display:grid;grid-template-columns:1fr 70px;gap:2px 8px;align-items:center}}.pair b{{font-weight:500;color:var(--mute);font-variant-numeric:tabular-nums}}
.bar{{display:block;height:9px;border-radius:2px}}.bar.c{{background:var(--c)}}.bar.a{{background:var(--a)}}
.key span{{display:inline-block;margin-right:16px;font-size:13px}}.key i{{display:inline-block;width:10px;height:10px;border-radius:2px;margin-right:6px}}
.note{{color:var(--mute);font-size:14px}}
</style></head><body><main>
<h1>{html.escape(title)}</h1>
<p class="note">{html.escape(note)}</p>
{body}
</main></body></html>"""
