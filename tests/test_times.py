"""Tests that publish times are read as UTC regardless of the computer's time zone, and that the old
shifted archive is repaired exactly once. Run: .venv/bin/python -m unittest discover tests"""
import calendar
import os
import sqlite3
import sys
import tempfile
import time
import unittest
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import archive
import build

TRUE_UTC = (2026, 11, 9, 22, 0, 0, 0, 0, 0)  # a UTC struct_time, as feedparser produces


class TimeZoneTests(unittest.TestCase):
    def setUp(self):
        self.old_tz = os.environ.get("TZ")

    def tearDown(self):
        if self.old_tz is None:
            os.environ.pop("TZ", None)
        else:
            os.environ["TZ"] = self.old_tz
        time.tzset()

    def set_tz(self, name):
        os.environ["TZ"] = name
        time.tzset()

    def test_entry_time_is_the_same_in_every_time_zone(self):
        expected = datetime(2026, 11, 9, 22, 0, tzinfo=timezone.utc)
        for tz in ("America/Los_Angeles", "UTC", "Asia/Tokyo", "Europe/London"):
            self.set_tz(tz)
            got = build.entry_time({"published_parsed": time.struct_time(TRUE_UTC)})
            self.assertEqual(got, expected, tz)

    def test_the_old_archive_is_repaired_once(self):
        self.set_tz("America/Los_Angeles")
        true_epoch = calendar.timegm(TRUE_UTC)
        shifted = int(time.mktime(time.struct_time(TRUE_UTC)))  # what the old code stored
        self.assertEqual(shifted - true_epoch, 8 * 3600)
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "a.sqlite"
            conn = archive.open_archive(path)  # fresh: marker only
            conn.execute("INSERT INTO articles(url, source, lean, fringe, topic, title, published, first_seen, last_seen, story_id) "
                         "VALUES('u','S','left',0,'us','T',?,1,1,NULL)", (shifted,))
            conn.execute("DELETE FROM meta")  # pretend this archive was written by the old code
            conn.commit()
            conn.close()
            conn = archive.open_archive(path)
            self.assertEqual(conn.execute("SELECT published FROM articles").fetchone()[0], true_epoch)
            conn.close()
            conn = archive.open_archive(path)  # opening again must not shift it a second time
            self.assertEqual(conn.execute("SELECT published FROM articles").fetchone()[0], true_epoch)

    def test_a_fresh_archive_is_not_touched(self):
        with tempfile.TemporaryDirectory() as d:
            conn = archive.open_archive(Path(d) / "a.sqlite")
            self.assertEqual({r[0] for r in conn.execute("SELECT key FROM meta")}, {"publish_times_utc", "story_labels_v2"})


if __name__ == "__main__":
    unittest.main()
