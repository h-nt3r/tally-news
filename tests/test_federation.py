import unittest
import xml.etree.ElementTree as ET
from datetime import datetime, timezone

import federation

T = datetime(2026, 11, 14, 12, 0, tzinfo=timezone.utc)


def story(sid="abc", label="A & B <story>", summary=None):
    members = [{"source": "Left Paper", "lean": "left", "when": T, "link": "https://l.example/a?x=1&y=2"},
               {"source": "Right Daily", "lean": "right", "when": T.replace(minute=30), "link": "https://r.example/a"}]
    st = {"sid": sid, "label": label, "members": members, "newest": T.replace(minute=30), "topic": "us"}
    if summary:
        st["summary"] = {"text": summary, "model": "m"}
    return st


class FeedFor(unittest.TestCase):
    def test_mastodon_handle(self):
        self.assertEqual(federation.feed_for("@Mastodon@mastodon.social"), "https://mastodon.social/@Mastodon.rss")

    def test_mastodon_profile_and_tag(self):
        self.assertEqual(federation.feed_for("https://mastodon.social/@Mastodon"), "https://mastodon.social/@Mastodon.rss")
        self.assertEqual(federation.feed_for("#breakingnews@mastodon.social"), "https://mastodon.social/tags/breakingnews.rss")
        self.assertEqual(federation.feed_for("https://mastodon.social/tags/news"), "https://mastodon.social/tags/news.rss")

    def test_bluesky(self):
        self.assertEqual(federation.feed_for("bsky.app/profile/nytimes.com"), "https://bsky.app/profile/nytimes.com/rss")
        self.assertEqual(federation.feed_for("https://bsky.app/profile/nytimes.com/rss"), "https://bsky.app/profile/nytimes.com/rss")

    def test_not_ours(self):
        for t in ("@somechannel", "https://www.youtube.com/@somechannel", "https://example.com/feed", "", "news site"):
            self.assertIsNone(federation.feed_for(t), t)

    def test_social_feed_detection(self):
        self.assertTrue(federation.is_social_feed("https://mastodon.social/@Mastodon.rss"))
        self.assertTrue(federation.is_social_feed("https://bsky.app/profile/x.com/rss"))
        self.assertFalse(federation.is_social_feed("https://www.theguardian.com/us-news/rss"))

    def test_title_from_post(self):
        self.assertEqual(federation.title_from_post("  short\n post "), "short post")
        long = federation.title_from_post("word " * 80)
        self.assertLessEqual(len(long), 141)
        self.assertTrue(long.endswith("…"))


class Atom(unittest.TestCase):
    def test_well_formed_and_escaped(self):
        xml = federation.atom("Tally & Co", "sub", "https://x.example/", "feed.xml", [story(summary="It <happened> & more.")], T)
        root = ET.fromstring(xml)  # parses: every special character was escaped
        ns = {"a": "http://www.w3.org/2005/Atom"}
        entry = root.find("a:entry", ns)
        self.assertEqual(entry.find("a:title", ns).text, "A & B <story>")
        self.assertEqual(entry.find("a:id", ns).text, "https://x.example/story/abc.html")
        content = entry.find("a:content", ns).text
        self.assertIn("can be wrong", content)
        self.assertIn("It <happened> & more.", content)
        related = [l.get("href") for l in entry.findall("a:link", ns) if l.get("rel") == "related"]
        self.assertEqual(related, ["https://l.example/a?x=1&y=2", "https://r.example/a"])

    def test_no_summary_still_valid_and_labels_machine_text_only_when_present(self):
        xml = federation.atom("T", "s", "https://x.example/", "feed.xml", [story()], T)
        self.assertNotIn("Machine-written", xml)

    def test_stories_without_page_are_left_out(self):
        s = story()
        s["sid"] = ""
        root = ET.fromstring(federation.atom("T", "s", "https://x.example/", "feed.xml", [s], T))
        self.assertEqual(root.findall("{http://www.w3.org/2005/Atom}entry"), [])


class Opml(unittest.TestCase):
    def test_grouped_by_topic_with_sides(self):
        cfg = {"feeds": [{"name": "A & B", "url": "https://a.example/rss", "lean": "left", "topic": "us"},
                         {"name": "Page", "url": "https://p.example/news", "lean": "center", "topic": "world", "method": "page"}]}
        root = ET.fromstring(federation.opml("T", cfg))
        outlines = root.findall(".//outline[@type]")
        self.assertEqual(outlines[0].get("xmlUrl"), "https://a.example/rss")
        self.assertEqual(outlines[0].get("{https://github.com/h-nt3r/tally-news}side"), "left")
        self.assertEqual(outlines[1].get("url"), "https://p.example/news")
        self.assertIsNone(outlines[1].get("xmlUrl"))


if __name__ == "__main__":
    unittest.main()
