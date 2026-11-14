"""Clips and posts from open social platforms: Bluesky accounts, Mastodon accounts and hashtags, Reddit communities.

Everything here is pulled by this program, never by the reader's browser, so no platform script, cookie or embedded
player ever loads for a reader. Items are shown newest first and are never ranked by engagement. Only open, public
routes are used: no logins, and no scraping of platforms that do not offer one (TikTok, Instagram).
"""
import calendar
import html
import json
import re
import urllib.parse
from datetime import datetime, timedelta, timezone

import feedparser
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity

BSKY_API = "https://public.api.bsky.app/xrpc/"
VIDEO_HOSTS = re.compile(r"v\.redd\.it|youtube\.com|youtu\.be|streamable\.com|vimeo\.com|twitch\.tv/\w+/clip", re.I)
PLATFORMS = ("bluesky", "mastodon", "reddit")
NAMES = {"bluesky": "Bluesky", "mastodon": "Mastodon", "reddit": "Reddit"}


def clean_text(s, limit=600):
    text = html.unescape(re.sub(r"<[^>]+>", " ", s or ""))
    text = " ".join(text.split())
    return text if len(text) <= limit else text[:limit - 1].rstrip() + "…"


def _when(dt, now):
    """Posts cannot come from the future: a wrong clock is treated as 'just now'."""
    return now if dt > now + timedelta(minutes=10) else dt


def mastodon_target(handle):
    """'@user@instance' -> (account feed url, profile url); '#tag@instance' -> (tag feed url, tag page url)."""
    m = re.fullmatch(r"([@#])([\w.-]+)@([\w.-]+\.[a-z]+)", handle.strip(), re.I)
    if not m:
        raise ValueError(f"Mastodon handle should look like @user@instance.social or #tag@instance.social, not {handle!r}")
    kind, name, host = m.groups()
    if kind == "@":
        return f"https://{host}/@{name}.rss", f"https://{host}/@{name}"
    return f"https://{host}/tags/{name}.rss", f"https://{host}/tags/{name}"


def reddit_target(handle):
    m = re.fullmatch(r"(?:r/)?(\w+)", handle.strip())
    if not m:
        raise ValueError(f"Reddit community should look like r/worldnews, not {handle!r}")
    return f"https://www.reddit.com/r/{m.group(1)}/new/.rss", f"https://www.reddit.com/r/{m.group(1)}"


def profile_url(src):
    """Where a person can look at the account themselves."""
    p, h = src["platform"], src["handle"]
    if p == "bluesky":
        return f"https://bsky.app/profile/{h}"
    return mastodon_target(h)[1] if p == "mastodon" else reddit_target(h)[1]


def _bluesky_has_video(embed):
    embed = embed or {}
    kind = embed.get("$type", "")
    if kind.startswith("app.bsky.embed.video"):
        return True
    return (kind.startswith("app.bsky.embed.recordWithMedia")
            and (embed.get("media") or {}).get("$type", "").startswith("app.bsky.embed.video"))


def _https(url):
    """Only plain https addresses are ever put in a page."""
    return url if isinstance(url, str) and url.startswith("https://") else None


def _bluesky_media(embed):
    embed = embed or {}
    if embed.get("$type", "").startswith("app.bsky.embed.recordWithMedia"):
        embed = embed.get("media") or {}
    if not embed.get("$type", "").startswith("app.bsky.embed.video") or not _https(embed.get("playlist")):
        return None
    ratio = embed.get("aspectRatio") or {}
    return {"kind": "hls", "src": embed["playlist"], "poster": _https(embed.get("thumbnail")),
            "w": ratio.get("width"), "h": ratio.get("height"), "alt": clean_text(embed.get("alt", ""), 300)}


def bluesky_posts(src, get, now):
    video_only = src.get("kind", "video") == "video"
    filt = "posts_with_video" if video_only else "posts_no_replies"
    url = (f"{BSKY_API}app.bsky.feed.getAuthorFeed?actor={urllib.parse.quote(src['handle'])}"
           f"&filter={filt}&limit={src.get('limit', 30)}")
    out = []
    for item in json.loads(get(url)).get("feed", []):
        if item.get("reason"):  # a repost: not this account's own post
            continue
        post = item["post"]
        rec = post.get("record", {})
        created = rec.get("createdAt")
        if not created:
            continue
        rkey = post["uri"].rsplit("/", 1)[-1]
        out.append({
            "platform": "bluesky", "source": src["name"], "handle": post["author"]["handle"],
            "url": f"https://bsky.app/profile/{post['author']['handle']}/post/{rkey}",
            "text": clean_text(rec.get("text", "")),
            "when": _when(datetime.fromisoformat(created.replace("Z", "+00:00")).astimezone(timezone.utc), now),
            "video": _bluesky_has_video(post.get("embed")),
            "media": _bluesky_media(post.get("embed")),
        })
    return out


def mastodon_posts(src, get, now):
    feed_url, _ = mastodon_target(src["handle"])
    out = []
    for e in feedparser.parse(get(feed_url)).entries:
        t = e.get("published_parsed") or e.get("updated_parsed")
        if not t or not e.get("link"):
            continue
        videos = [m for m in e.get("media_content", []) if m.get("type", "").startswith("video") or m.get("medium") == "video"]
        video = bool(videos)
        thumb = next((_https(t.get("url")) for t in e.get("media_thumbnail", [])), None)
        media = None
        if videos and _https(videos[0].get("url")):
            v = videos[0]
            media = {"kind": "mp4", "src": v["url"], "poster": thumb,
                     "w": int(v["width"]) if str(v.get("width", "")).isdigit() else None,
                     "h": int(v["height"]) if str(v.get("height", "")).isdigit() else None, "alt": ""}
        out.append({
            "platform": "mastodon", "source": src["name"], "handle": src["handle"], "url": e["link"],
            "text": clean_text(e.get("summary") or e.get("title", "")),
            "when": _when(datetime.fromtimestamp(calendar.timegm(t), timezone.utc), now), "video": video, "media": media,
        })
    return out


def reddit_posts(src, get, now):
    feed_url, _ = reddit_target(src["handle"])
    out = []
    for e in feedparser.parse(get(feed_url)).entries:
        t = e.get("published_parsed") or e.get("updated_parsed")
        if not t or not e.get("link"):
            continue
        body = e.get("summary", "") + " ".join(c.get("value", "") for c in e.get("content", []))
        out.append({
            "platform": "reddit", "source": src["name"], "handle": src["handle"], "url": e["link"],
            "text": clean_text(e.get("title", "")),
            "when": _when(datetime.fromtimestamp(calendar.timegm(t), timezone.utc), now),
            "video": bool(VIDEO_HOSTS.search(body)),
            "media": None,  # Reddit video is opened on Reddit (or a front end you choose), not played here
        })
    return out


FETCHERS = {"bluesky": bluesky_posts, "mastodon": mastodon_posts, "reddit": reddit_posts}


def fetch(src, get, now, cutoff):
    """Recent posts for one followed account, newest first. Video only unless the entry says kind = "all"."""
    if src["platform"] not in FETCHERS:
        raise ValueError(f"unknown platform {src['platform']!r} (use one of {', '.join(PLATFORMS)})")
    posts = [p for p in FETCHERS[src["platform"]](src, get, now) if p["when"] >= cutoff]
    if src.get("kind", "video") == "video":
        posts = [p for p in posts if p["video"]]
    return sorted(posts, key=lambda p: p["when"], reverse=True)


def match_posts(posts, stories, min_sim=0.2):
    """Pair each post with the story whose headlines it most resembles, if it resembles one closely enough.
    Matching is by wording only, so it can miss a post or pair one loosely; the page says so."""
    posts = [p for p in posts if p["text"]]
    if not posts or not stories:
        return []
    docs = [" ".join(m["title"] for m in s["members"]) for s in stories]
    vec = TfidfVectorizer(stop_words="english", ngram_range=(1, 2), sublinear_tf=True)
    m = vec.fit_transform(docs + [p["text"] for p in posts])
    sims = cosine_similarity(m[len(stories):], m[:len(stories)])
    out = []
    for i, p in enumerate(posts):
        j = int(sims[i].argmax())
        if sims[i][j] >= min_sim:
            out.append((p, stories[j], float(sims[i][j])))
    return out


def open_url(url, open_with):
    """Optionally open a link through an open-source privacy front end the reader or maintainer chose in config."""
    if not open_with:
        return url
    p = urllib.parse.urlsplit(url)
    host = p.netloc.lower().removeprefix("www.")
    if host in ("reddit.com", "old.reddit.com") and open_with.get("reddit"):
        return urllib.parse.urlunsplit(("https", open_with["reddit"], p.path, p.query, ""))
    if host in ("youtube.com", "m.youtube.com") and open_with.get("youtube"):
        return urllib.parse.urlunsplit(("https", open_with["youtube"], p.path, p.query, ""))
    if host == "youtu.be" and open_with.get("youtube"):
        return f"https://{open_with['youtube']}/watch?v={p.path.lstrip('/')}"
    return url
