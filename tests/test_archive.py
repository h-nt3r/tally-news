"""Tests for the archive: stable story ids, splits and merges, headline edits, expiry.
Run from the project folder:  .venv/bin/python -m unittest discover tests
"""
import sqlite3
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import archive

T0 = datetime(2026, 11, 9, 12, 0, tzinfo=timezone.utc)


def art(n, title=None, lean="center", minutes=0):
    return {"link": f"https://example.com/{n}", "title": title or f"Headline {n}", "source": f"Outlet {n}",
            "lean": lean, "topic": "us", "when": T0 + timedelta(minutes=minutes)}


def story(*articles):
    return {"members": list(articles)}


class ArchiveTests(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.path = Path(self.dir.name) / "archive.sqlite"
        self.t = 1_000_000

    def tearDown(self):
        self.dir.cleanup()

    def build(self, *stories, extra=()):
        self.t += 1200
        members = [m for s in stories for m in s["members"]]
        out = archive.record_build(self.path, self.t, members + list(extra), {"us": (list(stories), [])})
        return out

    def test_same_story_keeps_its_id_as_outlets_join(self):
        s1 = story(art(1), art(2), art(3))
        self.build(s1)
        first = s1["sid"]
        s2 = story(art(1), art(2), art(3), art(4))
        self.build(s2)
        self.assertEqual(s2["sid"], first)

    def test_a_new_cluster_gets_a_new_id(self):
        a, b = story(art(1), art(2)), story(art(10), art(11))
        self.build(a, b)
        self.assertNotEqual(a["sid"], b["sid"])

    def test_when_a_story_splits_the_larger_part_keeps_the_id(self):
        big = story(*[art(n) for n in range(1, 6)])
        self.build(big)
        original = big["sid"]
        part1, part2 = story(art(1), art(2), art(3)), story(art(4), art(5))
        self.build(part1, part2)
        self.assertEqual(part1["sid"], original)
        self.assertNotEqual(part2["sid"], original)

    def test_when_two_stories_merge_the_better_overlap_wins_and_nothing_breaks(self):
        a, b = story(art(1), art(2), art(3)), story(art(10), art(11))
        self.build(a, b)
        merged = story(art(1), art(2), art(3), art(10), art(11))
        self.build(merged)
        self.assertEqual(merged["sid"], a["sid"])
        conn = sqlite3.connect(self.path)
        self.assertEqual(conn.execute("SELECT COUNT(*) FROM stories").fetchone()[0], 2)  # both remain in the archive

    def test_two_clusters_never_share_an_id_in_one_build(self):
        s = story(art(1), art(2), art(3), art(4))
        self.build(s)
        x, y = story(art(1), art(2)), story(art(3), art(4))
        self.build(x, y)
        self.assertNotEqual(x["sid"], y["sid"])

    def test_a_changed_headline_is_counted_and_both_versions_kept(self):
        self.build(story(art(1, "Original headline"), art(2)))
        out = self.build(story(art(1, "Edited headline"), art(2)))
        self.assertEqual(out["edits"], 1)
        conn = sqlite3.connect(self.path)
        versions = [r[0] for r in conn.execute("SELECT title FROM titles WHERE url='https://example.com/1' ORDER BY first_seen")]
        self.assertEqual(sorted(versions), ["Edited headline", "Original headline"])
        self.assertEqual(conn.execute("SELECT title FROM articles WHERE url='https://example.com/1'").fetchone()[0], "Edited headline")

    def test_recent_edits_lists_edited_articles_even_outside_stories(self):
        self.build(story(art(1), art(2)), extra=[art(9, "Loose headline")])
        self.build(story(art(1), art(2)), extra=[art(9, "Loose headline, corrected")])
        found = archive.recent_edits(self.path, 0)
        self.assertEqual([e["url"] for e in found], ["https://example.com/9"])
        self.assertEqual(len(found[0]["versions"]), 2)
        self.assertEqual(archive.recent_edits(self.path, self.t + 1), [])  # nothing edited after that time

    def test_a_story_can_be_read_back_with_every_report_and_its_edits(self):
        s = story(art(1, "Before", minutes=0), art(2, lean="left", minutes=30))
        self.build(s)
        s2 = story(art(1, "After", minutes=0), art(2, lean="left", minutes=30), art(3, lean="right", minutes=90))
        self.build(s2)
        conn = archive.open_archive(self.path)
        rec = archive.story_record(conn, s["sid"])
        self.assertEqual([r["outlet"] for r in rec["reports"]], ["Outlet 1", "Outlet 2", "Outlet 3"])  # in publish order
        self.assertEqual(len(rec["reports"][0]["versions"]), 2)
        self.assertEqual(rec["reports"][1]["versions"], [])
        self.assertEqual(rec["first_published"], int(T0.timestamp()))
        self.assertEqual(rec["changed_at"], self.t)  # the last build changed it (a new report joined, a headline changed)
        self.assertIsNone(archive.story_record(conn, "nope"))
        listing = archive.story_listing(conn, 0)
        self.assertEqual(len(listing), 1)
        self.assertEqual(listing[0][5:9], (3, 1, 1, 1))  # outlets, then left, center, right

    def test_observations_are_only_written_when_a_story_changes_shape(self):
        s = story(art(1), art(2))
        self.build(s)
        self.build(story(art(1), art(2)))
        conn = sqlite3.connect(self.path)
        self.assertEqual(conn.execute("SELECT COUNT(*) FROM observations").fetchone()[0], 1)
        self.build(story(art(1), art(2), art(3)))
        self.assertEqual(conn.execute("SELECT COUNT(*) FROM observations").fetchone()[0], 2)

    def test_matched_posts_come_back_with_the_story_and_count_as_a_change(self):
        s = story(art(1), art(2))
        self.build(s)
        conn = archive.open_archive(self.path)
        before = archive.story_record(conn, s["sid"])["changed_at"]
        post = {"platform": "bluesky", "source": "AP", "handle": "apnews.com", "url": "https://bsky.app/p/1", "text": "clip about it",
                "when": T0 + timedelta(minutes=5), "video": True}
        self.t += 1200
        archive.record_posts(self.path, self.t, [post], [(post, s, 0.5)])
        rec = archive.story_record(conn, s["sid"])
        self.assertEqual([p["url"] for p in rec["posts"]], ["https://bsky.app/p/1"])
        self.assertTrue(rec["posts"][0]["video"])
        self.assertGreater(rec["changed_at"], before)

    def test_a_clips_media_survives_the_archive_and_unused_posters_can_be_listed(self):
        s = story(art(1), art(2))
        self.build(s)
        media = {"kind": "hls", "src": "https://video.example/p.m3u8", "poster": "https://x/t.jpg", "poster_local": "clips/abc.jpg", "w": 1080, "h": 1920}
        post = {"platform": "bluesky", "source": "AP", "handle": "apnews.com", "url": "https://bsky.app/p/9", "text": "clip", "when": T0,
                "video": True, "media": media}
        archive.record_posts(self.path, self.t, [post], [(post, s, 0.5)])
        conn = archive.open_archive(self.path)
        got = archive.story_record(conn, s["sid"])["posts"][0]["media"]
        self.assertEqual(got["src"], "https://video.example/p.m3u8")
        self.assertEqual(got["poster_local"], "clips/abc.jpg")
        self.assertEqual(archive.recent_posters(self.path, 0), {"clips/abc.jpg"})
        self.assertEqual(archive.recent_posters(self.path, self.t + 10), set())

    def test_an_older_archive_without_the_media_column_is_upgraded(self):
        conn = sqlite3.connect(self.path)
        conn.execute("CREATE TABLE posts(url TEXT PRIMARY KEY, platform TEXT, source TEXT, handle TEXT, text TEXT, published INTEGER, "
                     "first_seen INTEGER, last_seen INTEGER, video INTEGER)")
        conn.commit(); conn.close()
        conn = archive.open_archive(self.path)
        self.assertIn("media_json", [r[1] for r in conn.execute("PRAGMA table_info(posts)")])

    def test_a_post_can_move_to_a_better_matching_story(self):
        a_, b_ = story(art(1), art(2)), story(art(10), art(11))
        self.build(a_, b_)
        post = {"platform": "reddit", "source": "r", "handle": "r/x", "url": "https://r/1", "text": "t", "when": T0, "video": False}
        archive.record_posts(self.path, self.t, [post], [(post, a_, 0.3)])
        archive.record_posts(self.path, self.t + 1, [post], [(post, b_, 0.6)])
        conn = archive.open_archive(self.path)
        self.assertEqual(archive.story_record(conn, a_["sid"])["posts"], [])
        self.assertEqual(len(archive.story_record(conn, b_["sid"])["posts"]), 1)

    def test_an_unchanged_rebuild_records_no_edits_and_no_duplicates(self):
        s = story(art(1), art(2))
        self.build(s)
        out = self.build(story(art(1), art(2)))
        self.assertEqual(out["edits"], 0)
        self.assertEqual(out["new_articles"], 0)
        conn = sqlite3.connect(self.path)
        self.assertEqual(conn.execute("SELECT COUNT(*) FROM articles").fetchone()[0], 2)

    def test_old_entries_are_deleted(self):
        self.build(story(art(1), art(2)))
        self.t += 400 * 86400
        archive.record_build(self.path, self.t, [art(50)], {"us": ([], [])}, keep_days=365)
        conn = sqlite3.connect(self.path)
        self.assertEqual(conn.execute("SELECT COUNT(*) FROM articles WHERE url IN ('https://example.com/1','https://example.com/2')").fetchone()[0], 0)
        self.assertEqual(conn.execute("SELECT COUNT(*) FROM articles").fetchone()[0], 1)


if __name__ == "__main__":
    unittest.main()
