"""Summaries: the cache key, what a story shows while its summary is rewritten, and how a timeout is handled.
The model itself is never run: _generate is replaced."""
import json, subprocess, sys, tempfile, time, unittest
from datetime import datetime, timedelta
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import summaries as S


def member(i, lean, title=None, source=None):
    return {"source": source or f"Outlet{i}", "lean": lean, "title": title or f"Headline {i}", "text": "Some excerpt text.",
            "when": datetime(2026, 11, 17, 8, 0) + timedelta(minutes=i)}


def story(sid, leans=("left", "center", "right"), **kw):
    st = {"sid": sid, "members": [member(i, l) for i, l in enumerate(leans)]}
    st.update(kw)
    return st


class Env(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        d = Path(self.tmp.name)
        (d / "bin").write_text("x"); (d / "model.gguf").write_text("x")
        self.hist = d / "hist"; self.hist.mkdir()
        self.settings = {"summaries": True, "summary_bin": str(d / "bin"), "summary_model": str(d / "model.gguf"),
                         "summary_per_build": 3, "summary_budget_s": 600}
        self.model = d / "model.gguf"
        self.prompt = S.PROMPT_FILE.read_text().strip()

    def cache(self):
        p = self.hist / "summaries.json"
        return json.loads(p.read_text()) if p.exists() else {}

    def put(self, entries):
        (self.hist / "summaries.json").write_text(json.dumps(entries))

    def entry(self, text="Something happened.", sid=None, ago=3600, ok=True):
        e = {"text": text, "ok": ok, "problems": [] if ok else ["empty"], "model": "model.gguf", "at": int(time.time()) - ago}
        if sid:
            e["sid"] = sid
        return e


class KeyTests(Env):
    def test_reworded_headline_keeps_the_key(self):
        a, b = story("s1"), story("s1")
        b["members"][0]["title"] = "A different headline"
        self.assertEqual(S._story_key(a["members"], self.prompt, self.model, "s1"), S._story_key(b["members"], self.prompt, self.model, "s1"))

    def test_more_outlets_on_a_covered_side_keep_the_key(self):
        a, b = story("s1"), story("s1", leans=("left", "center", "right", "left", "right"))
        self.assertEqual(S._story_key(a["members"], self.prompt, self.model, "s1"), S._story_key(b["members"], self.prompt, self.model, "s1"))

    def test_a_new_side_changes_the_key(self):
        a, b = story("s1", leans=("left", "right")), story("s1", leans=("left", "right", "center"))
        self.assertNotEqual(S._story_key(a["members"], self.prompt, self.model, "s1"), S._story_key(b["members"], self.prompt, self.model, "s1"))

    def test_without_an_id_the_excerpts_decide(self):
        a, b = story("s1"), story("s1")
        b["members"][0]["title"] = "A different headline"
        self.assertNotEqual(S._story_key(a["members"], self.prompt, self.model), S._story_key(b["members"], self.prompt, self.model))


class AttachTests(Env):
    def test_story_keeps_its_earlier_summary_while_a_new_one_is_missing(self):
        self.put({"oldkey": self.entry("Earlier version.", sid="s1")})
        st = story("s1")
        with mock.patch.object(S, "_generate", side_effect=AssertionError("must not run")):
            S.attach([st], self.settings, self.hist, per_build=0)
        self.assertEqual(st["summary"]["text"], "Earlier version.")

    def test_earlier_summary_is_not_shown_after_two_days(self):
        self.put({"oldkey": self.entry("Ancient.", sid="s1", ago=3 * 86400)})
        st = story("s1")
        S.attach([st], self.settings, self.hist, per_build=0)
        self.assertNotIn("summary", st)

    def test_a_summary_from_the_old_key_scheme_is_adopted(self):
        st = story("s1")
        legacy = S._story_key(st["members"], self.prompt, self.model)
        self.put({legacy: self.entry("Legacy.")})
        with mock.patch.object(S, "_generate", side_effect=AssertionError("must not run")):
            S.attach([st], self.settings, self.hist, per_build=0)
        self.assertEqual(st["summary"]["text"], "Legacy.")
        self.assertEqual(self.cache()[S._story_key(st["members"], self.prompt, self.model, "s1")]["sid"], "s1")

    def test_new_summary_is_written_and_cached_under_the_story_id(self):
        st = story("s1")
        text = "Mary won the race. It flips the seat."
        with mock.patch.object(S, "_generate", return_value=text), mock.patch.object(S, "check", return_value=[]):
            made = S.attach([st], self.settings, self.hist, per_build=3)
        self.assertEqual(made, 1)
        self.assertEqual(st["summary"]["text"], text)
        self.assertEqual(self.cache()[S._story_key(st["members"], self.prompt, self.model, "s1")]["sid"], "s1")

    def test_timeout_is_remembered_and_the_story_rests(self):
        st = story("s1")
        boom = subprocess.TimeoutExpired("llama", 420)
        with mock.patch.object(S, "_generate", side_effect=boom) as gen:
            S.attach([st], self.settings, self.hist, per_build=3)
            self.assertEqual(gen.call_count, 1)
            S.attach([story("s1")], self.settings, self.hist, per_build=3)  # straight away again: it is resting
            self.assertEqual(gen.call_count, 1)
        fails = json.loads((self.hist / "summary_fails.json").read_text())
        self.assertEqual(list(fails.values())[0]["n"], 1)

    def test_a_resting_story_does_not_use_the_slot_of_the_next_one(self):
        a, b = story("s1"), story("s2")
        ka = S._story_key(a["members"], self.prompt, self.model, "s1")
        (self.hist / "summary_fails.json").write_text(json.dumps({ka: {"n": 1, "at": int(time.time())}}))
        with mock.patch.object(S, "_generate", return_value="One sentence here.") as gen, mock.patch.object(S, "check", return_value=[]):
            S.attach([a, b], self.settings, self.hist, per_build=1)
        self.assertEqual(gen.call_count, 1)
        self.assertIn("summary", b)
        self.assertNotIn("summary", a)

    def test_backoff_grows_and_is_capped(self):
        now = int(time.time())
        self.assertTrue(S._backed_off({"n": 1, "at": now - 5 * 60}, now))
        self.assertFalse(S._backed_off({"n": 1, "at": now - 11 * 60}, now))
        self.assertTrue(S._backed_off({"n": 3, "at": now - 30 * 60}, now))
        self.assertFalse(S._backed_off({"n": 30, "at": now - 6 * 3600 - 1}, now))

    def test_a_failed_check_is_retried_later_not_forever_and_not_at_once(self):
        st = story("s1")
        k = S._story_key(st["members"], self.prompt, self.model, "s1")
        self.put({k: self.entry("Bad.", sid="s1", ago=600, ok=False)})
        with mock.patch.object(S, "_generate", side_effect=AssertionError("too soon")):
            S.attach([st], self.settings, self.hist, per_build=3)
        self.put({k: self.entry("Bad.", sid="s1", ago=3 * 3600, ok=False)})
        with mock.patch.object(S, "_generate", return_value="Better one.") as gen, mock.patch.object(S, "check", return_value=[]):
            S.attach([story("s1")], self.settings, self.hist, per_build=3)
        self.assertEqual(gen.call_count, 1)

    def test_saving_keeps_what_another_run_wrote_meanwhile(self):
        now = int(time.time())
        S._save_cache(self.hist / "summaries.json", {"a": self.entry("A.")}, now)
        S._save_cache(self.hist / "summaries.json", {"b": self.entry("B.")}, now)  # this run never loaded "a"
        self.assertEqual(set(self.cache()), {"a", "b"})

    def test_latest_by_sid_picks_the_newest_passing_summary_per_story(self):
        self.put({
            "a": self.entry("Old.", sid="s1", ago=7200),
            "b": self.entry("New.", sid="s1", ago=60),
            "c": self.entry("Failed check.", sid="s1", ago=10, ok=False),
            "d": self.entry("Other story.", sid="s2"),
            "e": self.entry("No id."),
        })
        got = S.latest_by_sid(self.hist)
        self.assertEqual({k: v["text"] for k, v in got.items()}, {"s1": "New.", "s2": "Other story."})

    def test_latest_by_sid_with_no_cache_is_empty(self):
        self.assertEqual(S.latest_by_sid(self.hist), {})

    def test_per_build_zero_never_runs_the_model(self):
        with mock.patch.object(S, "_generate", side_effect=AssertionError("must not run")):
            S.attach([story("s1"), story("s2")], self.settings, self.hist, per_build=0)


if __name__ == "__main__":
    unittest.main()
