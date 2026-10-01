"""Task suites for the A/B benchmark: fixtures, questions with machine-computed answers, scorers.

Everything a scorer needs is derived from the fixture source itself (with `ast`), never typed
in by hand, so a task cannot drift from the code it asks about. Targets are picked with a
seeded RNG under fixed constraints: the same fixture always yields the same tasks.

Suite `code` runs on a third-party library that is installed locally (paramiko). It is not
part of this repository and has nothing to do with Context Arbor, so the tool under test
cannot have been shaped around it.
"""
from __future__ import annotations

import ast
import hashlib
import importlib.util
import json
import random
import re
import shutil
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path

ANSWER_RE = re.compile(r"(?im)^\s*ANSWER:\s*(.+?)\s*$")
FOOTER = ("\n\nWork efficiently. When you are done, end your reply with exactly one line of the "
          "form `ANSWER: <json>` and nothing after it.")


@dataclass
class Task:
    id: str
    kind: str
    prompt: str
    expected: object
    scorer: str
    meta: dict = field(default_factory=dict)


# ---------------------------------------------------------------- source index (ast)

def package_dir(name: str) -> Path:
    spec = importlib.util.find_spec(name)
    if spec is None or not spec.submodule_search_locations:
        raise SystemExit(f"package {name!r} is not installed; the code suite needs it")
    return Path(next(iter(spec.submodule_search_locations)))


def copy_package(name: str, dest: Path) -> Path:
    """Copy the installed package (sources only) into `dest/<name>`."""
    target = dest / name
    shutil.copytree(package_dir(name), target,
                    ignore=shutil.ignore_patterns("__pycache__", "*.pyc", "*.pyi", "py.typed"))
    return target


def _defs(tree: ast.AST):
    """(class_or_None, FunctionDef) for every function/method; nested ones are skipped."""
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            yield None, node
        elif isinstance(node, ast.ClassDef):
            for item in node.body:
                if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    yield node, item


def _own_nodes(func: ast.AST):
    """Nodes of a function body without descending into nested functions or classes."""
    stack = list(getattr(func, "body", []))
    while stack:
        node = stack.pop()
        yield node
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef, ast.Lambda)):
            continue
        stack.extend(ast.iter_child_nodes(node))


class Index:
    def __init__(self, root: Path, package: str):
        self.root, self.package = root, package
        self.files: dict[str, ast.Module] = {}
        self.text: dict[str, str] = {}
        self._hits: dict[str, int] | None = None
        for path in sorted((root / package).rglob("*.py")):
            rel = path.relative_to(root).as_posix()
            try:
                text = path.read_text(encoding="utf-8")
                self.files[rel] = ast.parse(text)
                self.text[rel] = text
            except (SyntaxError, UnicodeDecodeError):
                continue
        self.classes: dict[str, list[tuple[str, ast.ClassDef]]] = {}
        self.functions: dict[str, list[tuple[str, ast.AST, ast.AST | None]]] = {}
        for rel, tree in self.files.items():
            for node in ast.walk(tree):
                if isinstance(node, ast.ClassDef):
                    self.classes.setdefault(node.name, []).append((rel, node))
            for cls, func in _defs(tree):
                self.functions.setdefault(func.name, []).append((rel, func, cls))

    def _scan(self) -> None:
        """One pass over every tree: who calls what, which names are code, what runs at import."""
        self._calls: dict[str, set[tuple[str, str]]] = {}
        self._hits: dict[str, int] = {}
        self._toplevel: set[str] = set()
        for rel, tree in self.files.items():
            for node in ast.walk(tree):
                label = (node.id if isinstance(node, ast.Name) else
                         node.attr if isinstance(node, ast.Attribute) else
                         node.name if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.alias)) else None)
                if label:
                    self._hits[label] = self._hits.get(label, 0) + 1
            for _cls, func in _defs(tree):
                for node in _own_nodes(func):
                    if isinstance(node, ast.Call):
                        f = node.func
                        called = f.id if isinstance(f, ast.Name) else f.attr if isinstance(f, ast.Attribute) else None
                        if called:
                            self._calls.setdefault(called, set()).add((rel, func.name))
            for node in tree.body:
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                    continue
                for sub in ast.walk(node):
                    if isinstance(sub, ast.Call) and isinstance(sub.func, ast.Name):
                        self._toplevel.add(sub.func.id)

    def callers(self, name: str) -> set[tuple[str, str]]:
        """(file, enclosing def name) of every call to `name(...)` / `x.name(...)`."""
        if self._hits is None:
            self._scan()
        return set(self._calls.get(name, ()))

    def code_hits(self, name: str) -> int:
        """Names, attributes, definitions and imports called `name` -- code, not prose."""
        if self._hits is None:
            self._scan()
        return self._hits.get(name, 0)

    def module_level_calls(self, name: str) -> bool:
        if self._hits is None:
            self._scan()
        return name in self._toplevel


# ---------------------------------------------------------------- scorers

def parse_answer(text: str):
    """The JSON after the last `ANSWER:` line, or None."""
    found = ANSWER_RE.findall(text or "")
    if not found:
        return None
    try:
        return json.loads(found[-1])
    except json.JSONDecodeError:
        return None


def norm_path(value: object, package: str) -> str:
    text = str(value).replace("\\", "/").strip().strip("`").lstrip("./")
    return text if text.startswith(package + "/") else f"{package}/{text}"


def _literal(value: object) -> object:
    if isinstance(value, str):
        try:
            return ast.literal_eval(value.strip())
        except (ValueError, SyntaxError):
            return value.strip()
    return value


def f1(found: set, expected: set) -> float:
    if not found and not expected:
        return 1.0
    hit = len(found & expected)
    if not hit:
        return 0.0
    precision, recall = hit / len(found), hit / len(expected)
    return 2 * precision * recall / (precision + recall)


NOT_RECORDED = {"", "null", "none", "unknown", "n/a", "not recorded", "not found", "no record",
                "not documented", "not specified", "nothing recorded", "unrecorded"}


def _value_of(answer: object) -> object:
    return answer.get("value", answer.get("id")) if isinstance(answer, dict) else answer


def score(task: Task, answer: object, workdir: Path | None = None, package: str = "",
          answered: bool = True) -> float:
    """0..1. `answered` says whether an `ANSWER:` line was given at all, so that a deliberate
    `ANSWER: null` (right for a question with no recorded answer) differs from no answer."""
    if task.scorer == "rename":
        return score_rename(task, workdir)
    if task.scorer == "bundle":
        if not isinstance(answer, dict):
            return 0.0
        parts = [score(sub, answer.get(str(i)), None, package, str(i) in answer)
                 for i, sub in enumerate(task.expected, 1)]
        return sum(parts) / len(parts)
    if answer is None and not (task.scorer == "absent" and answered):
        return 0.0
    exp = task.expected
    try:
        if task.scorer == "id":
            return 1.0 if str(_value_of(answer)).strip().strip("`").upper() == str(exp).upper() else 0.0
        if task.scorer == "value":
            got = str(_value_of(answer)).strip().strip("`\"'")
            if str(exp).lstrip("-").isdigit():
                found = re.search(r"-?\d+", got.replace(",", ""))
                return 1.0 if found and found.group(0) == str(exp) else 0.0
            return 1.0 if got.lower() == str(exp).lower() else 0.0
        if task.scorer == "absent":
            got = _value_of(answer)
            return 1.0 if got is None or str(got).strip().lower() in NOT_RECORDED else 0.0
        if task.scorer == "def_line":
            if not isinstance(answer, dict):
                return 0.0
            right_file = norm_path(answer.get("file", ""), package) == exp["file"]
            right_line = str(answer.get("line")) == str(exp["line"])
            return 1.0 if right_file and right_line else 0.5 if right_file else 0.0
        if task.scorer == "defaults":
            if not isinstance(answer, dict):
                return 0.0
            got = {str(k): _literal(v) for k, v in answer.items()}
            want = {k: _literal(v) for k, v in exp.items()}
            return sum(1 for k, v in want.items() if k in got and got[k] == v) / len(want)
        if task.scorer == "pairs":
            got = set()
            for item in answer if isinstance(answer, list) else []:
                path, _sep, name = str(item).rpartition(":")
                got.add((norm_path(path, package), name.split(".")[-1].strip("` ()")))
            return f1(got, {tuple(p) for p in exp})
        if task.scorer == "names":
            got = {str(x).strip("` ").split(".")[-1] for x in (answer if isinstance(answer, list) else [])}
            return f1(got, set(exp))
        if task.scorer == "int":
            return 1.0 if str(answer).strip() == str(exp) else 0.0
    except (TypeError, ValueError, AttributeError):
        return 0.0
    raise ValueError(task.scorer)


def score_rename(task: Task, workdir: Path | None) -> float:
    """1.0 only if the tree equals the original with exactly the old name replaced by the new
    one (word-boundary substitution, applied to every file); the fraction of files that are
    exactly right otherwise. The package must still import."""
    if workdir is None:
        return 0.0
    old, new, package = task.expected["old"], task.expected["new"], task.meta["package"]
    pattern = re.compile(rf"\b{re.escape(old)}\b")
    right = total = 0
    for rel, original in task.expected["originals"].items():
        total += 1
        path = workdir / rel
        want = pattern.sub(new, original)
        try:
            right += path.read_text(encoding="utf-8") == want
        except OSError:
            pass
    fraction = right / total if total else 0.0
    for rel, digest in task.expected["others"].items():
        try:
            if hashlib.sha1((workdir / rel).read_bytes()).hexdigest() != digest:
                fraction = min(fraction, 0.5)  # "change nothing else" was violated
        except OSError:
            fraction = min(fraction, 0.5)
    if fraction == 1.0:
        try:
            subprocess.run([sys.executable, "-c", f"import {package}"], cwd=workdir, check=True,
                           capture_output=True, timeout=60)
        except (subprocess.SubprocessError, OSError):
            return 0.0
    return fraction


# ---------------------------------------------------------------- code suite (paramiko)

def _pick(rng: random.Random, options: list, count: int = 1) -> list:
    options = sorted(options, key=repr)
    rng.shuffle(options)
    return options[:count]


def code_tasks(root: Path, package: str, seed: int = 20260929, per_kind: int = 2) -> list[Task]:
    """Tasks on an installed package that has been copied to `root/package`: `per_kind`
    different targets for each kind of question, so no single lucky target decides the result."""
    ix = Index(root, package)
    rng = random.Random(seed)
    tasks: list[Task] = []
    taken: set[str] = set()

    def add(kind, i, question, expected, scorer, **meta):
        tasks.append(Task(f"{package}-{kind}{i}", kind, question + FOOTER, expected, scorer,
                          {"package": package, **meta}))
        taken.add(meta["target"].split(".")[-1])

    def method_options(keep):
        """(class, method, def) of uniquely named, non-dunder methods that pass `keep`."""
        for fname, defs in ix.functions.items():
            for rel, func, cls in defs:
                if cls is not None and len(defs) == 1 and not fname.startswith("__") and keep(func):
                    yield cls.name, fname, func

    # where is a class defined
    names = [n for n, defs in ix.classes.items()
             if len(defs) == 1 and not defs[0][0].endswith("__init__.py") and len(n) > 7
             and not n.startswith("_") and defs[0][1].lineno > 40]
    for i, name in enumerate(_pick(rng, names, per_kind), 1):
        rel, node = ix.classes[name][0]
        add("class-line", i, f"In which file (path relative to the project root) and on which line "
            f"does the definition of the class `{name}` start? Answer as "
            f"{{\"file\": ..., \"line\": ...}}.", {"file": rel, "line": node.lineno}, "def_line", target=name)

    # default values of a method's parameters
    options = []
    plain = lambda f: (3 <= len(f.args.defaults) <= 6 and not f.args.posonlyargs
                       and not any(d is not None for d in f.args.kw_defaults))
    for cls_name, fname, func in method_options(plain):
        pairs = zip(func.args.args[len(func.args.args) - len(func.args.defaults):], func.args.defaults)
        options.append((cls_name, fname, {a.arg: ast.unparse(d) for a, d in pairs}))
    for i, (cls_name, fname, defaults) in enumerate(_pick(rng, options, per_kind), 1):
        add("defaults", i, f"What are the default values of the parameters that have one in the "
            f"definition of the method `{cls_name}.{fname}`? Answer as a JSON object mapping "
            f"parameter name to the default exactly as written in the source code, as a string.",
            defaults, "defaults", target=f"{cls_name}.{fname}")

    # who calls a helper
    common = {n for kind in (bytes, str, list, dict, set, int, float, bytearray, tuple)
              for n in dir(kind)}  # x.decode() on bytes is not a call to the package's decode
    options = []
    for fname, defs in ix.functions.items():
        if len(defs) != 1 or fname.startswith("__") or len(fname) < 6 or fname in common:
            continue
        callers = ix.callers(fname)
        if 4 <= len(callers) <= 9 and len({r for r, _ in callers}) >= 2 and not ix.module_level_calls(fname):
            options.append((fname, sorted(callers)))
    for i, (fname, callers) in enumerate(_pick(rng, options, per_kind + 1), 1):
        add("callers", i, f"List every function or method in the `{package}` package whose body "
            f"contains a call to `{fname}(...)` (a plain call or a method call such as "
            f"`self.{fname}(...)`). Do not count the definition itself. Answer as a JSON list "
            f"of strings `\"<file path relative to the project root>:<name of the calling def>\"`.",
            callers, "pairs", target=fname)

    # direct subclasses
    subclasses: dict[str, set[str]] = {}
    for cname, defs in ix.classes.items():
        for _rel, cnode in defs:
            for base in cnode.bases:
                bname = base.id if isinstance(base, ast.Name) else base.attr if isinstance(base, ast.Attribute) else None
                if bname:
                    subclasses.setdefault(bname, set()).add(cname)
    options = [(b, sorted(s)) for b, s in subclasses.items()
               if b in ix.classes and 3 <= len(s) <= 10 and len(ix.classes[b]) == 1]
    for i, (base, subs) in enumerate(_pick(rng, options, per_kind), 1):
        add("subclasses", i, f"List the names of all classes defined in the `{package}` package "
            f"that directly inherit from `{base}` (it appears in their base-class list). Answer "
            f"as a JSON list of class names.", subs, "names", target=base)

    # how many methods does a large class define
    options = []
    for cname, defs in ix.classes.items():
        if len(defs) == 1:
            count = sum(isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) for n in defs[0][1].body)
            if 20 <= count <= 120:
                options.append((cname, count))
    for i, (cname, count) in enumerate(_pick(rng, options, per_kind), 1):
        add("method-count", i, f"How many methods (functions defined with `def` directly in the "
            f"class body, including private and dunder ones, but not nested functions) does the "
            f"class `{cname}` define? Answer as a JSON integer.", count, "int", target=cname)

    # exceptions raised explicitly by a method
    options = []
    for cls_name, fname, func in method_options(lambda f: f.end_lineno - f.lineno > 15):
        raised, clear = set(), True
        for node in _own_nodes(func):
            if isinstance(node, ast.Raise):
                exc = None if node.exc is None else node.exc.func if isinstance(node.exc, ast.Call) else node.exc
                name = exc.id if isinstance(exc, ast.Name) else exc.attr if isinstance(exc, ast.Attribute) else ""
                if not name[:1].isupper():  # a bare `raise` or `raise e`: what is raised is not a name
                    clear = False
                raised.add(name)
        if clear and 2 <= len(raised) <= 6:
            options.append((cls_name, fname, sorted(raised)))
    for i, (cls_name, fname, raised) in enumerate(_pick(rng, options, per_kind), 1):
        add("raises", i, f"Which exception classes are raised explicitly (with a `raise` statement "
            f"in the body, not in nested functions) by the method `{cls_name}.{fname}`? Answer as "
            f"a JSON list of class names.", raised, "names", target=f"{cls_name}.{fname}")

    # rename a private helper across the package (an edit task, checked on the tree)
    options = []
    for fname, defs in ix.functions.items():
        if len(defs) == 1 and fname.startswith("_") and not fname.startswith("__") and len(fname) > 6 \
                and fname not in taken:
            uses = {rel for rel, text in _sources(ix, root) if re.search(rf"\b{re.escape(fname)}\b", text)}
            total = sum(len(re.findall(rf"\b{re.escape(fname)}\b", ix.text[r])) for r in uses)
            # every textual hit must be real code, so "everywhere" has exactly one right answer
            if 4 <= total <= 12 and len(uses) >= 2 and ix.code_hits(fname) == total:
                options.append((fname, sorted(uses)))
    for i, (fname, uses) in enumerate(_pick(rng, options, per_kind), 1):
        new = fname + "_renamed"
        add("rename", i, f"Rename the function `{fname}` to `{new}` everywhere in the `{package}` "
            f"package: its definition and every use. Change nothing else. There is nothing to "
            f"answer; when finished, reply `ANSWER: \"done\"`.",
            {"old": fname, "new": new,
             "originals": {r: (root / r).read_text(encoding="utf-8") for r in uses},
             "others": {r: hashlib.sha1((root / r).read_bytes()).hexdigest()
                        for r in ix.files if r not in uses}},
            "rename", target=fname)
    return tasks


def code_session_tasks(root: Path, package: str, seed: int = 20261001, bundles: int = 4) -> list[Task]:
    """Long sessions: each task is six different questions (one of each kind) put to the agent
    in one session, so the context it builds up on the first question is re-read on all later
    ones. Targets are drawn with a different seed from the single-question suite."""
    kinds = ["class-line", "defaults", "callers", "subclasses", "method-count", "raises"]
    pool = [t for t in code_tasks(root, package, seed, per_kind=bundles) if t.kind in kinds]
    by_kind = {k: [t for t in pool if t.kind == k] for k in kinds}
    tasks = []
    for b in range(bundles):
        subs = [by_kind[k][b] for k in kinds if len(by_kind[k]) > b]
        questions = "\n\n".join(f"{i}. {s.prompt[:-len(FOOTER)]}" for i, s in enumerate(subs, 1))
        prompt = (f"Answer all {len(subs)} questions below about this project.\n\n{questions}\n\n"
                  f"Work efficiently. When you are done, end your reply with exactly one line of the "
                  f"form `ANSWER: <json>` and nothing after it, where the JSON is an object with the keys "
                  f"\"1\" to \"{len(subs)}\", each holding the answer to that question in the format the "
                  f"question asks for.")
        tasks.append(Task(f"{package}-session{b + 1}", "session", prompt, subs, "bundle",
                          {"package": package, "target": ",".join(s.meta["target"] for s in subs)}))
    return tasks


def _sources(ix: Index, root: Path):
    yield from ix.text.items()


import memsuite  # noqa: E402  (after Task/FOOTER exist; memsuite imports them lazily)

SUITES = {"code": code_tasks, "code-session": code_session_tasks, **memsuite.TASK_BUILDERS}
