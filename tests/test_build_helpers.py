"""Tests for the small helpers that draw story pages. Run: .venv/bin/python -m unittest discover tests"""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import build


class DiffTests(unittest.TestCase):
    def test_only_the_changed_words_are_marked(self):
        old, new = build.diff_words("Democrats block budget bill in surprise vote", "Democrats stall budget bill in procedural vote")
        self.assertEqual(old, "Democrats <del>block</del> budget bill in <del>surprise</del> vote")
        self.assertEqual(new, "Democrats <ins>stall</ins> budget bill in <ins>procedural</ins> vote")

    def test_adding_punctuation_does_not_mark_the_whole_word(self):
        old, new = build.diff_words("Senate passes bill after overnight session", "Senate passes bill after marathon overnight session, 51-49")
        self.assertEqual(old, "Senate passes bill after overnight session")
        self.assertEqual(new, "Senate passes bill after <ins>marathon</ins> overnight session<ins>, 51-49</ins>")

    def test_markup_in_a_headline_is_escaped(self):
        old, new = build.diff_words("A <b>bold</b> claim", "A <i>new</i> claim")
        self.assertNotIn("<b>", old + new)
        self.assertNotIn("<i>", old + new)

    def test_identical_headlines_have_no_marks(self):
        old, new = build.diff_words("Same headline", "Same headline")
        self.assertEqual((old, new), ("Same headline", "Same headline"))


class TickTests(unittest.TestCase):
    def test_thirty_hours_gets_six_hour_ticks(self):
        self.assertEqual([t[1] for t in build.tick_steps(30 * 3600)], ["+6 h", "+12 h", "+18 h", "+24 h"])

    def test_three_days_gets_twelve_hour_ticks_that_stay_off_the_edges(self):
        ticks = build.tick_steps(3 * 86400)
        self.assertEqual([t[1] for t in ticks], ["+12 h", "+24 h", "+36 h", "+48 h", "+60 h"])
        self.assertTrue(all(0.08 < p < 0.92 for p, _ in ticks))

    def test_a_story_that_all_happened_in_one_instant_has_no_ticks(self):
        self.assertEqual(build.tick_steps(1), [])


class FirstReportedTests(unittest.TestCase):
    def facts(self, gap_minutes):
        from datetime import datetime, timedelta, timezone
        import analytics
        t0 = datetime(2026, 11, 9, 12, 0, tzinfo=timezone.utc)
        members = [{"source": "A", "lean": "left", "title": "x", "when": t0},
                   {"source": "A", "lean": "left", "title": "x again", "when": t0 + timedelta(minutes=1)},
                   {"source": "B", "lean": "right", "title": "y", "when": t0 + timedelta(minutes=gap_minutes)}]
        return analytics.story_facts(members)

    def test_a_lead_inside_the_check_gap_is_called_too_close(self):
        self.assertIn("Too close to call", build.facts_sentence(self.facts(5), []))

    def test_a_clear_lead_names_the_next_outlet_instead(self):
        line = build.facts_sentence(self.facts(45), [])
        self.assertNotIn("Too close", line)
        self.assertIn("Next: B", line)

    def test_the_next_outlet_is_a_different_one(self):
        self.assertEqual(self.facts(30)["next"]["source"], "B")


class MergeRelatedTests(unittest.TestCase):
    def story(self, topic, titles, lean="center"):
        from datetime import datetime, timezone
        members = [{"source": f"{topic}{n}", "lean": lean, "topic": topic, "title": t, "buzz": build.NO_BUZZ, "link": f"https://x/{topic}/{t}",
                    "when": datetime(2026, 11, 9, 12, n, tzinfo=timezone.utc)} for n, t in enumerate(titles)]
        return build.make_story(members, {"left", "center", "right"})

    def test_the_same_event_filed_under_two_topics_becomes_one_story(self):
        us = self.story("us", ["Russell Brand sentenced to prison for rape", "Russell Brand jailed over sexual assault"])
        world = self.story("world", ["Russell Brand sentenced to over 10 years for rape and assault", "British comedian Russell Brand sentenced"])
        other = self.story("us", ["Senate passes farm bill after long debate", "Farm bill clears the Senate"])
        out = build.merge_related({"us": [us, other], "world": [world], "tech": []}, [], 0.78)
        self.assertEqual(sum(len(v) for v in out.values()), 2)
        brand = [s for v in out.values() for s in v if "Brand" in s["members"][0]["title"] or "Brand" in s["members"][-1]["title"]][0]
        self.assertEqual(len(brand["members"]), 4)

    def test_unrelated_stories_stay_apart(self):
        a = self.story("us", ["Court allows border wall construction", "Justices clear way for border wall"])
        b = self.story("us", ["Meta expands Instagram age guessing worldwide", "Instagram expands AI age checks"])
        out = build.merge_related({"us": [a, b], "world": [], "tech": []}, [], 0.78)
        self.assertEqual(len(out["us"]), 2)

    def test_threshold_zero_turns_it_off(self):
        a = self.story("us", ["Nvidia CEO admits affair", "Nvidia CEO affair investigation"])
        b = self.story("world", ["Nvidia CEO affair probe", "Why the Nvidia CEO affair matters"])
        out = build.merge_related({"us": [a], "world": [b], "tech": []}, [], 0)
        self.assertEqual((len(out["us"]), len(out["world"])), (1, 1))


class SourceHealthTests(unittest.TestCase):
    def cfg(self, **flags):
        return {"feeds": [dict({"name": "F"}, **flags)], "channels": [dict({"name": "C"}, **flags)]}

    def test_a_working_source_is_ok_and_has_no_streak(self):
        h = build.source_health(self.cfg(_n=3, _total=9), 1_700_000_000, {})
        self.assertEqual((h["a:F"]["status"], h["a:F"]["builds"], h["a:F"]["since"]), ("ok", 0, None))

    def test_failures_are_counted_in_a_row_and_remember_when_they_began(self):
        first = build.source_health(self.cfg(_err="HTTP Error 403: Forbidden"), 1_700_000_000, {})
        self.assertEqual((first["a:F"]["status"], first["a:F"]["builds"]), ("failed", 1))
        second = build.source_health(self.cfg(_err="HTTP Error 403: Forbidden"), 1_700_001_200, first)
        self.assertEqual(second["a:F"]["builds"], 2)
        self.assertEqual(second["a:F"]["since"], first["a:F"]["since"])

    def test_recovery_resets_the_streak(self):
        bad = build.source_health(self.cfg(_err="x"), 1_700_000_000, {})
        good = build.source_health(self.cfg(_n=1, _total=1), 1_700_001_200, bad)
        self.assertEqual((good["a:F"]["status"], good["a:F"]["builds"]), ("ok", 0))

    def test_loaded_but_old_is_quiet_and_an_empty_feed_is_empty(self):
        self.assertEqual(build.source_health(self.cfg(_n=0, _total=5), 1, {})["a:F"]["status"], "quiet")
        self.assertEqual(build.source_health(self.cfg(_n=0, _total=0), 1, {})["a:F"]["status"], "empty")
        self.assertEqual(build.source_health(self.cfg(_n=0), 1, {})["v:C"]["status"], "quiet")  # a channel with no new videos is just quiet


class LatestDataTests(unittest.TestCase):
    def test_tracking_parameters_are_dropped_and_real_ones_kept(self):
        self.assertEqual(build.clean_link("https://x.test/a?utm_source=rss&id=7&fbclid=z"), "https://x.test/a?id=7")
        self.assertEqual(build.clean_link("https://x.test/a"), "https://x.test/a")
        self.assertEqual(build.clean_link("https://x.test/a?utm_medium=x"), "https://x.test/a")

    def test_the_headline_file_is_compact_and_indexes_outlets_once(self):
        import json
        rows = [("https://a.test/1?utm_x=1", "A", "left", "commercial", "us", "One", 200, "abc123"),
                ("https://a.test/2", "A", "left", "commercial", "world", "Two", 100, None)]
        d = json.loads(build.headlines_json(rows, 3))
        self.assertEqual(d["sources"], [["A", "left", "commercial"]])
        self.assertEqual(d["items"][0], [200, 0, 0, "One", "https://a.test/1", "abc123"])
        self.assertEqual(d["items"][1][2:], [1, "Two", "https://a.test/2", ""])

    def test_the_archive_returns_everything_recent_newest_first_including_one_outlet_items(self):
        import sqlite3
        import time
        import archive
        conn = sqlite3.connect(":memory:")
        conn.executescript(archive.SCHEMA)
        now = int(time.time())
        for i, (age, sid) in enumerate([(100, None), (50, "s1"), (10 ** 7, None)]):
            conn.execute("INSERT INTO articles(url, source, lean, topic, title, published, first_seen, last_seen, story_id, type) VALUES(?,?,?,?,?,?,?,?,?,?)",
                         (f"u{i}", "A", "left", "us", f"t{i}", now - age, now, now, sid, ""))
        rows = archive.headlines_since(conn, now - 1000)
        self.assertEqual([r[5] for r in rows], ["t1", "t0"])  # the old one is out, the newest is first
        self.assertEqual(rows[1][7], None)  # an item no story claimed is still there


if __name__ == "__main__":
    unittest.main()


class SummaryHtmlTests(unittest.TestCase):
    def test_no_summary_means_no_block(self):
        self.assertEqual(build.summary_html(None), "")

    def test_summary_is_escaped_and_always_labelled_machine_written(self):
        h = build.summary_html({"text": "A <b>won</b> & B lost.", "model": "m"}, "../")
        self.assertIn("A &lt;b&gt;won&lt;/b&gt; &amp; B lost.", h)
        self.assertIn("Machine-written", h)
        self.assertIn('href="../methods.html#summaries"', h)
