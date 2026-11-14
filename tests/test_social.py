"""Tests for reading clips and posts from open platforms, without the network.
Run: .venv/bin/python -m unittest discover tests"""
import json
import sys
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import social

NOW = datetime(2026, 11, 9, 22, 0, tzinfo=timezone.utc)
CUTOFF = NOW - timedelta(hours=36)


def bsky(*items):
    return json.dumps({"feed": list(items)}).encode()


def bsky_item(rkey, text, created, embed_type=None, repost=False, handle="apnews.com"):
    post = {"uri": f"at://did:plc:abc/app.bsky.feed.post/{rkey}", "author": {"handle": handle},
            "record": {"text": text, "createdAt": created}}
    if embed_type:
        post["embed"] = {"$type": embed_type}
    item = {"post": post}
    if repost:
        item["reason"] = {"$type": "app.bsky.feed.defs#reasonRepost"}
    return item


class BlueskyTests(unittest.TestCase):
    def fetch(self, body, **src):
        s = dict(name="AP", platform="bluesky", handle="apnews.com", **src)
        return social.fetch(s, lambda url: body, NOW, CUTOFF)

    def test_a_video_post_becomes_an_item_with_a_link_to_the_post(self):
        posts = self.fetch(bsky(bsky_item("3k1", "Flood waters rise", "2026-11-09T20:00:00.000Z", "app.bsky.embed.video#view")))
        self.assertEqual(len(posts), 1)
        self.assertEqual(posts[0]["url"], "https://bsky.app/profile/apnews.com/post/3k1")
        self.assertTrue(posts[0]["video"])
        self.assertEqual(posts[0]["when"], datetime(2026, 11, 9, 20, 0, tzinfo=timezone.utc))

    def test_reposts_are_left_out(self):
        posts = self.fetch(bsky(bsky_item("a", "Own post", "2026-11-09T20:00:00Z", "app.bsky.embed.video#view"),
                                bsky_item("b", "Someone else's", "2026-11-09T21:00:00Z", "app.bsky.embed.video#view", repost=True)))
        self.assertEqual([p["url"].rsplit("/", 1)[-1] for p in posts], ["a"])

    def test_video_only_is_the_default_and_all_shows_text_posts(self):
        body = bsky(bsky_item("v", "clip", "2026-11-09T20:00:00Z", "app.bsky.embed.video#view"),
                    bsky_item("t", "just words", "2026-11-09T19:00:00Z"))
        self.assertEqual(len(self.fetch(body)), 1)
        self.assertEqual(len(self.fetch(body, kind="all")), 2)

    def test_newest_first_and_old_posts_dropped(self):
        body = bsky(bsky_item("old", "x", "2026-11-01T00:00:00Z", "app.bsky.embed.video#view"),
                    bsky_item("a", "x", "2026-11-09T10:00:00Z", "app.bsky.embed.video#view"),
                    bsky_item("b", "x", "2026-11-09T12:00:00Z", "app.bsky.embed.video#view"))
        self.assertEqual([p["url"][-1] for p in self.fetch(body)], ["b", "a"])

    def test_a_post_dated_in_the_future_is_treated_as_now(self):
        posts = self.fetch(bsky(bsky_item("f", "x", "2026-11-10T09:00:00Z", "app.bsky.embed.video#view")))
        self.assertEqual(posts[0]["when"], NOW)


MASTODON = b"""<?xml version="1.0"?><rss version="2.0" xmlns:media="http://search.yahoo.com/mrss/"><channel>
<item><title>t1</title><link>https://mastodon.social/@a/1</link><pubDate>Mon, 09 Nov 2026 20:00:00 +0000</pubDate>
<description>&lt;p&gt;Clip &amp;amp; caption&lt;/p&gt;</description><media:content url="https://x/v.mp4" type="video/mp4" medium="video"/></item>
<item><title>t2</title><link>https://mastodon.social/@a/2</link><pubDate>Mon, 09 Nov 2026 19:00:00 +0000</pubDate>
<description>only words</description></item></channel></rss>"""

REDDIT = b"""<?xml version="1.0"?><feed xmlns="http://www.w3.org/2005/Atom"><entry><title>Protest footage</title>
<link href="https://www.reddit.com/r/worldnews/comments/1/x/"/><updated>2026-11-09T20:00:00+00:00</updated>
<content type="html">&lt;a href="https://v.redd.it/abc"&gt;[link]&lt;/a&gt;</content></entry>
<entry><title>An article</title><link href="https://www.reddit.com/r/worldnews/comments/2/y/"/><updated>2026-11-09T19:00:00+00:00</updated>
<content type="html">&lt;a href="https://example.com/story"&gt;[link]&lt;/a&gt;</content></entry></feed>"""


class MediaTests(unittest.TestCase):
    def fetch(self, items):
        return social.fetch(dict(name="AP", platform="bluesky", handle="apnews.com"), lambda u: bsky(*items), NOW, CUTOFF)

    def test_a_bluesky_video_carries_its_playlist_poster_and_shape(self):
        item = bsky_item("v", "clip", "2026-11-09T20:00:00Z")
        item["post"]["embed"] = {"$type": "app.bsky.embed.video#view", "playlist": "https://video.bsky.app/watch/x/playlist.m3u8",
                                 "thumbnail": "https://video.bsky.app/watch/x/thumbnail.jpg", "alt": "A flooded street",
                                 "aspectRatio": {"width": 1080, "height": 1920}}
        media = self.fetch([item])[0]["media"]
        self.assertEqual(media["kind"], "hls")
        self.assertEqual((media["w"], media["h"]), (1080, 1920))
        self.assertEqual(media["alt"], "A flooded street")

    def test_a_video_inside_a_quote_post_is_found(self):
        item = bsky_item("q", "quote", "2026-11-09T20:00:00Z")
        item["post"]["embed"] = {"$type": "app.bsky.embed.recordWithMedia#view",
                                 "media": {"$type": "app.bsky.embed.video#view", "playlist": "https://video.bsky.app/p.m3u8"}}
        self.assertEqual(self.fetch([item])[0]["media"]["src"], "https://video.bsky.app/p.m3u8")

    def test_only_https_addresses_are_accepted(self):
        item = bsky_item("v", "clip", "2026-11-09T20:00:00Z")
        item["post"]["embed"] = {"$type": "app.bsky.embed.video#view", "playlist": "javascript:alert(1)", "thumbnail": "http://x/t.jpg"}
        self.assertIsNone(self.fetch([item])[0]["media"])
        item["post"]["embed"]["playlist"] = "https://video.bsky.app/p.m3u8"
        self.assertIsNone(self.fetch([item])[0]["media"]["poster"])  # an http poster is dropped

    def test_a_mastodon_video_is_playable_as_mp4(self):
        src = dict(name="Acct", platform="mastodon", handle="@a@mastodon.social", kind="all")
        posts = social.fetch(src, lambda u: MASTODON, NOW, CUTOFF)
        self.assertEqual(posts[0]["media"]["kind"], "mp4")
        self.assertIsNone(posts[1]["media"])

    def test_reddit_video_is_linked_not_played(self):
        src = dict(name="WN", platform="reddit", handle="r/worldnews", kind="all")
        self.assertIsNone(social.fetch(src, lambda u: REDDIT, NOW, CUTOFF)[0]["media"])


class RssTests(unittest.TestCase):
    def test_mastodon_marks_video_attachments_and_cleans_the_caption(self):
        src = dict(name="Acct", platform="mastodon", handle="@a@mastodon.social", kind="all")
        posts = social.fetch(src, lambda u: MASTODON, NOW, CUTOFF)
        self.assertEqual([p["video"] for p in posts], [True, False])
        self.assertEqual(posts[0]["text"], "Clip & caption")
        self.assertEqual(posts[0]["when"], datetime(2026, 11, 9, 20, 0, tzinfo=timezone.utc))  # UTC, in any time zone

    def test_reddit_finds_video_hosts_in_the_post(self):
        src = dict(name="WN", platform="reddit", handle="r/worldnews", kind="all")
        posts = social.fetch(src, lambda u: REDDIT, NOW, CUTOFF)
        self.assertEqual([p["video"] for p in posts], [True, False])
        video_only = social.fetch(dict(src, kind="video"), lambda u: REDDIT, NOW, CUTOFF)
        self.assertEqual(len(video_only), 1)

    def test_handles_are_turned_into_the_right_feed_addresses(self):
        self.assertEqual(social.mastodon_target("@user@mastodon.social")[0], "https://mastodon.social/@user.rss")
        self.assertEqual(social.mastodon_target("#news@mastodon.social")[0], "https://mastodon.social/tags/news.rss")
        self.assertEqual(social.reddit_target("r/worldnews")[0], "https://www.reddit.com/r/worldnews/new/.rss")
        with self.assertRaises(ValueError):
            social.mastodon_target("not a handle")

    def test_an_unknown_platform_is_an_error_not_a_guess(self):
        with self.assertRaises(ValueError):
            social.fetch(dict(name="x", platform="tiktok", handle="y"), lambda u: b"", NOW, CUTOFF)


class MatchTests(unittest.TestCase):
    def story(self, *titles):
        return {"members": [{"title": t} for t in titles]}

    def test_a_post_pairs_with_the_story_it_resembles_and_unrelated_posts_pair_with_none(self):
        stories = [self.story("Judge denies Lindsay Clancy motion to dismiss murder case", "Clancy judge rejects dismissal bid"),
                   self.story("FDA warns of rare eye stroke risk from GLP-1 drugs")]
        posts = [{"text": "Judge denies motion to dismiss in the Lindsay Clancy case"}, {"text": "Look at this cute dog on a skateboard"}]
        pairs = social.match_posts(posts, stories, 0.2)
        self.assertEqual(len(pairs), 1)
        self.assertIs(pairs[0][1], stories[0])

    def test_posts_without_text_are_not_matched(self):
        self.assertEqual(social.match_posts([{"text": ""}], [self.story("A headline")], 0.0), [])


class OpenWithTests(unittest.TestCase):
    def test_links_are_unchanged_unless_a_front_end_is_chosen(self):
        self.assertEqual(social.open_url("https://www.reddit.com/r/x/comments/1/y/", {}), "https://www.reddit.com/r/x/comments/1/y/")

    def test_reddit_and_youtube_links_can_open_through_a_front_end(self):
        ow = {"reddit": "redlib.example.org", "youtube": "piped.example.org"}
        self.assertEqual(social.open_url("https://www.reddit.com/r/x/comments/1/y/", ow), "https://redlib.example.org/r/x/comments/1/y/")
        self.assertEqual(social.open_url("https://www.youtube.com/watch?v=abc", ow), "https://piped.example.org/watch?v=abc")
        self.assertEqual(social.open_url("https://youtu.be/abc", ow), "https://piped.example.org/watch?v=abc")
        self.assertEqual(social.open_url("https://bsky.app/profile/a/post/b", ow), "https://bsky.app/profile/a/post/b")


if __name__ == "__main__":
    unittest.main()
