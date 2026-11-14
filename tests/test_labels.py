"""Tests for the neutral story label (no single outlet's headline stands in for the story).
Run: .venv/bin/python -m unittest discover tests"""
import sys
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import analytics

T0 = datetime(2026, 11, 9, 12, 0, tzinfo=timezone.utc)


def m(source, title, minutes=0):
    return {"source": source, "title": title, "lean": "center", "when": T0 + timedelta(minutes=minutes)}


DANA = [m("The Guardian", "Donald Trump 'kidding' about making UFC boss Dana White US press secretary", 0),
        m("PBS", "Trump says idea to make UFC's Dana White his press secretary 'just a little fun'", 30),
        m("Fox", "Trump says he was 'only kidding' about making Dana White press secretary", 60),
        m("CBS", "Trump says he was kidding when he offered UFC CEO press secretary role", 90)]


class LabelTests(unittest.TestCase):
    def test_the_label_is_the_words_the_headlines_share(self):
        label, kind, src = analytics.story_label(DANA)
        self.assertEqual(kind, "shared")
        self.assertIsNone(src)
        for word in ("Trump", "press secretary", "Dana White"):
            self.assertIn(word, label)

    def test_the_label_is_not_any_one_outlets_headline(self):
        label = analytics.story_label(DANA)[0]
        self.assertNotIn(label, [x["title"] for x in DANA])

    def test_when_nothing_is_shared_it_uses_the_earliest_headline_and_names_the_outlet(self):
        label, kind, src = analytics.story_label([m("NPR", "Judge rejects dismissal bid", 0), m("Fox", "Flooding hits coastal town overnight", 5)])
        self.assertEqual((label, kind, src), ("Judge rejects dismissal bid", "earliest", "NPR"))

    def test_one_headline_per_outlet_so_reprints_do_not_count_twice(self):
        base = [m("A", "Senate passes budget bill overnight", 0), m("A", "Senate passes budget bill overnight", 5),
                m("B", "Rain falls on the city", 10)]
        self.assertEqual(analytics.story_label(base)[1], "earliest")  # the duplicate from A is not a second outlet

    def test_the_label_is_short(self):
        long_heads = [m(f"O{i}", "alpha bravo charlie delta echo foxtrot golf hotel india juliet kilo lima mike", i) for i in range(4)]
        words = [w for w in analytics.story_label(long_heads)[0].split() if w != "\u00b7"]  # count real words, not the dots between phrases
        self.assertLessEqual(len(words), 7)

    def test_the_label_does_not_depend_on_input_order(self):
        a = analytics.story_label(DANA)[0]
        b = analytics.story_label(list(reversed(DANA)))[0]
        self.assertEqual(a, b)

    def test_it_starts_with_a_capital_letter(self):
        label = analytics.story_label([m("A", "judge denies motion to dismiss case"), m("B", "judge denies motion to dismiss")])[0]
        self.assertTrue(label[0].isupper())


if __name__ == "__main__":
    unittest.main()
