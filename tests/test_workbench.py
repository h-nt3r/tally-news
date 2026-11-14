import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import workbench as wb

DEFAULTS = {
    "settings": {},
    "feeds": [{"name": "A", "url": "https://a.test/feed", "lean": "left", "topic": "us", "type": "commercial"},
              {"name": "B", "url": "https://b.test/feed", "lean": "right", "topic": "world"}],
    "channels": [{"name": "A", "handle": "achannel", "lean": "left"}],
}


def fresh():
    return wb.empty_changes()


class ApplyTests(unittest.TestCase):
    def test_no_changes_leaves_the_defaults_alone(self):
        new, rep = wb.apply_changes(DEFAULTS, fresh())
        self.assertEqual(new, DEFAULTS)
        self.assertEqual(rep["removed"], [])

    def test_the_default_config_is_never_modified(self):
        ch = fresh()
        ch["remove"].append({"kind": "feeds", "name": "A"})
        wb.apply_changes(DEFAULTS, ch)
        self.assertEqual(len(DEFAULTS["feeds"]), 2)

    def test_remove_is_by_kind_and_name(self):
        ch = fresh()
        ch["remove"].append({"kind": "feeds", "name": "A"})
        new, rep = wb.apply_changes(DEFAULTS, ch)
        self.assertEqual([f["name"] for f in new["feeds"]], ["B"])
        self.assertEqual(len(new["channels"]), 1)  # the channel with the same name stays
        self.assertEqual(rep["removed"], [{"kind": "feeds", "name": "A"}])

    def test_added_sources_join_and_duplicates_are_skipped(self):
        ch = fresh()
        ch["feeds"] += [{"name": "New", "url": "https://n.test/rss", "lean": "center", "topic": "us"},
                        {"name": "B", "url": "https://dup.test/rss", "lean": "center", "topic": "us"}]
        new, rep = wb.apply_changes(DEFAULTS, ch)
        self.assertEqual([f["name"] for f in new["feeds"]], ["A", "B", "New"])
        self.assertEqual(len(rep["skipped"]), 1)

    def test_relabel_changes_side_and_can_clear_type(self):
        ch = fresh()
        ch["override"] += [{"kind": "feeds", "name": "A", "lean": "center", "type": ""}]
        new, _ = wb.apply_changes(DEFAULTS, ch)
        self.assertEqual(new["feeds"][0]["lean"], "center")
        self.assertNotIn("type", new["feeds"][0])

    def test_a_removal_of_something_not_in_the_defaults_is_ignored(self):
        ch = fresh()
        ch["remove"].append({"kind": "feeds", "name": "Nope"})
        new, rep = wb.apply_changes(DEFAULTS, ch)
        self.assertEqual(new, DEFAULTS)
        self.assertEqual(rep["removed"], [])


class FileTests(unittest.TestCase):
    def test_round_trip_including_awkward_characters(self):
        ch = fresh()
        ch["feeds"].append({"name": 'Odd "name" \\ ünï', "url": "https://x.test/f", "lean": "left", "topic": "us"})
        ch["remove"].append({"kind": "channels", "name": "A"})
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "changes.toml"
            wb.save_changes(ch, p)
            self.assertEqual(wb.load_changes(p), ch)

    def test_saving_nothing_removes_the_file(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "changes.toml"
            p.write_text("x = 1")
            wb.save_changes(fresh(), p)
            self.assertFalse(p.exists())

    def test_a_missing_file_means_no_changes(self):
        self.assertEqual(wb.load_changes(Path("/nonexistent/changes.toml")), fresh())

    def test_a_broken_file_gives_a_plain_message(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "changes.toml"
            p.write_text("[[remove\n")
            with self.assertRaises(ValueError) as cm:
                wb.load_changes(p)
            self.assertIn("reset", str(cm.exception).lower())


class ValidationTests(unittest.TestCase):
    def test_a_good_feed_passes(self):
        out = wb.clean_entry("feeds", {"name": " New  Outlet ", "url": "https://n.test/rss", "lean": "left", "topic": "tech", "type": "nonprofit"}, DEFAULTS)
        self.assertEqual(out["name"], "New Outlet")
        self.assertEqual(out["type"], "nonprofit")

    def test_the_side_must_be_chosen(self):
        with self.assertRaises(ValueError):
            wb.clean_entry("feeds", {"name": "X", "url": "https://n.test/rss", "lean": ""}, DEFAULTS)

    def test_bad_addresses_and_duplicates_are_refused(self):
        for bad in ({"name": "X", "url": "ftp://n.test", "lean": "left"}, {"name": "A", "url": "https://z.test/f", "lean": "left"},
                    {"name": "Y", "url": "https://a.test/feed", "lean": "left"}, {"name": "", "url": "https://z.test", "lean": "left"}):
            with self.assertRaises(ValueError):
                wb.clean_entry("feeds", bad, DEFAULTS)

    def test_channel_handles_are_checked_and_the_at_sign_dropped(self):
        self.assertEqual(wb.clean_entry("channels", {"name": "Z", "handle": "@zed", "lean": "right"}, DEFAULTS)["handle"], "zed")
        with self.assertRaises(ValueError):
            wb.clean_entry("channels", {"name": "Z", "handle": "bad handle!", "lean": "right"}, DEFAULTS)

    def test_private_addresses_are_blocked(self):
        for ip in ("127.0.0.1", "10.0.0.5", "192.168.1.1", "169.254.1.1"):
            with self.assertRaises(ValueError):
                wb.check_url_is_public("http://x.test/", resolve=lambda h, p, ip=ip: [(0, 0, 0, "", (ip, 0))])
        wb.check_url_is_public("https://x.test/", resolve=lambda h, p: [(0, 0, 0, "", ("93.184.216.34", 0))])

    def test_only_web_addresses_are_allowed(self):
        with self.assertRaises(ValueError):
            wb.check_url_is_public("file:///etc/passwd")


class EditTests(unittest.TestCase):
    def test_removing_something_you_added_deletes_it_outright(self):
        ch = fresh()
        ch["feeds"].append({"name": "New", "url": "https://n.test", "lean": "left", "topic": "us"})
        wb.remove_source(ch, "feeds", "New", DEFAULTS)
        self.assertEqual(ch["feeds"], [])
        self.assertEqual(ch["remove"], [])

    def test_removing_a_default_is_remembered_once_and_restorable(self):
        ch = fresh()
        wb.remove_source(ch, "feeds", "A", DEFAULTS)
        wb.remove_source(ch, "feeds", "A", DEFAULTS)
        self.assertEqual(len(ch["remove"]), 1)
        wb.restore_source(ch, "feeds", "A")
        self.assertEqual(ch["remove"], [])

    def test_changing_a_label_back_to_the_default_forgets_the_override(self):
        ch = fresh()
        wb.set_label(ch, "feeds", "A", DEFAULTS, "lean", "right")
        self.assertEqual(len(ch["override"]), 1)
        wb.set_label(ch, "feeds", "A", DEFAULTS, "lean", "left")
        self.assertEqual(ch["override"], [])

    def test_describe_marks_removed_and_added(self):
        ch = fresh()
        wb.remove_source(ch, "feeds", "B", DEFAULTS)
        ch["feeds"].append({"name": "New", "url": "https://n.test", "lean": "left", "topic": "us"})
        d = wb.describe(DEFAULTS, ch)
        self.assertEqual((d["defaults"], d["removed"], d["added"]), (3, 1, 1))


SAMPLE_PAGE = b"""<html><head><link rel="alternate" type="application/rss+xml" href="/rss.xml">
<link rel='alternate' type='application/atom+xml' href='https://other.test/atom'><link rel="stylesheet" href="x.css"></head></html>"""


class DiscoverTests(unittest.TestCase):
    def test_feed_links_are_found_in_the_page_head(self):
        self.assertEqual(wb.feed_links(SAMPLE_PAGE.decode(), "https://site.test/news/"),
                         ["https://site.test/rss.xml", "https://other.test/atom"])

    def test_youtube_addresses_give_a_handle(self):
        self.assertEqual(wb.youtube_handle("https://www.youtube.com/@MeansTVstudios"), "MeansTVstudios")
        self.assertEqual(wb.youtube_handle("youtube.com/c/MeansTVstudios"), "MeansTVstudios")
        self.assertIsNone(wb.youtube_handle("https://example.com/@x"))

    def test_a_site_address_leads_to_its_feed_with_a_preview(self):
        pages = {"https://site.test": SAMPLE_PAGE, "https://site.test/rss.xml": b"FEED"}

        def fetch(u):
            if u not in pages:
                raise OSError("404")
            return pages[u]

        def parse(b):
            if b == b"FEED":
                return SimpleNamespace(entries=[{"title": "One", "published": "Mon"}, {"title": "Two"}], feed={"title": "Site &amp; Co", "link": "https://site.test"})
            return SimpleNamespace(entries=[], feed={})

        orig = wb.check_url_is_public
        wb.check_url_is_public = lambda u, resolve=None: None
        try:
            out = wb.discover("site.test", fetch, parse)
        finally:
            wb.check_url_is_public = orig
        self.assertEqual((out["kind"], out["url"], out["name"]), ("feeds", "https://site.test/rss.xml", "Site & Co"))
        self.assertEqual([i["title"] for i in out["items"]], ["One", "Two"])

    def test_a_page_with_no_feed_says_so_plainly(self):
        orig = wb.check_url_is_public
        wb.check_url_is_public = lambda u, resolve=None: None
        try:
            with self.assertRaises(ValueError) as cm:
                wb.discover("https://empty.test", lambda u: b"<html></html>", lambda b: SimpleNamespace(entries=[], feed={}))
        finally:
            wb.check_url_is_public = orig
        self.assertIn("No feed found", str(cm.exception))


class ServerGuardTests(unittest.TestCase):
    def test_only_this_mac_by_name_is_accepted(self):
        self.assertTrue(wb.host_ok("localhost:8766", 8766))
        self.assertTrue(wb.host_ok("127.0.0.1:8766", 8766))
        self.assertFalse(wb.host_ok("evil.example:8766", 8766))
        self.assertFalse(wb.host_ok("192.168.1.5:8766", 8766))
        self.assertFalse(wb.host_ok(None, 8766))

    def test_a_foreign_origin_is_refused(self):
        self.assertTrue(wb.origin_ok(None, 8766))
        self.assertTrue(wb.origin_ok("http://localhost:8766", 8766))
        self.assertFalse(wb.origin_ok("https://evil.example", 8766))


if __name__ == "__main__":
    unittest.main()
