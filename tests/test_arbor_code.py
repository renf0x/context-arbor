import contextlib
import io
import json
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

import arbor as ctx


PY_SAMPLE = '''"""Billing helpers."""
MAX_ITEMS = 5


def total(items):
    """Sum the line items."""
    def inner():
        return 0
    return len(items)


class Cart:
    """Holds items."""

    def add(self, item):
        return item

    @staticmethod
    def make():
        return Cart()
'''


TS_SAMPLE = '''/** Cart totals and pricing helpers. */
import { x } from "y";

// Sums line items.
export function sumItems(items: Item[]): number {
  const inner = function helper() { return 1; };
  return items.length;
}

export const formatPrice = (n: number): string => {
  return n.toFixed(2);
};

export const MAX_ITEMS = 50;

export interface Item {
  id: string;
}

export type Price = number;

/** Holds the cart. */
export class Cart {
  private items: Item[] = [];

  constructor(private readonly id: string) {
    if (id) {
      this.id = id;
    }
  }

  async add(item: Item): Promise<void> {
    if (item) {
      this.items.push(item);
    }
  }
}
'''


GO_SAMPLE = '''package main

// Server handles requests.
type Server struct {
	addr string
}

type Handler interface {
	Serve()
}

// NewServer builds a Server.
func NewServer(addr string) *Server {
	return &Server{addr: addr}
}

func (s *Server) Run() error {
	return nil
}
'''


RUST_SAMPLE = '''//! Parser module.

/// A token.
pub struct Token {
    kind: u8,
}

pub trait Visit {
    fn visit(&self);
}

impl Token {
    pub fn new(kind: u8) -> Self {
        fn inner() {}
        Token { kind }
    }
}

pub async fn parse(src: &str) -> Vec<Token> {
    vec![]
}
'''


JAVA_SAMPLE = '''package x;

/** Order service. */
public class OrderService {
    private final int n;

    public List<Order> findOrders(String user) throws IOException {
        if (user == null) {
            return List.of();
        }
        return repo.find(user);
    }
}
'''


RUBY_SAMPLE = '''# Billing helpers.

module Billing
  class Invoice
    # Total in cents.
    def total
      @lines.sum
    end
  end
end
'''


GD_SAMPLE = '''class_name FlightTask
extends RefCounted
## Flies a craft to a target.
## Second line.

signal finished(ok)

enum Phase { PLAN, WAIT }
enum { ANON_A, ANON_B }

## Burn share limit.
const LONG_BURN: float = 0.12
const lower_case = 1

@export var speed: float = 1.0
@export_range(0.0, 1.0) var ratio := 0.5
@onready var node = $Node
var state := 0

## Advance the task.
@rpc("any_peer")
func tick(dt: float) -> void:
\tvar f = func(x): return x
\tif dt > 0:
\t\tstate += 1

static func make() -> FlightTask:
\treturn FlightTask.new()

class Inner:
\tvar a := 1
\tfunc run():
\t\tpass
'''


MD_SAMPLE = '''# Guide

Intro.

## Install

```sh
# not a heading
pip install x
```

## Usage

Text.
'''


class CodeTestCase(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.root, True)

    def write(self, rel, text):
        path = self.root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
        return path

    def run_cli(self, *argv):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = ctx.main(list(argv))
        return code, out.getvalue(), err.getvalue()

    def code(self, *argv):
        return self.run_cli("code", *argv, "--path", str(self.root))

    def symbols(self, rel):
        path = self.root / rel
        return {s["n"]: s for s in ctx._index_file(path, path.stat())["symbols"]}


class SymbolExtractionTests(CodeTestCase):
    def test_python_uses_ast_for_nesting_docs_and_ranges(self):
        self.write("cart.py", PY_SAMPLE)
        path = self.root / "cart.py"
        record = ctx._index_file(path, path.stat())
        syms = {s["n"]: s for s in record["symbols"]}
        self.assertEqual(record["summary"], "Billing helpers.")
        self.assertEqual(set(syms), {"MAX_ITEMS", "total", "Cart", "Cart.add", "Cart.make"})
        self.assertEqual(syms["MAX_ITEMS"]["k"], "const")
        self.assertEqual(syms["Cart.add"]["k"], "method")
        self.assertEqual(syms["total"]["d"], "Sum the line items.")
        self.assertEqual((syms["total"]["l"], syms["total"]["e"]), (5, 9))
        # the range of a decorated method starts at its decorator
        self.assertEqual(PY_SAMPLE.splitlines()[syms["Cart.make"]["l"] - 1].strip(), "@staticmethod")

    def test_unparseable_python_still_indexes_the_file(self):
        self.write("old.py", "print 'py2'\n")
        path = self.root / "old.py"
        record = ctx._index_file(path, path.stat())
        self.assertEqual(record["symbols"], [])
        self.assertEqual(record["lang"], "python")

    def test_typescript_functions_classes_and_members(self):
        self.write("cart.ts", TS_SAMPLE)
        path = self.root / "cart.ts"
        record = ctx._index_file(path, path.stat())
        syms = {s["n"]: s for s in record["symbols"]}
        self.assertEqual(record["summary"], "Cart totals and pricing helpers.")
        self.assertEqual(set(syms), {"sumItems", "formatPrice", "MAX_ITEMS", "Item", "Price",
                                     "Cart", "Cart.constructor", "Cart.add"})
        self.assertEqual(syms["sumItems"]["d"], "Sums line items.")
        self.assertEqual(syms["Item"]["k"], "interface")
        self.assertEqual(syms["Price"]["k"], "type")
        self.assertNotIn("helper", syms)  # declared inside a function body
        self.assertNotIn("Cart.if", syms)

    def test_go_receivers_qualify_method_names(self):
        self.write("main.go", GO_SAMPLE)
        syms = self.symbols("main.go")
        self.assertEqual(set(syms), {"Server", "Handler", "NewServer", "Server.Run"})
        self.assertEqual(syms["Server"]["k"], "struct")
        self.assertEqual(syms["Server.Run"]["k"], "method")

    def test_rust_keeps_a_method_called_new_and_drops_nested_fns(self):
        self.write("lib.rs", RUST_SAMPLE)
        path = self.root / "lib.rs"
        record = ctx._index_file(path, path.stat())
        syms = {s["n"] for s in record["symbols"]}
        self.assertIn("Token.new", syms)  # `new` is a keyword only for member-only rules
        self.assertIn("Visit.visit", syms)
        self.assertIn("parse", syms)
        self.assertNotIn("Token.inner", syms)
        self.assertEqual(record["summary"], "Parser module.")

    def test_java_methods_need_a_class_and_skip_control_flow(self):
        self.write("OrderService.java", JAVA_SAMPLE)
        syms = self.symbols("OrderService.java")
        self.assertEqual(set(syms), {"OrderService", "OrderService.findOrders"})

    def test_ruby_modules_classes_and_methods(self):
        self.write("billing.rb", RUBY_SAMPLE)
        syms = self.symbols("billing.rb")
        self.assertEqual(set(syms), {"Billing", "Billing.Invoice", "Billing.Invoice.total"})

    def test_gdscript_class_name_members_exports_and_doc_comments(self):
        self.write("flight_task.gd", GD_SAMPLE)
        path = self.root / "flight_task.gd"
        record = ctx._index_file(path, path.stat())
        syms = {s["n"]: s for s in record["symbols"]}
        self.assertEqual(set(syms), {
            "FlightTask", "finished", "Phase", "LONG_BURN", "speed", "ratio",
            "tick", "make", "Inner", "Inner.run"})
        self.assertEqual(record["summary"], "Flies a craft to a target.")
        self.assertEqual(
            {name: syms[name]["k"] for name in ("finished", "Phase", "LONG_BURN", "speed", "tick",
                                                "Inner", "Inner.run")},
            {"finished": "signal", "Phase": "enum", "LONG_BURN": "const", "speed": "property",
             "tick": "function", "Inner": "class", "Inner.run": "method"})
        self.assertEqual(syms["tick"]["d"], "Advance the task.")  # `@rpc` sits between doc and func
        lines = GD_SAMPLE.splitlines()
        self.assertTrue(lines[syms["tick"]["l"] - 1].startswith("func tick"))
        self.assertEqual(lines[syms["tick"]["e"] - 1], "\t\tstate += 1")
        self.assertEqual(lines[syms["Inner.run"]["e"] - 1], "\t\tpass")

    def test_markdown_headings_ignore_fenced_code(self):
        self.write("guide.md", MD_SAMPLE)
        syms = self.symbols("guide.md")
        self.assertEqual(set(syms), {"Guide", "Install", "Usage"})
        self.assertEqual(syms["Guide"]["e"], len(MD_SAMPLE.splitlines()))
        self.assertLess(syms["Install"]["e"], syms["Usage"]["l"])

    def test_a_comment_glued_to_the_first_declaration_is_not_the_file_summary(self):
        self.write("main.go", GO_SAMPLE)
        path = self.root / "main.go"
        self.assertEqual(ctx._index_file(path, path.stat())["summary"], "")

    def test_binary_files_are_not_indexed(self):
        (self.root / "blob.py").write_bytes(b"\0\1\2 not text")
        path = self.root / "blob.py"
        self.assertIsNone(ctx._index_file(path, path.stat()))


class IndexTests(CodeTestCase):
    def test_refresh_reparses_only_changed_files_and_drops_deleted_ones(self):
        self.write("a.py", "def one():\n    pass\n")
        self.write("b.py", "def two():\n    pass\n")
        index, updated = ctx._code_index(self.root)
        self.assertEqual((sorted(index["files"]), updated), (["a.py", "b.py"], 2))
        index, updated = ctx._code_index(self.root)
        self.assertEqual(updated, 0)
        self.write("a.py", "def one():\n    pass\n\ndef uno():\n    pass\n")
        (self.root / "b.py").unlink()
        index, updated = ctx._code_index(self.root)
        self.assertEqual((sorted(index["files"]), updated), (["a.py"], 1))
        self.assertEqual([s["n"] for s in index["files"]["a.py"]["symbols"]], ["one", "uno"])
        self.assertTrue((self.root / ctx.CODE_INDEX_REL).is_file())

    def test_secrets_vault_and_dependency_folders_are_never_indexed(self):
        self.write("app.py", "def run():\n    pass\n")
        self.write(".env", "TOKEN=secret\n")
        self.write("deploy.pem", "-----BEGIN-----\n")
        self.write("node_modules/lib/index.js", "function x() {}\n")
        self.write("package-lock.json", "{}\n")
        self.write("memory/MEMORY.md", "# Memory\n")
        self.write("memory/decisions.md", "# Decisions\n")
        index, _ = ctx._code_index(self.root)
        self.assertEqual(sorted(index["files"]), ["app.py"])

    def test_a_folder_named_memory_without_a_vault_is_ordinary_code(self):
        self.write("memory/cache.py", "def get():\n    pass\n")
        index, _ = ctx._code_index(self.root)
        self.assertEqual(sorted(index["files"]), ["memory/cache.py"])

    @unittest.skipUnless(shutil.which("git"), "git is required")
    def test_gitignore_is_honoured_when_the_project_is_a_repository(self):
        subprocess.run(["git", "init", "-q"], cwd=self.root, check=True)
        self.write(".gitignore", "generated/\n")
        self.write("generated/big.py", "def skip():\n    pass\n")
        self.write("src/keep.py", "def keep():\n    pass\n")
        index, _ = ctx._code_index(self.root)
        self.assertEqual(sorted(index["files"]), ["src/keep.py"])

    def test_corrupt_index_file_is_rebuilt(self):
        self.write("a.py", "def one():\n    pass\n")
        path = self.root / ctx.CODE_INDEX_REL
        path.parent.mkdir(parents=True)
        path.write_text("{not json", encoding="utf-8")
        index, updated = ctx._code_index(self.root)
        self.assertEqual((list(index["files"]), updated), (["a.py"], 1))
        json.loads(path.read_text(encoding="utf-8"))


class FindTests(CodeTestCase):
    def build(self):
        self.write("src/relations.py",
                   '"""Entry graph."""\n\ndef relations_graph(memory):\n    """Local entry graph."""\n    return {}\n')
        self.write("tests/test_relations.py",
                   "class RelationsTests:\n    def test_trace_walks(self):\n        pass\n\n"
                   "    def test_trace_loops(self):\n        pass\n")
        self.write("src/other.py", "def unrelated():\n    pass\n")
        return ctx._code_index(self.root)[0]

    def test_definitions_outrank_tests_and_owner_names_are_a_weak_signal(self):
        index = self.build()
        hits = ctx._code_find(index, "relations graph trace", 5)
        self.assertEqual((hits[0][1], hits[0][2]["n"]), ("src/relations.py", "relations_graph"))

    def test_exact_name_wins_and_camel_and_snake_case_split_into_words(self):
        self.write("a.py", "def parse_http_request():\n    pass\n\ndef parse():\n    pass\n")
        index = ctx._code_index(self.root)[0]
        self.assertEqual(ctx._code_find(index, "parse", 3)[0][2]["n"], "parse")
        self.assertEqual(ctx._code_find(index, "HTTPRequest", 3)[0][2]["n"], "parse_http_request")
        self.assertEqual(ctx._name_terms("parseHTTPRequest v2"), ["parse", "http", "request", "v2"])

    def test_kind_filter_and_no_match(self):
        index = self.build()
        kinds = {h[2]["k"] for h in ctx._code_find(index, "relations", 10, kind="class")}
        self.assertEqual(kinds, {"class"})
        self.assertEqual(ctx._code_find(index, "zzzz", 5), [])
        self.assertEqual(ctx._code_find(index, "  ", 5), [])

    def test_cli_prints_location_kind_and_name_and_supports_json(self):
        self.build()
        code, out, _ = self.code("find", "relations graph")
        self.assertEqual(code, 0)
        self.assertIn("src/relations.py:3  function  relations_graph", out)
        self.assertIn("no LLM", out)
        code, out, _ = self.code("find", "relations graph", "--json", "--top", "2")
        payload = json.loads(out)
        self.assertEqual(payload["hits"][0]["symbol"], "relations_graph")
        self.assertEqual(len(payload["hits"]), 2)


class ShowMapAndRefsTests(CodeTestCase):
    def test_show_a_symbol_a_range_and_a_whole_small_file(self):
        self.write("cart.py", PY_SAMPLE)
        code, out, _ = self.code("show", "cart.py:Cart.add")
        self.assertEqual(code, 0)
        self.assertIn("15|    def add(self, item):", out)
        self.assertNotIn("def total", out)
        code, out, _ = self.code("show", "cart.py:4-6")
        self.assertEqual(out.splitlines()[0], "# cart.py:4-6")
        self.assertEqual(len(out.splitlines()), 4)
        code, out, _ = self.code("show", "cart.py")
        self.assertIn("1|\"\"\"Billing helpers.\"\"\"", out)

    def test_show_matches_a_bare_member_name_and_trailing_path(self):
        self.write("pkg/cart.py", PY_SAMPLE)
        code, out, _ = self.code("show", "cart.py:make")
        self.assertEqual(code, 0)
        self.assertIn("Cart.make", out)
        self.assertIn("@staticmethod", out)

    def test_big_file_without_a_target_shows_the_outline_not_the_source(self):
        self.write("cart.py", PY_SAMPLE)
        code, out, _ = self.code("show", "cart.py", "--max-lines", "5")
        self.assertEqual(code, 0)
        self.assertIn("showing its outline instead", out)
        self.assertIn("class Cart", out)
        self.assertNotIn("return len(items)", out)

    def test_show_truncates_a_long_slice_and_says_how_to_continue(self):
        self.write("cart.py", PY_SAMPLE)
        code, out, _ = self.code("show", "cart.py:1-18", "--max-lines", "4")
        self.assertIn("14 more lines; continue with code show cart.py:5-18", out)

    def test_show_errors_are_explicit(self):
        self.write("cart.py", PY_SAMPLE)
        self.assertEqual(self.code("show", "nope.py")[0], 2)
        code, _, err = self.code("show", "cart.py:missing_symbol")
        self.assertEqual(code, 2)
        self.assertIn("no symbol 'missing_symbol'", err)
        self.assertEqual(self.code("show", "cart.py:500-600")[0], 2)

    def test_show_refuses_a_secret_even_if_it_is_named_explicitly(self):
        self.write(".env", "TOKEN=secret\n")
        code, out, _ = self.code("show", ".env")
        self.assertEqual(code, 2)
        self.assertNotIn("secret", out)

    def test_outline_lists_members_with_ranges(self):
        self.write("cart.py", PY_SAMPLE)
        code, out, _ = self.code("outline", "cart.py")
        self.assertEqual(code, 0)
        self.assertIn("5-9 function total - Sum the line items.", out)
        self.assertIn("  15-16 method add", out)
        self.assertEqual(self.code("outline", "ghost.py")[0], 2)

    def test_map_picks_the_richest_level_that_fits_the_budget(self):
        for i in range(6):
            self.write(f"pkg{i}/mod.py", f'"""Module {i}."""\n\ndef fn_{i}():\n    pass\n')
        code, full, _ = self.code("map", "--budget", "5000")
        self.assertIn("fn_3", full)
        code, small, _ = self.code("map", "--budget", "60")
        self.assertNotIn("fn_3", small)
        self.assertLess(ctx.est_tokens(small), ctx.est_tokens(full))
        code, scoped, _ = self.code("map", "--dir", "pkg2")
        self.assertIn("fn_2", scoped)
        self.assertNotIn("fn_3", scoped)

    def test_a_huge_tree_folds_into_a_short_directory_overview(self):
        for i in range(60):
            for j in range(3):
                self.write(f"pkg{i % 4}/mod{i}/lib{j}/mod.py", "def f():\n    pass\n")
        self.write("src/app/main.py", "def run():\n    pass\n")
        code, out, _ = self.code("map")
        listed = [l for l in out.splitlines() if not l.startswith("#")]
        self.assertLessEqual(len(listed), ctx.CODE_MAP_DIR_LINES)
        self.assertIn("pkg1/  45 files (python, incl. subfolders)", out)
        self.assertNotIn("truncated", out)
        code, scoped, _ = self.code("map", "--dir", "src")  # drilling in shows the real tree
        self.assertIn("src/app/", scoped)

    def test_map_definitions_come_before_constants(self):
        self.write("cart.py", PY_SAMPLE)
        code, out, _ = self.code("map")
        self.assertLess(out.index("total"), out.index("MAX_ITEMS"))

    def test_refs_are_whole_word_and_bounded(self):
        self.write("a.py", "def total():\n    return subtotal\n")
        self.write("b.py", "x = total()\n" * 30)
        code, out, _ = self.code("refs", "total", "--top", "3")
        self.assertEqual(code, 0)
        self.assertNotIn("subtotal", out)
        self.assertEqual(len([l for l in out.splitlines() if not l.startswith("#")]), 3)
        self.assertIn("31 reference(s) in 2 file(s); 28 more", out)
        self.assertIn("no references", self.code("refs", "absent_name")[1])

    def test_removed_top_level_commands_stay_removed(self):
        for name in ("map", "digest", "read"):
            with self.subTest(name=name), contextlib.redirect_stderr(io.StringIO()):
                with self.assertRaises(SystemExit):
                    ctx.main([name])


if __name__ == "__main__":
    unittest.main()
