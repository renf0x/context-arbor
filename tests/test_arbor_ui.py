import contextlib
import io
import os
import re
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import arbor as ctx


DECISIONS = """# Decision Log

## DEC-20260914-001 Ring topology

- Status: active
- Date: 2026-09-14
- Decision: Use hot, warm and cold rings.
- Reason: Active context must stay small.
- Relations:
- Links: [[NOW]]

## DEC-20260915-002 <script>alert(1)</script> Storage

- Status: active
- Date: 2026-09-15
- Decision: Keep <b>notes</b> as Markdown.
- Reason: Portable.
- Relations: supersedes:DEC-20260914-001, relates-to:INV-20260914-001
- Links:
"""


INVESTIGATIONS = """# Investigation Log

## INV-20260914-001 Is a graph worth it

- Status: closed
- Date: 2026-09-14
- Question: Do we need a graph database?
- Findings: Not really.
- Conclusion: Use a typed field.
- Relations:
- Links:
"""


CHANGELOG = """# Memory Changelog

## 2026-09-15 — Storage decided

- Notes stay Markdown files
  so any editor works.
- No database.

## 2026-09-14 - First rings

- Added the hot/warm/cold rings.

## not-a-date — ignored

- nothing
"""


ARCHIVED = """# Decisions Archive 2026-08

## DEC-20260801-009 Old choice

- Status: superseded
- Date: 2026-08-01
- Decision: Something old.
- Reason: Long ago.
- Relations:
- Links:
"""


class UiTestCase(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.root, True)
        with contextlib.redirect_stdout(io.StringIO()):
            ctx.main(["memory", "init", str(self.root)])
        memory = self.root / "memory"
        (memory / "decisions.md").write_text(DECISIONS, encoding="utf-8")
        (memory / "investigations.md").write_text(INVESTIGATIONS, encoding="utf-8")
        (memory / "changelog.md").write_text(CHANGELOG, encoding="utf-8")
        (memory / "archive" / "decisions" / "2026-08.md").write_text(ARCHIVED, encoding="utf-8")
        patcher = mock.patch.object(ctx, "collect_usage", return_value=None)
        patcher.start()
        self.addCleanup(patcher.stop)

    def collect(self, lang="ru", commits=None):
        with mock.patch.object(ctx, "_ui_git", return_value=commits or []):
            return ctx._ui_collect(self.root, "Demo", lang)

    def render(self, lang="ru", commits=None):
        return ctx.render_ui(self.collect(lang, commits))


def commit(date, subject, add=10, dele=2, sha="abc1234"):
    return {"hash": sha, "date": date, "subject": subject, "files": 1, "add": add, "del": dele}


class CollectTests(UiTestCase):
    def test_entries_carry_date_ring_relations_and_skip_templates(self):
        entries = {e["id"]: e for e in ctx._ui_entries(self.root / "memory")}
        self.assertEqual(set(entries), {"DEC-20260914-001", "DEC-20260915-002",
                                        "INV-20260914-001", "DEC-20260801-009"})
        self.assertEqual(entries["DEC-20260801-009"]["ring"], "cold")
        self.assertEqual(entries["DEC-20260801-009"]["date"], "2026-08-01")
        self.assertEqual(entries["DEC-20260914-001"]["ring"], "warm")
        self.assertEqual(entries["DEC-20260915-002"]["relations"],
                         [("supersedes", "DEC-20260914-001"), ("relates-to", "INV-20260914-001")])
        self.assertEqual(entries["INV-20260914-001"]["fields"]["conclusion"], "Use a typed field.")

    def test_changelog_accepts_dash_variants_and_joins_wrapped_bullets(self):
        changes = ctx._ui_changelog(self.root / "memory")
        self.assertEqual([c["date"] for c in changes], ["2026-09-15", "2026-09-14"])
        self.assertEqual(changes[0]["points"][0], "Notes stay Markdown files so any editor works.")
        self.assertEqual(changes[0]["title"], "Storage decided")

    def test_a_day_is_headed_by_its_changelog_then_its_entries_then_its_biggest_commit(self):
        chapters = {c["date"]: c for c in ctx._ui_chapters(
            ctx._ui_entries(self.root / "memory"), ctx._ui_changelog(self.root / "memory"),
            [commit("2026-09-14", "small fix", 1, 1), commit("2026-09-14", "big rewrite", 500, 400),
             commit("2026-09-20", "small only", 1, 0), commit("2026-09-20", "the largest", 90, 9)])}
        self.assertEqual(chapters["2026-09-14"]["headline"], "First rings")
        self.assertEqual(chapters["2026-09-15"]["headline"], "Storage decided")
        self.assertEqual(chapters["2026-09-20"]["headline"], "the largest")
        self.assertEqual(chapters["2026-09-14"]["commits"][0]["subject"], "big rewrite")
        self.assertEqual(chapters["2026-09-14"]["added"], 501)
        self.assertEqual(list(chapters), sorted(chapters))
        self.assertEqual(chapters["2026-09-14"]["weight"], 1 + 2 + 2)

    def test_rings_report_tokens_against_the_real_caps(self):
        rings = ctx._ui_rings(self.root / "memory")
        self.assertEqual(rings["hot"]["cap"], ctx.NOW_MAX_TOKENS)
        self.assertGreater(rings["warm"]["tokens"], 0)
        self.assertEqual(rings["cold"]["files"], 1)
        caps = {r["name"]: r["cap"] for r in rings["warm"]["rows"]}
        self.assertEqual(caps["architecture.md"], ctx.ARCHITECTURE_MAX_TOKENS)
        self.assertEqual(caps["decisions.md"], ctx.JOURNAL_MAX_TOKENS)

    @unittest.skipUnless(shutil.which("git"), "git is required")
    def test_git_history_is_read_with_sizes_and_local_dates(self):
        env = {**os.environ, "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@x",
               "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@x"}

        def git(*args, **extra):
            subprocess.run(["git", *args], cwd=self.root, check=True, capture_output=True,
                           env={**env, **extra})

        git("init", "-q")
        (self.root / "a.txt").write_text("one\ntwo\n", encoding="utf-8")
        git("add", "a.txt")
        git("commit", "-q", "-m", "first thing", GIT_AUTHOR_DATE="2026-09-01T12:00:00",
            GIT_COMMITTER_DATE="2026-09-01T12:00:00")
        (self.root / "a.txt").write_text("one\n", encoding="utf-8")
        git("add", "a.txt")
        git("commit", "-q", "-m", "second thing", GIT_AUTHOR_DATE="2026-09-02T12:00:00",
            GIT_COMMITTER_DATE="2026-09-02T12:00:00")
        commits = ctx._ui_git(self.root)
        self.assertEqual([c["subject"] for c in commits], ["second thing", "first thing"])
        self.assertEqual((commits[1]["date"], commits[1]["add"], commits[1]["files"]), ("2026-09-01", 2, 1))
        self.assertEqual((commits[0]["add"], commits[0]["del"]), (0, 1))

    def test_no_git_means_no_commits_not_an_error(self):
        self.assertEqual(ctx._ui_git(self.root), [])


class RenderTests(UiTestCase):
    def test_page_is_offline_and_has_no_external_resources(self):
        page = self.render(commits=[commit("2026-09-14", "c1")])
        self.assertTrue(page.startswith("<!doctype html>"))
        for needle in ("http://", "https://", "<link", "@import", "url(http", "src="):
            self.assertNotIn(needle, page)
        self.assertIn("default-src 'none'", page)

    def test_every_value_from_the_vault_is_escaped(self):
        page = self.render()
        self.assertNotIn("<script>alert(1)", page)
        self.assertIn("&lt;script&gt;alert(1)&lt;/script&gt; Storage", page)
        self.assertNotIn("<b>notes</b>", page)
        self.assertEqual(page.count("<script>"), 2)  # the two of our own

    def test_project_name_is_escaped_too(self):
        data = self.collect()
        data["title"] = '"><img onerror=x>'
        page = ctx.render_ui(data)
        self.assertNotIn("<img onerror", page)

    def test_chapters_stats_and_sections_reflect_the_data(self):
        page = self.render(commits=[commit("2026-09-14", "c1"), commit("2026-09-16", "c2")])
        for day in ("2026-09-14", "2026-09-15", "2026-09-16", "2026-08-01"):
            self.assertIn(f'id="ch-{day}"', page)
        self.assertLess(page.index('id="ch-2026-08-01"'), page.index('id="ch-2026-09-14"'))
        self.assertIn('id="rings"', page)
        self.assertIn('id="links"', page)      # DEC-002 declares relations
        self.assertNotIn('id="tokens"', page)  # no transcripts were found
        self.assertIn("memory check: замечаний нет", page)

    def test_russian_and_english_pages(self):
        ru, en = self.render("ru"), self.render("en")
        self.assertIn('<html lang="ru">', ru)
        self.assertIn("Хроника", ru)
        self.assertIn('<html lang="en">', en)
        self.assertIn("How the project grew.", en)
        self.assertNotIn("Хроника", en)

    def test_russian_plurals(self):
        forms = ("день", "дня", "дней")
        picked = {n: ctx._plural(n, forms, "ru") for n in (1, 2, 4, 5, 11, 12, 21, 22, 25, 111)}
        self.assertEqual(picked, {1: "день", 2: "дня", 4: "дня", 5: "дней", 11: "дней", 12: "дней",
                                  21: "день", 22: "дня", 25: "дней", 111: "дней"})
        self.assertEqual(ctx._plural(1, ("day", "days"), "en"), "day")
        self.assertEqual(ctx._plural(2, ("day", "days"), "en"), "days")

    def test_token_formatting_follows_the_language(self):
        self.assertEqual(ctx._tokens_text(620_040_000, "ru"), "620,04 млн")
        self.assertEqual(ctx._tokens_text(620_040_000, "en"), "620.04M")
        self.assertEqual(ctx._tokens_text(12_500, "en"), "12.5k")
        self.assertEqual(ctx._tokens_text(999, "ru"), "999")

    def test_output_is_deterministic(self):
        commits = [commit("2026-09-14", "c1")]
        self.assertEqual(self.render(commits=commits), self.render(commits=commits))

    def test_more_days_than_the_cap_collapse_into_one_earlier_chapter(self):
        commits = [commit(f"2026-{m:02d}-{d:02d}", f"c{m}{d}")
                   for m in (1, 2, 3, 4) for d in range(1, 29)]
        page = self.render(commits=commits)
        self.assertEqual(page.count('class="chapter reveal"'), ctx.UI_MAX_CHAPTERS + 1)
        self.assertIn('id="ch-earlier"', page)
        self.assertNotIn('id="ch-2026-01-01"', page)

    def chart(self, commits):
        data = self.collect(commits=commits)
        return data, ctx._activity_chart(data["chapters"], ctx.UI_TEXT["en"], "en")

    def test_activity_chart_stacks_each_days_events_by_kind(self):
        data, chart = self.chart([commit("2026-09-14", "c1"), commit("2026-09-14", "c2")])
        day = next(c for c in data["chapters"] if c["date"] == "2026-09-14")
        counts = ctx._day_counts(day)
        self.assertEqual((counts["COMMIT"], counts["DEC"], counts["INV"]), (2, 1, 1))
        column = re.search(r'<a class="col" href="#ch-2026-09-14".*?</a>', chart).group(0)
        self.assertIn('title="14 Sep: 1 change, 1 decision, 1 investigation, 2 commits"', column)
        # a segment's height is its share of the axis top, so a column adds up to its events
        axis_top = max(int(v) for v in re.findall(r'bottom:[\d.]+%">(\d+)</span>', chart))
        heights = [float(h) for h in re.findall(r"height:([\d.]+)%", column)]
        self.assertEqual(len(heights), 4)
        self.assertAlmostEqual(sum(heights) / 100 * axis_top, sum(counts.values()), places=1)

    def test_activity_chart_has_one_column_per_calendar_day_including_quiet_ones(self):
        _data, chart = self.chart([commit("2026-09-14", "c1"), commit("2026-09-18", "c2")])
        # the vault's archived 2026-08-01 falls outside the 45-day window and is reported
        self.assertIn(f"--n:{ctx.UI_CHART_DAYS}", chart)
        self.assertEqual(chart.count('<a class="col"'), 3)  # 14, 15 and 18 Sep have events
        self.assertEqual(chart.count('<span class="col"></span>'), ctx.UI_CHART_DAYS - 3)
        self.assertIn("1 day earlier", chart)

    def test_activity_chart_window_is_capped_and_says_what_it_left_out(self):
        commits = [commit(f"2026-{m:02d}-{d:02d}", f"c{m}{d}") for m in (1, 2, 3) for d in (1, 15)]
        data = self.collect(commits=commits)
        chart = ctx._activity_chart(data["chapters"], ctx.UI_TEXT["en"], "en")
        self.assertIn(f"--n:{ctx.UI_CHART_DAYS}", chart)
        self.assertIn("earlier", chart)
        for link in re.findall(r'href="#(ch-[\d-]+)"', chart):
            self.assertIn(f'id="{link}"', ctx.render_ui(data))

    def test_axis_ticks_are_whole_numbers_and_reach_the_peak(self):
        for peak in (0, 1, 3, 4, 5, 9, 11, 37, 120, 999, 1500):
            ticks = ctx._axis_ticks(peak)
            self.assertEqual(ticks[0], 0)
            self.assertGreaterEqual(ticks[-1], peak)
            self.assertLessEqual(len(ticks), 5)
            self.assertEqual(len({b - a for a, b in zip(ticks, ticks[1:])}), 1)

    def test_chart_labels_are_escaped_and_no_tree_ring_art_remains(self):
        page = self.render(commits=[commit("2026-09-14", "c1")])
        self.assertIn('class="chart"', page)
        for gone in ("tree-ring", "core-pin", "data-mid", "radialGradient"):
            self.assertNotIn(gone, page)

    def test_empty_project_shows_a_pointer_not_a_crash(self):
        shutil.rmtree(self.root / "memory")
        (self.root / ".git").mkdir()
        page = self.render()
        self.assertIn("Хроника пуста", page)
        self.assertNotIn('id="rings"', page)
        self.assertNotIn('id="links"', page)

    def test_tokens_section_and_cost_appear_only_with_data_and_prices(self):
        usage = {"dir": "x", "cache_share": 0.9,
                 "totals": {"input": 100, "cache_write": 1_000, "cache_read": 900_000, "output": 5_000,
                            "turns": 3, "subagent_turns": 0, "peak_context": 300_000},
                 "sessions": [{"id": "abcdef123456", "turns": 3, "subagent_turns": 0, "peak_context": 300_000,
                               "input": 100, "cache_write": 1_000, "cache_read": 900_000, "output": 5_000,
                               "first": "2026-09-01T10:00:00Z", "last": "2026-09-01T11:00:00Z"}]}
        with mock.patch.object(ctx, "collect_usage", return_value=usage):
            page = self.render()
            self.assertIn('id="tokens"', page)
            self.assertIn("abcdef12", page)
            self.assertIn("90,0% входных токенов", page)
            self.assertIn('class="stack"', page)  # the share bar
            self.assertIn("99,3%", page)          # cache read: 900000 of 906100
            self.assertNotIn("$", page)
            ctx._config_write(self.root, {"prices": {"input": 1, "cache_write": 1, "cache_read": 1, "output": 1}})
            self.assertIn("$0.91", self.render())


class UiCommandTests(UiTestCase):
    def run_cli(self, *argv):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = ctx.main(list(argv))
        return code, out.getvalue(), err.getvalue()

    def test_writes_the_default_page_and_reports_what_it_used(self):
        code, out, _ = self.run_cli("ui", "--path", str(self.root))
        self.assertEqual(code, 0)
        page = (self.root / ".arbor" / "ui" / "index.html").read_text(encoding="utf-8")
        self.assertIn(f"<title>{self.root.name} —", page)
        self.assertIn("no LLM", out)

    def test_title_language_and_output_path_are_options(self):
        target = self.root / "out" / "page.html"
        code, _, _ = self.run_cli("ui", "--path", str(self.root), "--title", "Arbor & Co",
                                  "--lang", "en", "--out", str(target))
        self.assertEqual(code, 0)
        page = target.read_text(encoding="utf-8")
        self.assertIn("Arbor &amp; Co", page)
        self.assertIn('lang="en"', page)

    def test_open_flag_launches_the_browser_with_a_file_url(self):
        with mock.patch.object(ctx.webbrowser, "open") as opened:
            self.run_cli("ui", "--path", str(self.root), "--open")
        self.assertTrue(opened.call_args.args[0].startswith("file:///"))

    def test_refuses_a_folder_with_neither_memory_nor_history(self):
        bare = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, bare, True)
        code, _, err = self.run_cli("ui", "--path", bare)
        self.assertEqual(code, 2)
        self.assertIn("nothing to show", err)


if __name__ == "__main__":
    unittest.main()
