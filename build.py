#!/usr/bin/env python3
"""Fetch feeds, group coverage of the same story, write site/index.html.

Ranking rule (deliberately simple and visible): stories are ordered by how many
different outlets covered them. Nothing is personalized. Nothing learns from you.
"""
import federation
import gzip
import hashlib
import html
import calendar
import difflib
import json
import os
import re
import shutil
import subprocess
import sys
import threading
import time
import tomllib
import pages
import publish
import summaries
import urllib.error
import urllib.parse
import urllib.request
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from pathlib import Path

import feedparser
import analytics
import archive
import social
from analytics import clock, fmt_dur
from sklearn.cluster import AgglomerativeClustering
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity

ROOT = Path(__file__).parent
CACHE = ROOT / "cache"
UA = {"User-Agent": "Mozilla/5.0 (news_digest personal reader)"}
LEANS = ["left", "center", "right"]


def get(url, timeout=15):
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read()


FEED_STATE = CACHE / "feeds.json"   # url -> {"etag", "modified"}; the last body for each lives in cache/feeds/
_feed_state, _feed_lock, _feed_stats = {}, threading.Lock(), {"fresh": 0, "unchanged": 0}


def _body_path(url):
    return CACHE / "feeds" / (hashlib.sha1(url.encode()).hexdigest()[:16] + ".body")


def load_feed_state():
    global _feed_state
    try:
        _feed_state = json.loads(FEED_STATE.read_text())
    except Exception:
        _feed_state = {}


def save_feed_state():
    try:
        CACHE.mkdir(exist_ok=True)
        with _feed_lock:
            FEED_STATE.write_text(json.dumps(_feed_state))
    except Exception:
        pass


def get_feed(url, timeout=15):
    """A polite fetch of a feed: asks the site "has this changed since I last looked?" (ETag / Last-Modified) and takes
    compressed bodies. An unchanged feed costs the site a tiny 304 reply and we reuse the copy we kept."""
    st = _feed_state.get(url, {})
    path = _body_path(url)
    headers = dict(UA, **{"Accept-Encoding": "gzip"})
    if path.exists():  # only ask conditionally when we still hold the body it would replace
        if st.get("etag"):
            headers["If-None-Match"] = st["etag"]
        if st.get("modified"):
            headers["If-Modified-Since"] = st["modified"]
    req = urllib.request.Request(url, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            body = r.read()
            if r.headers.get("Content-Encoding", "").lower() == "gzip":
                body = gzip.decompress(body)
            etag, modified = r.headers.get("ETag"), r.headers.get("Last-Modified")
    except urllib.error.HTTPError as ex:
        if ex.code == 304 and path.exists():
            with _feed_lock:
                _feed_stats["unchanged"] += 1
            return path.read_bytes()
        raise
    with _feed_lock:
        _feed_stats["fresh"] += 1
        if etag or modified:
            _feed_state[url] = {"etag": etag, "modified": modified}
        else:
            _feed_state.pop(url, None)
    try:
        if etag or modified:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(body)
        elif path.exists():
            path.unlink()
    except OSError:
        pass
    return body


def get_retry(url, tries=4):
    """YouTube's feed endpoint intermittently answers 404/500, so try a few times."""
    for n in range(tries):
        try:
            return get(url)
        except Exception:
            if n == tries - 1:
                raise
            time.sleep(1.5 * (n + 1))


MASTODON = ["mastodon.social", "mastodon.online"]
BLUESKY_TRENDS = "https://public.api.bsky.app/xrpc/app.bsky.unspecced.getTrends?limit=25"
NO_BUZZ = {"mastodon": 0, "mastodon_host": None, "hn_points": 0, "hn_id": None}
BSKY_TOPIC = re.compile(r"^/profile/[\w:.%-]+/feed/[\w.-]+$")  # the shape of a Bluesky topic-feed link


def norm_url(u):
    """Same article, different spelling (www, tracking params, trailing slash) -> same key."""
    p = urllib.parse.urlsplit(u)
    return p.netloc.lower().removeprefix("www.") + p.path.rstrip("/")


def fetch_buzz(hours=48):
    """Public popularity signals, keyed by normalized article URL. Display only; never used to rank."""
    buzz = {}

    def slot(url):
        return buzz.setdefault(norm_url(url), dict(NO_BUZZ))

    for host in MASTODON:
        shared = {}
        for offset in (0, 20, 40):  # the API serves 20 links per page
            try:
                links = json.loads(get(f"https://{host}/api/v1/trends/links?limit=20&offset={offset}"))
            except Exception as ex:
                print(f"  no Mastodon trends from {host}: {ex}", file=sys.stderr)
                break
            for l in links:
                # people sharing the link over the last two days
                shared[l["url"]] = sum(int(d["accounts"]) for d in l["history"][:2])
            if len(links) < 20:
                break
        for url, n in shared.items():
            b = slot(url)
            if n > b["mastodon"]:  # servers overlap, so take the larger, not the sum
                b["mastodon"], b["mastodon_host"] = n, host
    try:
        since = int(time.time()) - hours * 3600
        flt = urllib.parse.quote(f"points>=20,created_at_i>{since}")
        hits = json.loads(get(
            f"https://hn.algolia.com/api/v1/search_by_date?tags=story&numericFilters={flt}&hitsPerPage=1000"))["hits"]
        for h in hits:
            if h.get("url") and h["points"] > slot(h["url"])["hn_points"]:
                slot(h["url"]).update(hn_points=h["points"], hn_id=h["objectID"])
    except Exception as ex:
        print(f"  no Hacker News data: {ex}", file=sys.stderr)
    return buzz


def bluesky_url(link):
    return "https://bsky.app" + link if BSKY_TOPIC.match(link or "") else None


def fetch_bluesky_trends():
    """Bluesky's trending topics: a name, a one-line description and a post count. No article links."""
    try:
        data = json.loads(get(BLUESKY_TRENDS))["trends"]
        return [{"name": t["displayName"], "text": f'{t["displayName"]}. {t.get("description", "")}',
                 "posts": t.get("postCount", 0), "url": bluesky_url(t.get("link"))} for t in data]
    except Exception as ex:
        print(f"  no Bluesky trends: {ex}", file=sys.stderr)
        return []


def match_trends(stories, trends, min_sim):
    """Attach each Bluesky trend to the stories it matches well.
    Matching is by wording, so the card shows the trend's own name and you can judge it."""
    if not stories or not trends:
        return []
    docs = [" ".join(f"{m['title']} {m['text']}" for m in st["members"]) for st in stories]
    vec = TfidfVectorizer(stop_words="english", ngram_range=(1, 2), sublinear_tf=True)
    m = vec.fit_transform(docs + [t["text"] for t in trends])
    sims = cosine_similarity(m[len(stories):], m[:len(stories)])
    matches = []
    for ti, t in enumerate(trends):
        # every story that clears the bar, since one event is sometimes split across two cards
        for si in range(len(stories)):
            if sims[ti][si] >= min_sim:
                matches.append((stories[si], t, float(sims[ti][si])))
    for st, t, _ in sorted(matches, key=lambda x: x[2]):  # if a story gets two trends, the best fit wins
        st["buzz"]["bluesky"] = t
    return matches


def clean(text):
    return html.unescape(re.sub(r"<[^>]+>", " ", text or "")).strip()


def entry_time(e):
    """When an entry was published, as an aware UTC time.

    feedparser's *_parsed values are UTC struct_times, so they need timegm. (mktime reads them as local time and
    shifts every date by this computer's UTC offset, which this code used to do.)
    """
    t = e.get("published_parsed") or e.get("updated_parsed")
    return datetime.fromtimestamp(calendar.timegm(t), timezone.utc) if t else None


def fetch_feed(feed, cutoff, cap):
    if feed.get("method") == "page":  # a page with no feed: watched for new links (see pages.py)
        return pages.fetch_page(feed, cutoff, cap)
    try:
        parsed = feedparser.parse(get_feed(feed["url"]))
    except Exception as ex:
        print(f"  skipped {feed['name']}: {ex}", file=sys.stderr)
        feed["_err"] = str(ex)
        return []
    feed["_total"] = len(parsed.entries)
    fetched_at, future, items = datetime.now(timezone.utc), 0, []
    social = federation.is_social_feed(feed["url"])  # Mastodon and Bluesky posts have no title of their own: use their first words
    for e in parsed.entries[:cap]:
        when = entry_time(e)
        title = e.get("title") or (federation.title_from_post(clean(e.get("summary", ""))) if social else "")
        if not when or not title or not e.get("link"):
            continue
        if when > fetched_at + timedelta(minutes=10):
            future += 1  # a feed with a wrong clock or a scheduled post: treat as just published
            when = fetched_at
        if when < cutoff:
            continue
        items.append({
            "title": clean(title),
            "link": e["link"],
            "text": clean(e.get("summary", ""))[:400],
            "when": when,
            "source": feed["name"],
            "lean": feed["lean"],
            "type": feed.get("type", ""),
            "topic": feed.get("topic", "us"),
        })
    feed["_n"] = len(items)
    feed["_future"] = future
    if not items:
        print(f"  no recent items from {feed['name']}", file=sys.stderr)
    return items


def channel_id(handle):
    CACHE.mkdir(exist_ok=True)
    path = CACHE / "youtube_ids.json"
    ids = json.loads(path.read_text()) if path.exists() else {}
    if handle not in ids:
        page = get(f"https://www.youtube.com/@{handle}").decode("utf-8", "ignore")
        # the page's RSS link is the canonical ID; "channelId" can match other channels
        m = re.search(r'channel_id=(UC[\w-]{22})', page) or re.search(
            r'"externalId":"(UC[\w-]{22})"', page)
        if not m:
            raise ValueError("channel id not found")
        ids[handle] = m.group(1)
        path.write_text(json.dumps(ids, indent=2))
    return ids[handle]


def channel_via_ytdlp(ch):
    """Fallback when YouTube's RSS endpoint is down. Gives newest-first order but no dates."""
    out = subprocess.run(
        [str(ROOT / ".venv" / "bin" / "yt-dlp"), "--flat-playlist", "--dump-json",
         "--playlist-end", "4", f"https://www.youtube.com/channel/{ch['id']}/videos"],
        capture_output=True, text=True, timeout=60, check=True).stdout
    now = datetime.now(timezone.utc)
    videos = []
    for n, line in enumerate(out.splitlines()):
        d = json.loads(line)
        videos.append({
            "title": d["title"], "link": f"https://www.youtube.com/watch?v={d['id']}",
            "when": now - timedelta(hours=n),  # stand-in: keeps the channel's newest-first order
            "source": ch["name"], "lean": ch["lean"],
            "type": ch.get("type", ""), "vid": d["id"],
            "views": d.get("view_count") or 0,
        })
    return videos


def fetch_channel(ch, cutoff):
    try:
        parsed = feedparser.parse(get_retry(
            f"https://www.youtube.com/feeds/videos.xml?channel_id={ch['id']}", tries=2))
        out = []
        for e in parsed.entries[:10]:
            when = entry_time(e)
            if not when or when < cutoff:
                continue
            vid = e.get("yt_videoid") or e["link"].split("v=")[-1]
            out.append({
                "title": clean(e["title"]), "link": e["link"], "when": when,
                "source": ch["name"], "lean": ch["lean"],
                "type": ch.get("type", ""), "vid": vid,
                "views": int((e.get("media_statistics") or {}).get("views", 0)),
            })
        if parsed.entries:
            return out
        raise ValueError("empty feed")
    except Exception:
        pass
    try:
        return channel_via_ytdlp(ch)
    except Exception as ex:
        print(f"  skipped video channel {ch['name']}: {ex}", file=sys.stderr)
        return []


def pick_videos(videos, limit):
    """Round-robin across left/center/right so no side fills the top row."""
    buckets = {l: sorted([v for v in videos if v["lean"] == l],
                         key=lambda v: v["when"], reverse=True) for l in LEANS}
    picked, seen_sources = [], {}
    while len(picked) < limit and any(buckets.values()):
        for l in LEANS:
            while buckets[l]:
                v = buckets[l].pop(0)
                if seen_sources.get(v["source"], 0) < 2:  # max 2 per channel
                    seen_sources[v["source"]] = seen_sources.get(v["source"], 0) + 1
                    picked.append(v)
                    break
            if len(picked) >= limit:
                break
    return picked


def cluster(items, threshold):
    if len(items) < 2:
        return [[i] for i in items]
    docs = [f"{i['title']} {i['title']} {i['text']}" for i in items]  # title counts double
    vec = TfidfVectorizer(stop_words="english", ngram_range=(1, 2), min_df=1, sublinear_tf=True)
    matrix = vec.fit_transform(docs).toarray()
    labels = AgglomerativeClustering(
        n_clusters=None, metric="cosine", linkage="average", distance_threshold=threshold,
    ).fit_predict(matrix)
    groups = {}
    for item, label in zip(items, labels):
        groups.setdefault(label, []).append(item)
    return list(groups.values())


def story_buzz(members):
    best = max(members, key=lambda m: m["buzz"]["hn_points"])["buzz"]
    top = max(members, key=lambda m: m["buzz"]["mastodon"])["buzz"]
    return {"mastodon": sum(m["buzz"]["mastodon"] for m in members), "mastodon_host": top["mastodon_host"],
            "hn_points": best["hn_points"], "hn_id": best["hn_id"]}


def make_story(members, covered_sides):
    """One story from its members (one entry per outlet already)."""
    leans = {m["lean"] for m in members}
    return {
        "members": members,
        "missing": [l for l in ("left", "right") if l in covered_sides and l not in leans]
        if len(members) >= 3 else [],
        "newest": max(m["when"] for m in members),
        "buzz": {**story_buzz(members), "bluesky": None},
    }


def one_per_outlet(group):
    by_source = {}
    for i in sorted(group, key=lambda i: i["when"], reverse=True):
        by_source.setdefault(i["source"], i)
    return list(by_source.values())


def sort_stories(stories):
    stories.sort(key=lambda s: (len(s["members"]), s["newest"]), reverse=True)
    return stories


def build_stories(items, threshold, singles=None):
    """Multi-outlet stories. Single-outlet items go into `singles` if a list is given."""
    # only call something a blind spot if this section has outlets on that side at all
    covered_sides = {i["lean"] for i in items}
    stories = []
    for group in cluster(items, threshold):
        members = one_per_outlet(group)  # one entry per outlet within a story
        if len(members) < 2:
            if singles is not None:
                singles.extend(members)
            continue  # a story only one outlet ran isn't shown in the main view
        stories.append(make_story(members, covered_sides))
    return sort_stories(stories)


TOPIC_ORDER = ("us", "world", "tech")


def merge_related(by_topic, articles, threshold):
    """Second pass: join stories that are the same event but were split by topic or by wording.

    Stories are compared as a whole (all their headlines together) and joined when they are close enough. Because it
    works across topics, one event no longer shows up once under US and again under World. A merged story goes in the
    topic most of its outlets filed it under (US, then World, then Tech on a tie). Returns {topic: [stories]}.
    """
    flat = [(t, st) for t in TOPIC_ORDER for st in by_topic.get(t, [])]
    if len(flat) < 2 or threshold <= 0:
        return by_topic
    used = {m["link"] for _, st in flat for m in st["members"]}
    docs = [" ".join(m["title"] for m in st["members"]) for _, st in flat]
    docs += [a["title"] for a in articles if a["link"] not in used]  # the rest of the day's headlines, so rare words count as rare
    vec = TfidfVectorizer(stop_words="english", sublinear_tf=True, token_pattern=r"[A-Za-z][A-Za-z'\u2019-]{2,}")
    matrix = vec.fit_transform(docs)[:len(flat)].toarray()
    labels = AgglomerativeClustering(n_clusters=None, metric="cosine", linkage="average",
                                     distance_threshold=threshold).fit_predict(matrix)
    groups = {}
    for (topic, st), lab in zip(flat, labels):
        groups.setdefault(lab, []).append((topic, st))
    covered = {t: {a["lean"] for a in articles if a["topic"] == t} for t in TOPIC_ORDER}
    out = {t: [] for t in TOPIC_ORDER}
    for g in groups.values():
        if len(g) == 1:
            out[g[0][0]].append(g[0][1])
            continue
        members = one_per_outlet([m for _, st in g for m in st["members"]])
        votes = Counter(m["topic"] for m in members)
        topic = max(TOPIC_ORDER, key=lambda t: (votes[t], -TOPIC_ORDER.index(t)))
        out[topic].append(make_story(members, covered[topic]))
    return {t: sort_stories(v) for t, v in out.items()}


# ---------- rendering ----------

e = html.escape
LEAN_LABEL = {"left": "Left", "center": "Center", "right": "Right"}
MAX_ROWS = 3  # headlines shown per side before "Show N more"
TITLES = {"us": "United States", "world": "World", "tech": "Technology"}
TABS_ALL = [("posts", "Clips"), ("us", "US"), ("world", "World"), ("tech", "Tech"), ("watch", "Videos")]
TABS = TABS_ALL  # rebuilt in main() from settings
CLIPS_ON = False  # clips and posts from social accounts; off unless settings.clips = true
FEEDS_ON = False  # Atom feeds need absolute addresses, so they are written only when settings.base_url is set
REPO_URL, LICENSE_NAME = "", ""  # from settings.repo_url and settings.license; empty shows the footer placeholders
SITE_URL = ""  # public address of this site, from settings.base_url; empty until it is hosted
OPEN_WITH = {}  # set from config: open some links through privacy front ends
SITE_NAME = "Tally News"  # the name lives here and nowhere else in the code; change it here
TAGLINE = "An open, forkable news aggregator. Your sources, your rules."
GROUP_TAGLINE = ""  # a group's own line, shown at the top of its news page
ICONS = {
    "news": '<path d="M5 5h11v14H7a2 2 0 0 1-2-2V5z"/><path d="M16 9h3v8a2 2 0 0 1-2 2"/><path d="M8 9h5M8 12h5M8 15h3"/>',
    "sources": '<path d="M9 7h10M9 12h10M9 17h10"/><path d="M5 7h.01M5 12h.01M5 17h.01"/>',
    "settings": '<path d="M5 8h8M17 8h2M5 16h2M11 16h8"/><circle cx="15" cy="8" r="2"/><circle cx="9" cy="16" r="2"/>',
    "latest": '<path d="M12 7v5l3 2"/><circle cx="12" cy="12" r="8"/>',
    "manage": '<path d="M12 5v14M5 12h14"/><rect x="3" y="3" width="18" height="18" rx="4"/>',
    "fork": '<circle cx="7" cy="6" r="2"/><circle cx="7" cy="18" r="2"/><circle cx="17" cy="8" r="2"/><path d="M7 8v8M17 10v1a3 3 0 0 1-3 3h-4a3 3 0 0 0-3 3"/>',
}
PAGES = [("index.html", "news", "News"), ("latest.html", "latest", "Latest"), ("sources.html", "sources", "Sources"),
         ("settings.html", "settings", "Settings")]
LAYOUT = (ROOT / "template" / "layout.html").read_text()
WORKBENCH = False  # True when building your own copy (python build.py --workbench), see workbench.py
WB_REPORT = None   # what the workbench changed from the defaults
NO_BUZZ_TEXT = ""


def fmt(n):
    if n >= 1_000_000:
        return f"{n / 1e6:.1f}M".replace(".0M", "M")
    if n >= 1_000:
        return f"{n / 1e3:.1f}K".replace(".0K", "K")
    return str(n)


def buzz_html(b):
    parts = []
    if b["mastodon"]:
        text = f'shared by {fmt(b["mastodon"])} people on Mastodon'
        host = b.get("mastodon_host")
        # Mastodon has no page for one article, so this opens its list of trending links
        parts.append(f'<a href="https://{host}/explore/links" target="_blank" rel="noopener" '
                     f'title="Opens Mastodon\'s trending links. The list changes through the day.">{text}</a>'
                     if host in MASTODON else text)
    if b.get("bluesky"):
        t = b["bluesky"]
        text = f'trending on Bluesky: “{e(t["name"])}” ({fmt(t["posts"])} posts)'
        parts.append(f'<a href="{e(t["url"])}" target="_blank" rel="noopener" title="Opens this topic on Bluesky.">{text}</a>'
                     if t.get("url") else text)
    if b["hn_points"]:
        parts.append(f'<a href="https://news.ycombinator.com/item?id={e(str(b["hn_id"]))}" target="_blank" '
                     f'rel="noopener">{fmt(b["hn_points"])} points on Hacker News</a>')
    return " · ".join(parts)


def pill(lean):
    return f'<span class="pill lean-{lean}"><i></i>{LEAN_LABEL[lean]}</span>'


TYPE_LABEL = {"wire": "Wire service", "public": "Public broadcaster", "state": "State-funded", "nonprofit": "Nonprofit", "commercial": "Commercial"}


def type_badge(item):
    """How an outlet is funded or owned, when that is known. A plain fact, not a rating."""
    t = item.get("type")
    return f'<span class="badge type" title="How this outlet is funded or owned (one maintainer\'s classification)">{TYPE_LABEL.get(t, e(t))}</span>' if t else ""


def _vthumb(v):
    local = v.get("poster_local")
    return f'<img loading="lazy" src="{e(local)}" alt="">' if local and (SITE_DIR / local).exists() else ""


def _vage(v):
    """How old the video is, so freshness is visible. The text is kept current by script; the clock time shows without it."""
    iso = v["when"].astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    return f'<time class="vage" datetime="{iso}" data-since>{e(clock(v["when"]))}</time>'


def render_video(v):
    views = f'<span class="views">{fmt(v["views"])} views</span>' if v.get("views") else ""
    return f"""<a class="video" data-lean="{v['lean']}" data-source="v:{e(v['source'])}" href="{e(social.open_url(v['link'], OPEN_WITH))}" target="_blank" rel="noopener">
  <span class="thumb">{_vthumb(v)}</span>
  <span class="vmeta">{pill(v['lean'])}<span>{e(v['source'])}</span>{_vage(v)}{views}</span>
  <span class="vtitle">{e(v['title'])}</span>
</a>"""


def render_video_row(v):
    """The compact version for the side rail on wide screens: small thumbnail, title, then who and how old."""
    return f"""<a class="video" data-lean="{v['lean']}" data-source="v:{e(v['source'])}" href="{e(social.open_url(v['link'], OPEN_WITH))}" target="_blank" rel="noopener">
  <span class="thumb">{_vthumb(v)}</span>
  <span class="vbody"><span class="vtitle">{e(v['title'])}</span>
  <span class="vmeta">{pill(v['lean'])}<span class="vsrc">{e(v['source'])}</span>{_vage(v)}</span></span>
</a>"""


def render_singles(items, topic="tech"):
    rows = "".join(
        f'<li data-lean="{i["lean"]}" data-source="a:{e(i["source"])}">'
        f'<a class="hl" href="{e(i["link"])}" target="_blank" rel="noopener">{e(i["title"])}</a>'
        f'<span class="src">{pill(i["lean"])}<span>{e(i["source"])}</span>'
        f'{"<span class=buzz>" + buzz_html(i["buzz"]) + "</span>" if buzz_html(i["buzz"]) else ""}</span></li>'
        for i in items)
    if not rows:
        return ""
    return (f'<details class="singles"><summary class="also">Reported by one outlet'
            f'<span class="n">{len(items)}</span></summary><ul class="briefs">{rows}</ul></details>')


def story_row(m):
    when = m.get("when")
    return (f'<li data-lean="{m["lean"]}" data-source="a:{e(m["source"])}"{f" data-t={int(when.timestamp())}" if when else ""}>'
            f'<a class="hl" href="{e(m["link"])}" target="_blank" rel="noopener">{e(m["title"])}</a>'
            f'<span class="src"><span>{e(m["source"])}</span></span></li>')


def label_note(kind, src):
    """When no words are shared, the label is the earliest headline, and we say whose it is."""
    if kind == "earliest":
        return f'<p class="lead-src">Earliest headline, from {e(src)}. These outlets share no wording.</p>'
    return ""


def mark_breaking(stories, now, s):
    """Flag stories that look like they are unfolding right now. One stated rule, no judgment about importance:

    a story is breaking when its first report is at most `breaking_max_age_h` hours old and either
      - at least `breaking_min_outlets` outlets have it and at least `breaking_min_recent` of them reported in the last
        `breaking_recent_min` minutes (still spreading), or
      - at least 2 outlets have it and its first report is under `breaking_fresh_min` minutes old (brand new).
    Report times are the times the outlets' own feeds give. At most `breaking_max` stories are shown.
    """
    if not s.get("breaking", True):
        return []
    max_age = timedelta(hours=s.get("breaking_max_age_h", 4))
    recent_w = timedelta(minutes=s.get("breaking_recent_min", 60))
    fresh_w = timedelta(minutes=s.get("breaking_fresh_min", 45))
    out = []
    for st in stories:
        times = sorted(m["when"] for m in st["members"])
        first, n = times[0], len(times)
        age = now - first
        recent = sum(1 for t in times if now - t <= recent_w)
        spreading = n >= s.get("breaking_min_outlets", 3) and recent >= s.get("breaking_min_recent", 2)
        brand_new = n >= 2 and age <= fresh_w
        if age <= max_age and (spreading or brand_new):
            st["breaking"] = {"first": first, "recent": recent}
            out.append(st)
    out.sort(key=lambda st: (st["breaking"]["recent"], len(st["members"]), st["newest"]), reverse=True)
    keep = out[:s.get("breaking_max", 4)]
    for st in out[len(keep):]:
        st.pop("breaking", None)  # qualified but cut by the limit: no badge, no priority
    return keep


def mark_blindspots(stories, cfg, now, s, skip=()):
    """Stories that only one side has covered. One stated rule, no judgment about importance or truth:

    a story is a blindspot when at least `blindspot_min_outlets` outlets have it, every one of them is labelled
    left (or every one right), its first report is at least `blindspot_min_age_h` hours old (so the other sides have had
    time), and the section it sits in has outlets from the other sides to compare with. Labels are one maintainer's
    judgment. Most outlets first; at most `blindspot_max` shown. Stories in Breaking are skipped: they are still unfolding.
    """
    if not s.get("blindspots", True):
        return []
    min_age = timedelta(hours=s.get("blindspot_min_age_h", 3))
    sides = {}
    for f in cfg["feeds"]:
        sides.setdefault(f.get("topic", "us"), set()).add(f["lean"])
    out = []
    for st in stories:
        if id(st) in skip:
            continue
        leans = {m["lean"] for m in st["members"]}
        if len(st["members"]) < s.get("blindspot_min_outlets", 3) or len(leans) != 1:
            continue
        side = next(iter(leans))
        others = [l for l in LEANS if l != side and l in sides.get(st.get("topic", "us"), ())]
        if side == "center":
            continue
        if not others or now - min(m["when"] for m in st["members"]) < min_age:
            continue
        st["blindspot"] = {"side": side, "others": others}
        out.append(st)
    out.sort(key=lambda st: (len(st["members"]), st["newest"]), reverse=True)
    return out[:s.get("blindspot_max", 6)]


def render_blindspots(stories, hours_back):
    rows = ""
    for st in stories:
        b, n = st["blindspot"], len(st["members"])
        rows += (f'<li data-lean="{b["side"]}"><a class="hl" href="#s-{st.get("sid", "")}">{e(st["label"])}</a>'
                 f'<span class="src">{pill(b["side"])}<span>{n} outlets, all labelled {b["side"]}. '
                 f'Nothing yet from {" or ".join(b["others"])} outlets.</span></span></li>')
    return (f'<section data-section id="blindspots"><h2 class="sec">Blindspots</h2>'
            f'<p class="sec-note">Stories that only one side has covered so far, among the outlets we track. Not a claim that anyone is hiding it: '
            f'<a href="methods.html#blindspots">how this is decided</a></p>'
            f'<ul class="briefs blind">{rows}</ul>'
            f'<p class="none-left" hidden>Everything here is hidden by your settings.</p></section>')


def render_story(s):
    by_lean = {l: [m for m in s["members"] if m["lean"] == l] for l in LEANS}
    counts = {l: len(v) for l, v in by_lean.items()}
    bar = "".join(f'<span class="seg lean-{l}" data-lean="{l}" style="flex-grow:{counts[l]}"></span>'
                  for l in LEANS if counts[l])
    gap = {l: f'<span class="seg-gap lean-{l}" aria-hidden="true"></span>' for l in s["missing"]}  # a side that did not cover it, drawn as an empty slot
    bar = gap.get("left", "") + bar + gap.get("right", "")
    legend = "".join(f'<span class="k lean-{l}" data-lean="{l}"><i></i>{LEAN_LABEL[l]} <b>{counts[l]}</b></span>' for l in LEANS)
    groups = ""
    for l in LEANS:
        rows = [story_row(m) for m in by_lean[l]]
        head, tail = rows[:MAX_ROWS], rows[MAX_ROWS:]
        more = (f'<details class="more"><summary>Show {len(tail)} more</summary><ul>{"".join(tail)}</ul></details>'
                if tail else "")
        groups += (f'<section class="group lean-{l}" data-lean="{l}"><h4><i></i>{LEAN_LABEL[l]}'
                   f'<span class="n">{counts[l]}</span></h4><ul>{"".join(head)}</ul>{more}'
                   f'<p class="none"{" hidden" if rows else ""}>No coverage from this side.</p></section>')
    b = buzz_html(s["buzz"])
    buzz = f'<span class="buzz">{b}</span>' if b else ""
    flag = ""
    if s["missing"]:
        flag = f'<span class="badge gap">Not covered by: {" and ".join(s["missing"])}</span>'
    sid = s.get("sid", "")
    sm = s.get("summary")
    summary = (f'<div class="s-summary"><p>{e(sm["text"])}</p><p class="s-by">Machine-written from the outlets’ own excerpts, '
               f'so it can be wrong. The headlines below are the outlets’ own. <a href="methods.html#summaries">How this works</a></p></div>'
               if sm else "")
    bk = s.get("breaking")
    bflag = (f'<span class="s-flag"><span class="badge brk">Breaking</span><span class="s-ago"><time datetime="{bk["first"].astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")}" '
            f'data-ago>{e(clock(bk["first"]))}</time></span></span>') if bk else ""
    chev = '<svg class="chev" viewBox="0 0 24 24" aria-hidden="true"><path d="m7 10 5 5 5-5"/></svg>'
    return f"""<article class="story" id="s-{sid}" data-t="{int(s['newest'].timestamp())}">
  <h3><button class="s-head" type="button" aria-expanded="false" aria-controls="p-{sid}">
    <span class="s-main"><span class="s-title">{e(s["label"])}</span>{bflag}</span>
    <span class="s-sum"><span class="bar" role="img" aria-label="Outlets covering this story: left {counts['left']}, center {counts['center']}, right {counts['right']}">{bar}</span>
    <span class="s-count"><b class="n-total">{len(s['members'])}</b> <span class="w">outlets</span></span><span class="badge new" hidden>New</span></span>{chev}
  </button></h3>
  <div class="s-panel" id="p-{sid}" hidden>
  {summary}{label_note(s["label_kind"], s["label_src"])}
  <p class="legend">{legend}</p>
  <p class="meta">{flag}{buzz}<a class="sp" href="story/{sid}.html">Story page</a></p>
  {render_facts(s, tucked=bool(sm))}
  <div class="groups">{groups}</div>
  </div>
</article>"""


def tm(dt):
    """A time element: readable with no script, and shown in the reader's own time zone once the script runs."""
    iso = dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    return f'<time datetime="{iso}" data-clock>{e(clock(dt))}</time>'


def render_facts(s, tucked=False):
    """When it was first reported, and a timeline of who reported when (one lane per side).
    With a summary on the page, the first-reported sentence moves inside the timeline instead of opening the story."""
    f = s["facts"]
    rows = "".join(
        f'<tr data-lean="{m["lean"]}" data-source="a:{e(m["source"])}">'
        f'<td>{tm(m["when"])}</td><td>{LEAN_LABEL[m["lean"]]}</td><td>{e(m["source"])}</td></tr>' for m in f["ordered"])
    line = f'<p class="facts-line">{facts_sentence(f, s["missing"])}</p>'
    return f"""<div class="facts">{"" if tucked else line}
  <details class="timeline"><summary>{"Who reported when" if tucked else "Coverage timeline"}</summary>
  {line if tucked else ""}{lanes_html(f["ordered"])}
  <details class="tbl"><summary>Show as a table</summary><table><thead><tr><th>Time</th><th>Side</th><th>Outlet</th></tr></thead><tbody>{rows}</tbody></table></details>
  <p class="mlink"><a href="methods.html#timeline">How this is worked out</a></p></details></div>"""


def chart_story_rows(stories):
    """One row per story: its label (a link to its page), then a bar as long as its outlet count, split by side."""
    if not stories:
        return '<p class="empty">No stories match.</p>'
    top = max(len(s["members"]) for s in stories)
    rows = ""
    for s in stories:
        counts = {l: sum(1 for m in s["members"] if m["lean"] == l) for l in LEANS}
        segs = "".join(f'<span class="seg lean-{l}" style="flex-grow:{counts[l]}" title="{LEAN_LABEL[l]}: {counts[l]} outlets"></span>'
                       for l in LEANS if counts[l])
        gaps = "".join(f'<span class="seg-gap lean-{l}" title="No {l}-side coverage"></span>' for l in s["missing"])
        width = max(100 * len(s["members"]) / top, 8)
        nums = " &middot; ".join(f'{LEAN_LABEL[l][0]} {counts[l]}' for l in LEANS)
        rows += (f'<li data-topic="{s.get("topic", "")}"><a class="c-label" href="story/{s.get("sid", "")}.html">{e(s["label"])}</a>'
                 f'<span class="c-track"><span class="c-bar bar" style="width:{width:.1f}%">{gaps if "left" in s["missing"] else ""}{segs}{gaps if "right" in s["missing"] else ""}</span>'
                 f'<span class="c-n"><b>{len(s["members"])}</b> <span class="c-sides" aria-label="Left {counts["left"]}, center {counts["center"]}, right {counts["right"]}">{nums}</span></span></span></li>')
    legend = "".join(f'<span class="k lean-{l}"><i></i>{LEAN_LABEL[l]}</span>' for l in LEANS)
    by_topic = Counter(s.get("topic") for s in stories)
    chips = "".join(f'<button type="button" aria-pressed="false" data-topic="{t}">{e(TITLES[t])} <b>{by_topic[t]}</b></button>'
                    for t in TOPIC_ORDER if by_topic[t])
    filt = (f'<div class="c-filter" role="group" aria-label="Show stories from"><button type="button" aria-pressed="true" data-topic="">'
            f'All <b>{len(stories)}</b></button>{chips}</div>') if len(by_topic) > 1 else ""
    return (f'{filt}<p class="legend c-legend">{legend}<span class="k"><i class="dash"></i>No coverage from that side</span></p>'
            f'<ol class="c-rows">{rows}</ol>')


def chart_time_columns(stories, hours_back, step=3):
    """Stories by when they were first reported, in three-hour steps counted back from now, oldest on the left."""
    now = datetime.now(timezone.utc)
    n = -(-hours_back // step)
    counts = [0] * n
    for s in stories:
        age = (now - s["facts"]["first"]["when"]).total_seconds() / 3600
        counts[min(max(int(age // step), 0), n - 1)] += 1
    counts.reverse()  # oldest first
    top = max(max(counts), 1)
    spans = [f"{(n - 1 - k) * step}\u2013{(n - k) * step} h ago" if (n - 1 - k) else f"last {step} h" for k in range(n)]
    cols = "".join(f'<li title="{spans[k]}: {c} stories"><span class="t-bar" style="height:{100 * c / top:.1f}%"></span>'
                   f'<b>{c}</b></li>' for k, c in enumerate(counts))
    rows = "".join(f"<tr><td>{spans[k]}</td><td>{c}</td></tr>" for k, c in enumerate(counts))
    return (f'<ol class="t-cols" role="img" aria-label="Stories first reported, per {step}-hour step, oldest to newest: {", ".join(map(str, counts))}">{cols}</ol>'
            f'<p class="t-axis"><span>{n * step} h ago</span><span>now</span></p>'
            f'<details class="tbl"><summary>Show as a table</summary><table><thead><tr><th>When first reported</th><th>Stories</th></tr></thead>'
            f'<tbody>{rows}</tbody></table></details>')


def chart_outlet_rows(articles):
    """Articles per outlet, one bar each, in the outlet's side colour."""
    per = Counter(a["source"] for a in articles)
    lean = {a["source"]: a["lean"] for a in articles}
    top = max(per.values())
    rows = ""
    for n, c in per.most_common():
        l, w = lean[n], max(100 * c / top, 3)
        rows += (f'<li class="lean-{l}"><span class="c-label">{e(n)} <span class="c-side">{LEAN_LABEL[l]}</span></span>'
                 f'<span class="c-track"><span class="c-bar bar" style="width:{w:.1f}%"><span class="seg lean-{l}" style="flex-grow:1"></span></span>'
                 f'<span class="c-n"><b>{c}</b></span></span></li>')
    return f'<ol class="c-rows">{rows}</ol>'


def chart_side_rows(articles):
    """Outlets that published something in this update, counted by side."""
    sides = {}
    for a in articles:
        sides[a["source"]] = a["lean"]
    counts = Counter(sides.values())
    top = max(counts.values())
    rows = "".join(
        f'<li class="lean-{l}"><span class="c-label">{LEAN_LABEL[l]}</span><span class="c-track">'
        f'<span class="c-bar bar" style="width:{max(100 * counts[l] / top, 3):.1f}%"><span class="seg lean-{l}" style="flex-grow:1"></span></span>'
        f'<span class="c-n"><b>{counts[l]}</b></span></span></li>' for l in LEANS)
    return (f'<ol class="c-rows">{rows}</ol>'
            f'<p class="muted-note">Sides are one maintainer&rsquo;s judgment. '
            f'<a href="sources.html">See every outlet</a></p>')


def stat_panels(stories, articles, hours_back):
    """What opens under each number in the stat strip."""
    three = [s for s in stories if s["facts"]["all_sides_at"]]
    return {
        "stories": ("Every story, most outlets first", "Each row is a story. Select it to open its page. The bar is split by side.", chart_story_rows(stories)),
        "articles": ("Articles per outlet", "How many articles each outlet contributed to this update.", chart_outlet_rows(articles)),
        "outlets": ("Outlets by side", "How many outlets published something in this update, by side.", chart_side_rows(articles)),
        "time": ("When stories were first reported", f"Stories by the time their first report appeared among the outlets we track, in three-hour steps over the last {hours_back} hours. A story counts once, in the step of its first report.",
                 chart_time_columns(stories, hours_back)),
        "three": ("Stories covered by all three sides", "", chart_story_rows(three)),
        "no_right": ("Stories with no right-side coverage", "", chart_story_rows([s for s in stories if "right" in s["missing"]])),
        "no_left": ("Stories with no left-side coverage", "", chart_story_rows([s for s in stories if "left" in s["missing"]])),
    }


def render_today(sm, panels, hours_back):
    """One compact strip of counts for the whole update. Each number opens a chart of what it counts."""
    cells = [("stories", sm["stories"], "stories"), ("articles", sm["articles"], "articles"), ("outlets", sm["outlets"], "outlets"),
             ("three", sm["all_three"], "all 3 sides")]
    cells.append(("time", f"{hours_back} h", "timeline"))
    if sm["no_right"]:
        cells.append(("no_right", sm["no_right"], "no right side"))
    if sm["no_left"]:
        cells.append(("no_left", sm["no_left"], "no left side"))
    items = "".join(f'<li><button type="button" class="stat" data-stat="{k}" aria-expanded="false" aria-controls="stat-{k}">'
                    f'<b>{n}</b><span>{e(w)}</span></button></li>' for k, n, w in cells)
    shown = {k for k, _, _ in cells}
    body = "".join(
        f'<section class="stat-panel" id="stat-{k}" hidden aria-label="{e(t)}"><div class="sp-head"><h3>{e(t)}</h3>'
        f'<button type="button" class="sp-close" data-close>Close</button></div>'
        f'{f"<p class=muted-note>{e(d)}</p>" if d else ""}<div class="sp-body">{html_}</div></section>'
        for k, (t, d, html_) in panels.items() if k in shown)
    fast = ""
    if sm["fastest"]:
        took, st = sm["fastest"]
        fast = f' Quickest to reach all three sides: {fmt_dur(took)}, {e(st["label"])}.'
    return (f'<div class="today"><ul class="stat-strip" aria-label="Counts for this update. Select one to see what it counts.">{items}</ul>'
            f'{body}<p>Select a number to see what it counts. Counts cover every outlet, whatever your switches say.{fast} '
            f'<a href="methods.html#counts">How these are counted</a></p></div>')


PLAY = '<svg viewBox="0 0 24 24" width="26" height="26" aria-hidden="true"><path d="M8 5.5v13l11-6.5z"/></svg>'
SITE_DIR = ROOT / "site"


def cache_poster(url, site):
    """Keep a copy of a clip's preview frame on this site, so a reader's browser contacts nothing external until they
    tap play. Returns the path under site/, or None."""
    name = hashlib.sha1(url.encode()).hexdigest()[:16]
    folder = site / "clips"
    for ext in ("jpg", "png", "webp"):
        if (folder / f"{name}.{ext}").exists():
            return f"clips/{name}.{ext}"
    data = get(url)
    if not data or len(data) > 600_000:
        return None
    ext = ("jpg" if data[:2] == b"\xff\xd8" else "png" if data[:4] == b"\x89PNG"
           else "webp" if data[:4] == b"RIFF" and data[8:12] == b"WEBP" else None)
    if not ext:
        return None
    folder.mkdir(exist_ok=True)
    tmp = folder / f"{name}.{ext}.tmp"
    tmp.write_bytes(data)
    os.replace(tmp, folder / f"{name}.{ext}")
    return f"clips/{name}.{ext}"


def attach_posters(posts, site, limit=60):
    done = 0
    for p in posts:
        m = p.get("media")
        if not m or not m.get("poster") or done >= limit:
            continue
        done += 1
        try:
            local = cache_poster(m["poster"], site)
        except Exception as ex:
            print(f"  preview frame skipped for {p['source']}: {ex}", file=sys.stderr)
            continue
        if local:
            m["poster_local"] = local


def clip_card(p, base="", match=None):
    """A clip as a tall card: tap to play it in the clips viewer. Posts with nothing playable here link out instead."""
    m, plat = p.get("media"), social.NAMES[p["platform"]]
    text = p["text"]
    snippet = text if len(text) <= 120 else text[:119].rstrip() + "\u2026"
    when = p["when"]
    common = f'data-lean="none" data-source="s:{e(p["source"])}"'
    link = e(social.open_url(p["url"], OPEN_WITH))
    below = (f'<span class="src"><a href="{base}story/{match[0]}.html" title="Matches story: {e(match[1])}">Matches: {e(match[1])}</a></span>'
             if match else '<span class="src slot" aria-hidden="true">&nbsp;</span>')  # a fixed slot, so cards line up whether or not they match
    if not m:
        return (f'<li class="clip" {common} data-kind="link"><a class="clip-card clip-text" href="{link}" target="_blank" rel="noopener noreferrer">'
                f'<span class="clip-cap">{e(snippet) or "(no caption)"}</span>'
                f'<span class="clip-src">{plat} &middot; {e(p["source"])} &middot; {tm(when)}<br><b>Open on {plat}</b></span></a>{below}</li>')
    local = m.get("poster_local")
    if local and not (SITE_DIR / local).exists():
        local = None
    poster = (f'<img class="clip-poster" src="{base}{e(local)}" alt="" loading="lazy">' if local else '<span class="clip-poster blank"></span>')
    story = f' data-story="{match[0]}" data-story-title="{e(match[1])}"' if match else ""
    return (f'<li class="clip" {common} data-kind="{m["kind"]}" data-src="{e(m["src"])}" data-poster="{e(local or "")}" '
            f'data-w="{m.get("w") or ""}" data-h="{m.get("h") or ""}" data-url="{link}" data-name="{e(p["source"])}" '
            f'data-platform="{plat}" data-t="{int(when.timestamp())}" data-text="{e(text)}" data-alt="{e(m.get("alt", ""))}"{story}>'
            f'<button class="clip-card" type="button" aria-label="Play clip from {e(p["source"])}: {e(snippet)}">{poster}'
            f'<span class="clip-play" aria-hidden="true">{PLAY}</span>'
            f'<span class="clip-scrim"><b>{e(p["source"])}</b><span class="clip-cap">{e(snippet)}</span></span></button>{below}</li>')


def posts_section(posts, matched, followed):
    if not followed:
        body = '<p class="empty">No accounts are followed yet. Add some under <code>[[social]]</code> in config/sources.toml (see Run your own).</p>'
    elif not posts:
        body = '<p class="empty">Nothing new from the accounts you follow in this update.</p>'
    else:
        rows = ""
        for p in posts[:40]:
            st = matched.get(p["url"])
            rows += clip_card(p, match=(st["sid"], archive_lead(st)) if st and st.get("sid") else None)
        body = ('<p class="muted-note">Newest first. Tap to watch. Nothing plays by itself, and we have not checked any of it. '
                '<a href="methods.html#social">How this works</a></p>'
                f'<ul class="clips">{rows}</ul>'
                '<button class="btn all-clips" id="allClips" type="button" aria-expanded="false" hidden>Show all clips</button>')
    return (f'<section data-section id="posts"><h2 class="sec">Clips and posts</h2>{body}'
            f'<p class="none-left" hidden>Everything here is hidden by your settings.</p></section>')


def archive_lead(story):
    """The neutral label; stories that were not annotated for the page (archive-only ones) get it computed here."""
    return story.get("label") or analytics.story_label(story["members"])[0]


def social_row(c, hours):
    key = f's:{c["name"]}'
    n = c.get("_n")
    if c.get("_err"):
        status = f'Could not load: {e(c["_err"])}'
    elif n:
        status = f'{n} {"clip or post" if n == 1 else "clips and posts"} in the last {hours} hours'
    else:
        status = f"Nothing in the last {hours} hours"
    try:
        href = social.profile_url(c)
    except ValueError:
        href = "#"
    return f"""<li class="src-row" data-source="{e(key)}" data-lean="none">
  <div class="s-main"><div class="s-name"><b>{e(c['name'])}</b></div><div class="s-host"><a href="{e(href)}" target="_blank" rel="noopener">{e(c['handle'])}</a></div></div>
  <div class="s-meta"><span class="badge plat">{social.NAMES.get(c['platform'], e(c['platform']))}</span><span>{status}</span><span class="s-note" hidden>Hidden by your Show settings</span></div>
  <button class="trow" role="switch" aria-checked="true" aria-label="Show {e(c['name'])}"><span class="knob" aria-hidden="true"></span></button>
</li>"""


def toggle(path, label_html):
    return (f'<button class="trow" role="switch" data-set="{path}"><span class="lbl">{label_html}</span>'
            f'<span class="knob" aria-hidden="true"></span></button>')


def primary_nav(active, base=""):
    out = ""
    for href, key, label in PAGES + ([("manage.html", "manage", "Manage")] if WORKBENCH else []):
        cur = ' aria-current="page"' if key == active else ""
        out += (f'<a href="{base}{href}"{cur}><svg class="ic" viewBox="0 0 24 24" aria-hidden="true">{ICONS[key]}</svg>'
                f'{"<span class=nl>Run your own</span><span class=ns>Fork</span>" if key == "fork" else f"<span>{label}</span>"}</a>')
    return out


def write_atomic(path, data):
    """Write a file so a reader never sees it half-written."""
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(data)
    os.replace(tmp, path)


def write_if_changed(path, data):
    """Write only when the content differs, so unchanged story pages are left alone. Returns 1 if written."""
    if path.exists() and path.read_text() == data:
        return 0
    write_atomic(path, data)
    return 1


def wb_banner(base=""):
    """On the workbench only: how far this copy has moved from the defaults, and the way back."""
    if not WORKBENCH or not WB_REPORT:
        return ""
    r = WB_REPORT
    bits = []
    if r["removed"]:
        bits.append(f'removed <b>{len(r["removed"])}</b> of {r["defaults"]} defaults')
    if r["added"]:
        bits.append(f'added <b>{len(r["added"])}</b>')
    if r["relabeled"]:
        bits.append(f'relabeled <b>{len(r["relabeled"])}</b>')
    text = ("Workbench: " + ", ".join(bits) + ".") if bits else "Workbench: this copy matches the default list."
    return (f'<p class="wb-banner"><span>{text}</span> <a href="{base}manage.html">Manage sources</a>'
            f'{f" &middot; <a href={chr(34)}{base}manage.html#removed{chr(34)}>Restore</a>" if r["removed"] else ""}</p>')


def feed_head_links(base=""):
    """Lets feed readers find the feeds from any page."""
    if not FEEDS_ON:
        return ""
    return "".join(f'<link rel="alternate" type="application/atom+xml" title="{e(SITE_NAME)}{e(t)}" href="{base}{f}">'
                   for f, t in (("feed.xml", ""), ("breaking.xml", " · Breaking"), ("blindspots.xml", " · Blindspots")))


def subscribe_line(base=""):
    feeds = (f'<a href="{base}feed.xml">Atom feed</a>, <a href="{base}breaking.xml">Breaking</a> and '
             f'<a href="{base}blindspots.xml">Blindspots</a> feeds, and ') if FEEDS_ON else ""
    return (f'<p><b>Follow without an account:</b> {feeds}<a href="{base}sources.opml">the source list as OPML</a>. '
            f'Add any of them to a feed reader, or to another copy of this project as a source. <a href="{base}methods.html#feeds">What is in them</a></p>')


def fill_repo(text):
    """Fill {repo_link} and {license_link} in a template page from settings.repo_url and settings.license."""
    code = f'<a href="{e(REPO_URL)}">{e(REPO_URL.removeprefix("https://"))}</a>' if REPO_URL else '<span class="ph">not published yet</span>'
    lic = (f'<a href="{e(REPO_URL)}/blob/main/LICENSE">{e(LICENSE_NAME)}</a>' if REPO_URL and LICENSE_NAME
           else e(LICENSE_NAME) if LICENSE_NAME else '<span class="ph">not chosen yet</span>')
    return text.replace("{repo_link}", code).replace("{license_link}", lic)


def source_line(base=""):
    """The footer's source-code and license line: real links once settings.repo_url and settings.license are set."""
    code = (f'<a href="{e(REPO_URL)}">{e(REPO_URL.removeprefix("https://"))}</a>' if REPO_URL else '<span class="ph">not published yet</span>')
    lic = (f'<a href="{e(REPO_URL)}/blob/main/LICENSE">{e(LICENSE_NAME)}</a>' if REPO_URL and LICENSE_NAME
           else e(LICENSE_NAME) if LICENSE_NAME else '<span class="ph">not chosen yet</span>')
    return f'Source code: {code} &middot; License: {lic} &middot; <a href="{base}fork.html">Run your own copy</a>'


def page(title, key, content, built, base=""):
    # content goes in last: it holds real headlines, which must never be mistaken for placeholders
    return (LAYOUT.replace("{primary_nav}", primary_nav(key, base))
            .replace("<main id=\"main\" tabindex=\"-1\">{content}", "<main id=\"main\" tabindex=\"-1\">" + wb_banner(base) + "{content}")
            .replace("{base}", base)
            .replace("{site_name}", SITE_NAME)
            .replace("{tagline}", e(TAGLINE))
            .replace("{source_line}", source_line(base))
            .replace("{feed_links}", feed_head_links(base))
            .replace("{subscribe}", subscribe_line(base))
            .replace("{title}", e(title))
            .replace("{page}", key)
            .replace("{built}", str(built))
            .replace("{content}", content))


def source_row(kind, c, hours, stats=None, total=0):
    key = f'{kind}:{c["name"]}'
    if kind == "a":
        feed_url, unit = c["url"], "item"
        site = c.get("site") or "https://" + urllib.parse.urlsplit(feed_url).netloc
        sp = urllib.parse.urlsplit(site)
        shown = sp.netloc.removeprefix("www.") + sp.path.rstrip("/")
        links = (f'<a href="{e(site)}" target="_blank" rel="noopener">{e(shown)}</a> &middot; '
                 f'<a href="{e(feed_url)}" target="_blank" rel="noopener">{"watched page" if c.get("method") == "page" else "feed"}</a>')
    else:
        unit = "video"
        links = f'<a href="https://www.youtube.com/@{e(c["handle"])}" target="_blank" rel="noopener">youtube.com/@{e(c["handle"])}</a>'
    n = c.get("_n")
    if c.get("_err"):
        status = "Could not load in this build"
        if c.get("method") == "page":
            status += f": {e(c['_err'])}"
    elif c.get("_note") and c.get("method") == "page":
        status = e(c["_note"])
    elif n:
        status = f"{n} {unit}{'' if n == 1 else 's'} in the last {hours} hours"
    elif c.get("_total"):
        status = f"Loaded, but nothing newer than {hours} hours (the feed may be stale)"
    elif kind == "a":
        status = "Loaded, but the feed had no items"
    else:
        status = f"No videos in the last {hours} hours"
    if kind == "a" and c.get("_future"):
        status += f' <span class="s-stats">{c["_future"]} item{"" if c["_future"] == 1 else "s"} had a publish time in the future; we treated {"it" if c["_future"] == 1 else "them"} as just published.</span>'
    if kind == "a" and stats is not None:
        st = stats.get(c["name"], {"stories": 0, "first": 0})
        status += f' <span class="s-stats">In {st["stories"]} of {total} stories. Earliest report in {st["first"]}.</span>'
    return f"""<li class="src-row" data-source="{e(key)}" data-lean="{c['lean']}">
  <div class="s-main"><div class="s-name"><b>{e(c['name'])}</b>{type_badge(c)}</div><div class="s-host">{links}</div></div>
  <div class="s-meta">{pill(c['lean'])}<span>{status}</span><span class="s-note" hidden>Hidden by your Show settings</span></div>
  <button class="trow" role="switch" aria-checked="true" aria-label="Show {e(c['name'])}"><span class="knob" aria-hidden="true"></span></button>
</li>"""


def source_health(cfg, built, previous):
    """How each source did in this build, and for how many builds in a row it has been unhealthy.

    Status: ok (items in the window), quiet (loaded, nothing newer than the window), empty (a feed with no items at all),
    failed (could not load). `builds` counts consecutive builds with the same problem, so a one-off blip is not
    mistaken for a dead feed.
    """
    when = datetime.fromtimestamp(built, timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    out = {}
    for kind, entries in (("a", cfg["feeds"]), ("v", cfg["channels"])):
        for c in entries:
            key = f'{kind}:{c["name"]}'
            if c.get("_err"):
                status, detail = "failed", " ".join(str(c["_err"]).split())[:140]
            elif c.get("_n"):
                status, detail = "ok", ""
            elif c.get("_total") or kind == "v":
                status, detail = "quiet", ""
            else:
                status, detail = "empty", ""
            prev = previous.get(key) or {}
            if status == "ok":
                since, n = None, 0
            elif prev.get("status") == status:
                since, n = prev.get("since") or when, int(prev.get("builds", 1)) + 1
            else:
                since, n = when, 1
            out[key] = {"kind": kind, "name": c["name"], "status": status, "items": c.get("_n") or 0, "error": detail,
                        "since": since, "builds": n}
    return out


def sources_page(cfg, hours, updated, stats, total):
    groups = ""
    for topic in ("us", "world", "tech"):
        rows = sorted([f for f in cfg["feeds"] if f.get("topic", "us") == topic], key=lambda f: f["name"].lower())
        if rows:
            groups += (f'<h2>{TITLES[topic]} <span class="muted">· articles</span></h2><ul class="list">'
                       + "".join(source_row("a", f, hours, stats, total) for f in rows) + "</ul>")
    vids = sorted(cfg["channels"], key=lambda c: c["name"].lower())
    groups += '<h2>Videos <span class="muted">· YouTube channels</span></h2><ul class="list">' + "".join(source_row("v", c, hours) for c in vids) + "</ul>"
    if CLIPS_ON and cfg.get("social"):
        groups += ('<h2>Clips and posts <span class="muted">· accounts followed</span></h2><ul class="list">'
                   + "".join(social_row(c, hours) for c in cfg["social"]) + "</ul>")
    return f"""<div class="page">
<h1>Sources</h1>
<p class="lede">Every outlet this site reads, with the label it carries. Labels are one maintainer&rsquo;s judgment, not facts, and they are set in <code>config/sources.toml</code>. To change a label or add an outlet, edit that file and rebuild (see <a href="fork.html">Run your own</a>). The switches below only hide an outlet for you, in this browser. Counts are from the build made {e(updated)}; &ldquo;in N of M stories&rdquo; counts the stories on the news page (<a href="methods.html#outlets">how</a>).</p>
<div class="toolbar"><p id="srcCount"></p><button class="btn" id="allOn" type="button">Turn all on</button></div>
{groups}
</div>"""


def news_page(sections, videos, updated, counts, summary, panels, hours_back, posts_html="", breaking_html="", rail_videos=""):
    tabs = "".join(f'<a href="#{k}">{label}</a>' for k, label in TABS)
    rail_html = (f'<section class="rail-videos" aria-label="Videos"><h2 class="rv-head">Videos</h2>'
                 f'<div class="rv-list" role="region" aria-label="Videos, newest first" tabindex="0">{rail_videos}</div>'
                 f'<button class="btn rv-more" id="railMore" type="button" aria-expanded="false" hidden>Show all videos</button>'
                 f'<p class="none-left" hidden>Everything here is hidden by your settings.</p></section>') if rail_videos else ""
    index = (f'{counts["stories"]} stories &middot; <a href="latest.html">{counts["headlines"]:,} headlines</a> '
             f'&middot; <a href="sources.html">{counts["sources"]} sources</a>')
    return f"""<div class="tabs" id="tabs"><div class="tabs-in wrap" role="navigation" aria-label="Jump to section"><span class="jump">Jump to</span>{tabs}</div></div>
<div class="wrap"><div class="layout">
<div class="rail">
<aside class="side" aria-label="How this page works">
<p class="rule"><b>How items are ordered.</b> By how many different outlets covered a story, then by recency. Nothing learns from you. <a href="fork.html#ordering">Details</a></p>
<p class="side-links"><a href="settings.html">Defaults in Settings</a> &middot; <a href="sources.html">Sources</a> &middot; <a href="archive.html">Archive</a></p>
</aside>
{rail_html}
</div>
<div class="feed">
<h1 class="sr">{e(SITE_NAME)}: today&rsquo;s news</h1>
{f'<p class="tagline">{e(GROUP_TAGLINE)}</p>' if GROUP_TAGLINE else ""}<form class="home-find" action="latest.html" role="search"><label class="sr" for="hq">Search all headlines</label><input id="hq" name="q" type="search" autocomplete="off" placeholder="Search every headline"><button class="btn" type="submit">Search</button></form>
<div class="view" id="view" role="group" aria-label="Show coverage from">
<button type="button" data-view="all" aria-pressed="true">All sides</button>
<button type="button" data-view="left" aria-pressed="false">{pill("left")}</button>
<button type="button" data-view="center" aria-pressed="false">{pill("center")}</button>
<button type="button" data-view="right" aria-pressed="false">{pill("right")}</button>
</div>
<p class="view-chip" id="viewChip" role="status" hidden><span id="viewText"></span> <button type="button" class="linkbtn" id="viewClear" hidden>Show all sides</button> <a href="settings.html" id="viewSet" hidden>Change in Settings</a></p>
<p class="stamp">Updated {e(updated)} &middot; {index}</p>
<p class="since-row" id="sinceRow" hidden><span class="since" id="since"></span> <button type="button" class="linkbtn" id="newOnly" aria-pressed="false" hidden>New only</button> <button type="button" class="linkbtn" id="markSeen" hidden>Mark all seen</button></p>
{breaking_html}{posts_html}
{sections}
{render_today(summary, panels, hours_back)}
<section data-section id="watch"><h2 class="sec">Videos</h2>
<div class="videos" role="region" aria-label="Videos, scrolls sideways" tabindex="0">{videos}</div>
<button class="btn all-videos" id="allVideos" type="button" aria-expanded="false" hidden>Show all videos</button>
<p class="none-left" hidden>Everything here is hidden by your settings.</p></section>
<p class="end">You&rsquo;re caught up as of {e(updated)}. Nothing further is queued for you.</p>
</div></div></div>"""


def tick_steps(span):
    """Evenly spaced relative ticks (+6 h, +1 d) so a multi-day timeline never needs a time-zone guess."""
    step = 604800
    for candidate in (3600, 7200, 21600, 43200, 86400, 172800):
        if span / candidate <= 6:
            step = candidate
            break
    ticks, k = [], 1
    while k * step < span:
        p = k * step / span
        if 0.08 < p < 0.92:
            ticks.append((p, f"+{k * step // 3600} h" if step < 86400 else f"+{k * step // 86400} d"))
        k += 1
    return ticks


def lanes_html(ordered, ticks=False):
    """The three-lane timeline: one dot per outlet at its publish time. Used on cards and on story pages."""
    t0 = ordered[0]["when"].timestamp()
    span = max(ordered[-1]["when"].timestamp() - t0, 1)
    lanes = ""
    for l in LEANS:
        marks = "".join(
            f'<span class="mk" tabindex="0" data-lean="{l}" data-source="a:{e(m["source"])}" '
            f'data-name="{e(m["source"])}" data-t="{int(m["when"].timestamp())}" '
            f'style="--p:{(m["when"].timestamp() - t0) / span:.4f}" aria-label="{e(m["source"])}, {e(clock(m["when"]))}"></span>'
            for m in ordered if m["lean"] == l)
        lanes += (f'<div class="lane lean-{l}" data-lean="{l}"><span class="lane-label"><i></i>{LEAN_LABEL[l]}</span>'
                  f'<div class="track">{marks}</div></div>')
    axis = (f'<div class="axis"><span></span><div class="ends"><span class="a0">{tm(ordered[0]["when"])}</span>'
            f'<span class="a1">{tm(ordered[-1]["when"])}</span></div></div>')
    tick_row = ""
    if ticks:
        tick_row = ('<div class="axis"><span></span><div class="ticks">'
                    + "".join(f'<span class="tick" style="--p:{p:.4f}">{label}</span>' for p, label in tick_steps(span))
                    + "</div></div>")
    return f'<div class="lanes" role="group" aria-label="When each outlet reported, by side">{lanes}{axis}{tick_row}</div>'


def utc_stamp(dt):
    return dt.astimezone(timezone.utc).strftime("%H:%M UTC")


CHECK_GAP = 20 * 60  # seconds between builds; a lead smaller than this is not a lead we can claim


def facts_sentence(f, missing, utc=False):
    first = f["first"]
    u = f' <span class="utc">({utc_stamp(first["when"])})</span>' if utc else ""
    line = (f'<span class="f-first">First reported by <b>{e(first["source"])}</b> at {tm(first["when"])}{u}, '
            f'among the outlets we track, going by the time each outlet&rsquo;s feed gives.</span>')
    nxt = f.get("next")
    if nxt:
        gap = (nxt["when"] - first["when"]).total_seconds()
        if gap < CHECK_GAP:
            line += (f' <span class="f-close">Too close to call: <b>{e(nxt["source"])}</b> followed {fmt_dur(gap)} later, '
                     f'within the {CHECK_GAP // 60} minutes between our checks.</span>')
        else:
            line += f' <span class="f-next">Next: {e(nxt["source"])}, {fmt_dur(gap)} later.</span>'
    if f["all_sides_at"]:
        took = (f["all_sides_at"] - first["when"]).total_seconds()
        u2 = f' <span class="utc">({utc_stamp(f["all_sides_at"])})</span>' if utc else ""
        line += (f' <span class="f-all">All three sides had covered it by {tm(f["all_sides_at"])}{u2} '
                 f'({fmt_dur(took)} after the first report).</span>')
    elif missing:
        line += f' <span class="f-all">Not covered by {" or ".join(missing)} so far.</span>'
    return line


TOKEN = re.compile(r"\s+|[\w'\u2019-]+|[^\w\s]")


def _mark(tag, text):
    """Wrap changed text in <del>/<ins>, keeping the spaces around it outside the mark."""
    core = text.strip()
    if not core:
        return e(text)
    lead, trail = text[:len(text) - len(text.lstrip())], text[len(text.rstrip()):]
    return f"{e(lead)}<{tag}>{e(core)}</{tag}>{e(trail)}"


def diff_words(old, new):
    """Old and new headline with the changed words marked (<del> and <ins>). Punctuation is compared on its own,
    so adding a comma does not make the whole word look edited."""
    a, b = TOKEN.findall(old), TOKEN.findall(new)
    out_old, out_new = [], []
    for op, i1, i2, j1, j2 in difflib.SequenceMatcher(None, a, b, autojunk=False).get_opcodes():
        o, n = "".join(a[i1:i2]), "".join(b[j1:j2])
        if op == "equal":
            out_old.append(e(o)); out_new.append(e(n))
            continue
        if o:
            out_old.append(_mark("del", o))
        if n:
            out_new.append(_mark("ins", n))
    return "".join(out_old), "".join(out_new)


def story_members(rec):
    return [{"source": r["outlet"], "lean": r["side"], "type": r.get("type") or "", "title": r["headline"], "link": r["url"],
             "when": datetime.fromtimestamp(r["published"], timezone.utc), "versions": r["versions"]} for r in rec["reports"]]


def iso(dt):
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%d %H:%M")


def story_page(rec, asof, section_sides):
    """A story's own page: permalink, multi-day timeline, every report, headline edits, and a way to cite it."""
    members = story_members(rec)
    f = analytics.story_facts(members)
    label, kind, src = analytics.story_label(members)
    first, last = f["first"], f["last"]
    by = {l: {m["source"] for m in members if m["lean"] == l} for l in LEANS}
    counts = {l: len(v) for l, v in by.items()}
    outlets = len({m["source"] for m in members})
    missing = [l for l in ("left", "right") if outlets >= 3 and l in section_sides.get(rec["topic"], ()) and not counts[l]]
    bar = "".join(f'<span class="seg lean-{l}" data-lean="{l}" style="flex-grow:{counts[l]}"></span>' for l in LEANS if counts[l])
    gap = {l: f'<span class="seg-gap lean-{l}" aria-hidden="true"></span>' for l in missing}
    bar = gap.get("left", "") + bar + gap.get("right", "")
    legend = "".join(f'<span class="k lean-{l}" data-lean="{l}"><i></i>{LEAN_LABEL[l]} <b>{counts[l]}</b></span>' for l in LEANS)
    tracked = fmt_dur((last["when"] - first["when"]).total_seconds())
    reps = "".join(
        f'<li class="rep" data-lean="{m["lean"]}" data-source="a:{e(m["source"])}">'
        f'<div class="rep-meta">{tm(m["when"])}<span class="utc">({utc_stamp(m["when"])})</span>{pill(m["lean"])}<span>{e(m["source"])}</span>{type_badge(m)}'
        f'{"<span class=badge-edited>Headline changed</span>" if len(m["versions"]) > 1 else ""}</div>'
        f'<a class="hl" href="{e(m["link"])}" target="_blank" rel="noopener">{e(m["title"])}</a></li>' for m in f["ordered"])
    if not CLIPS_ON:
        clips = ""
    elif rec.get("posts"):
        rows = "".join(clip_card(dict(p, when=datetime.fromtimestamp(p["published"], timezone.utc)), base="../") for p in rec["posts"])
        clips = ('<h2>Clips and posts</h2><p class="muted-note">From the accounts we follow, newest first. Matched to this story by wording, so a '
                 'post can be paired loosely or missed. We have not checked them. <a href="../methods.html#social">How this works</a></p>'
                 f'<ul class="clips">{rows}</ul>')
    else:
        clips = ('<h2>Clips and posts</h2><p class="muted-note">No clips or posts from the accounts we follow have matched this story yet. '
                 'Matching is by wording and can miss one.</p>')
    edited = [m for m in f["ordered"] if len(m["versions"]) > 1]
    if edited:
        items = ""
        for m in edited:
            vs, rows = m["versions"], ""
            for k, v in enumerate(vs):
                before = diff_words(vs[k]["headline"], vs[k + 1]["headline"])[0] if k + 1 < len(vs) and k == 0 else None
                after = diff_words(vs[k - 1]["headline"], v["headline"])[1] if k > 0 else None
                text = after if after is not None else (before if before is not None else e(v["headline"]))
                seen = (f'seen from {tm(datetime.fromtimestamp(v["first_seen"], timezone.utc))}' if k else
                        f'first seen {tm(datetime.fromtimestamp(v["first_seen"], timezone.utc))}')
                rows += f'<li><span class="vt">{seen}</span><span>{text}</span></li>'
            items += (f'<li class="edit"><b>{e(m["source"])}</b> '
                      f'<a href="{e(m["link"])}" target="_blank" rel="noopener">open article</a><ol class="vers">{rows}</ol></li>')
        edits = (f'<h2>Headline changes</h2><p class="muted-note">Words removed are struck through and words added are underlined. '
                 f'We only see changes between our checks, about every 20 minutes. <a href="../methods.html#archive">How this works</a></p>'
                 f'<ul class="edits">{items}</ul>')
    else:
        edits = ('<h2>Headline changes</h2><p class="muted-note">No headline changes seen on this story so far. '
                 'We check about every 20 minutes, so a quick edit between checks would be missed.</p>')
    cite = (f'{SITE_NAME}, story {rec["id"]} (label: {label}). {len(members)} reports from {outlets} tracked outlets, '
            f'{iso(first["when"])} to {iso(last["when"])} UTC. Page last updated {iso(asof)} UTC (a report was added or a headline changed); '
            f'retrieved [retrieval time] UTC. '
            f'Page and outlet list: [where]')
    if SITE_URL:
        cite = cite.replace("[where]", f"{SITE_URL}story/{rec['id']}.html (outlets and side labels: {SITE_URL}sources.html)")
    body = f"""<div class="page story-page" data-id="{rec['id']}">
<p class="crumbs"><a href="../index.html">News</a> &middot; <a href="../archive.html">Archive</a> &middot; {e(TITLES.get(rec['topic'], rec['topic']))}</p>
<h1>{e(label)}</h1>{label_note(kind, src) or '<p class="lead-src">Label: the words most of these outlets&rsquo; headlines share. <a href="../methods.html#labels">How labels are made</a></p>'}
<p class="switch-note" id="switchNote" hidden>Some outlets or sides are switched off, so the counts and timing facts on this page follow what you have left on. <a href="../settings.html">Change in Settings</a></p>
<p class="meta"><span><b class="n-total">{outlets}</b> <span class="w">outlets</span></span><span>{len(members)} reports over {tracked}</span></p>
<div class="coverage"><div class="bar" role="img" aria-label="Outlets covering this story: left {counts['left']}, center {counts['center']}, right {counts['right']}">{bar}</div>
<p class="legend">{legend}</p></div>
<div class="facts"><p class="facts-line">{facts_sentence(f, missing, utc=True)}</p>
<h2>Coverage timeline</h2>
{lanes_html(f['ordered'], ticks=True)}
</div>
<h2>Every report</h2>
<p class="muted-note">Times are in your device&rsquo;s time zone (<span class="tz">your local time</span>), with UTC beside each.</p>
<ul class="reps">{reps}</ul>
{clips}
{edits}
<h2>Cite this</h2>
<p class="muted-note">A plain-text citation that says exactly what the numbers are based on. The citation uses UTC; times elsewhere on this page are in your device&rsquo;s time zone (<span class="tz">your local time</span>). <a href="../methods.html#cite">What to keep in mind</a></p>
<p class="cite-text" id="cite" tabindex="0">{e(cite)}</p>
<div class="row-actions-plain"><button class="btn primary" id="copyCite" type="button">Copy citation</button>
<a class="btn" href="{rec['id']}.json" download>Download this story's data (JSON)</a></div>
<p class="status-line" id="status" role="status" aria-live="polite"></p>
</div>"""
    return body, f, missing


def story_json(rec, asof, f, missing):
    iso_z = lambda dt: dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    stamp = lambda t: iso_z(datetime.fromtimestamp(t, timezone.utc))
    return {
        "schema": 1,
        "id": rec["id"],
        "label": analytics.story_label(story_members(rec))[0],
        "label_kind": analytics.story_label(story_members(rec))[1],
        "topic": rec["topic"],
        "last_updated": iso_z(asof),
        "first_reported": {"outlet": f["first"]["source"], "side": f["first"]["lean"], "at": iso_z(f["first"]["when"])},
        "first_by_side": {l: (iso_z(f["by_side"][l]["when"]) if f["by_side"][l] else None) for l in LEANS},
        "all_sides_at": iso_z(f["all_sides_at"]) if f["all_sides_at"] else None,
        "not_covered_by": missing,
        "clips_and_posts": [{"platform": p["platform"], "account": p["source"], "url": p["url"], "text": p["text"], "video": p["video"],
                             "published": stamp(p["published"]), "match_score": round(p["score"], 3)} for p in rec.get("posts", [])],
        "note": "Sides are one maintainer's judgment, not facts. 'First' means first among the tracked outlets, using feed publish times. The label is made of words the outlets' headlines share, not any one outlet's headline. last_updated is when a report was added or a headline changed. See methods.html.",
        "reports": [dict(outlet=m["source"], side=m["lean"], type=m.get("type") or "", headline=m["title"], url=m["link"],
                         published=iso_z(m["when"]),
                         **({"headline_versions": [dict(v, first_seen=stamp(v["first_seen"]), last_seen=stamp(v["last_seen"]))
                                                   for v in m["versions"]]} if len(m["versions"]) > 1 else {}))
                    for m in f["ordered"]],
    }


TRACKING = re.compile(r"^(utm_|fbclid|gclid|mc_|cmpid|smid|ocid|taid)", re.I)


def clean_link(url):
    """The article's address without tracking parameters, so the data file stays small and the links stay clean."""
    p = urllib.parse.urlsplit(url)
    if not p.query:
        return url
    keep = [kv for kv in urllib.parse.parse_qsl(p.query, keep_blank_values=True) if not TRACKING.match(kv[0])]
    return urllib.parse.urlunsplit(p._replace(query=urllib.parse.urlencode(keep)))


def headlines_json(rows, days):
    """Every headline of the last few days as compact arrays: [published, outlet, topic, title, link, story id or ""]."""
    sources, index, items = [], {}, []
    for url, source, lean, typ, topic, title, published, sid in rows:
        key = (source, lean, typ or "")
        if key not in index:
            index[key] = len(sources)
            sources.append(list(key))
        items.append([published, index[key], TOPIC_ORDER.index(topic) if topic in TOPIC_ORDER else 0, title, clean_link(url), sid or ""])
    return json.dumps({"days": days, "sources": sources, "topics": list(TOPIC_ORDER), "items": items}, separators=(",", ":"), ensure_ascii=False)


def latest_page(days, count):
    return f"""<div class="page" id="latest">
<h1>Latest</h1>
<p class="lede">Every headline from every outlet we read, newest first, including the ones only one outlet ran. The News page groups stories that several outlets covered; this page is everything, from the last {days} days. Your switches in Settings still apply.</p>
<form class="find" id="lform" role="search"><label for="lq">Search headlines and outlet names</label>
<input id="lq" name="q" type="search" autocomplete="off" placeholder="for example: mamdani, or &quot;ice raid&quot; for an exact phrase"><span class="hint">Whole words only (plurals count), so elon finds Elon but not felon. End a word with * to match its beginning (elon*).</span></form>
<div class="c-filter" id="ltopics" role="group" aria-label="Topic"><button type="button" aria-pressed="true" data-topic="">All</button><button type="button" aria-pressed="false" data-topic="0">United States</button><button type="button" aria-pressed="false" data-topic="1">World</button><button type="button" aria-pressed="false" data-topic="2">Technology</button></div>
<p class="status-line" id="lstatus" role="status" aria-live="polite">Loading {count:,} headlines&hellip;</p>
<ul class="lt-list" id="llist"></ul>
<button class="btn" id="lmore" type="button" hidden>Show more</button>
<noscript><p class="empty">This page needs JavaScript. The <a href="archive.html">archive</a> lists the stories without it.</p></noscript>
</div>
<script src="latest.js" defer></script>"""


def archive_page(rows, days):
    by_day = {}
    for sid, topic, lead, first_pub, last_seen, n, nl, nc, nr, first_src in rows[:600]:
        d = datetime.fromtimestamp(first_pub)
        by_day.setdefault(d.strftime("%A, %B %-d"), []).append(
            f'<li data-q="{e((lead + " " + (first_src or "")).lower())}"><a class="hl" href="story/{e(sid)}.html">{e(lead)}</a>'
            f'<div class="bar bar-sm" role="img" aria-label="Outlets covering this story: left {nl}, center {nc}, right {nr}">'
            + "".join(f'<span class="seg lean-{l}" style="flex-grow:{c}"></span>' for l, c in zip(LEANS, (nl, nc, nr)) if c) + '</div>'
            f'<span class="src"><span>{n} outlets</span><span>Left {nl} &middot; Center {nc} &middot; Right {nr}</span>'
            f'<span>First: {e(first_src or "")} at {tm(datetime.fromtimestamp(first_pub, timezone.utc))}</span></span></li>')
    groups = "".join(f'<section class="day"><h2>{e(day)}</h2><ul class="list stories-list">{"".join(items)}</ul></section>'
                     for day, items in by_day.items())
    return f"""<div class="page">
<h1>Archive</h1>
<p class="lede">Every story with two or more outlets that this site has seen in the last {days} days, newest first. Each has its own page with a permalink, a timeline across days and any headline changes. Day headings follow the time zone of the computer that builds the site.</p>
<div class="find"><label for="find">Filter by a word in a headline or an outlet name</label><input id="find" type="search" autocomplete="off"></div>
<p class="status-line" id="found" role="status" aria-live="polite">{len(rows)} stories</p>
{groups or '<p class="empty">Nothing archived yet. Stories appear here after the next build.</p>'}
</div>"""


_T0 = time.time()


def tick(label):
    """Print how long the build has been running, so a slow build shows which stage is slow (see logs/build.log)."""
    print(f"  [{time.time() - _T0:5.0f}s] {label}")


def main():
    cfg = tomllib.loads((ROOT / "config" / "sources.toml").read_text())
    global SITE_DIR, HIST, WORKBENCH, WB_REPORT, SITE_NAME, TAGLINE, GROUP_TAGLINE
    WORKBENCH = "--workbench" in sys.argv
    if WORKBENCH:  # your own copy: the defaults plus workbench/changes.toml, in its own folder with its own archive
        import workbench
        try:
            cfg, WB_REPORT = workbench.apply_changes(cfg, workbench.load_changes())
        except ValueError as ex:
            sys.exit(str(ex))
        SITE_DIR, HIST = workbench.WORK / "site", workbench.WORK / "history"
        SITE_NAME = f"{SITE_NAME} Workbench"
        for d in (workbench.WORK, SITE_DIR, HIST):
            d.mkdir(exist_ok=True)
        for r in WB_REPORT["skipped"]:
            print(f"  workbench: skipped {r}", file=sys.stderr)
    elif "--group" in sys.argv:  # one community's own copy: see groups.py
        import groups
        try:
            g = groups.load(sys.argv[sys.argv.index("--group") + 1])
            cfg, rep = groups.apply(cfg, g)
        except (ValueError, IndexError) as ex:
            sys.exit(str(ex) or "Usage: build.py --group <name>")
        if not cfg["feeds"]:
            sys.exit(f"The group '{g['slug']}' follows no outlets yet. Add some: .venv/bin/python groups.py add {g['slug']} <website>")
        gdir = groups.group_dir(g["slug"])
        SITE_DIR, HIST = gdir / "site", gdir / "history"
        SITE_NAME = g["name"]
        if str(g.get("tagline", "")).strip():
            TAGLINE = GROUP_TAGLINE = " ".join(str(g["tagline"]).split())[:160]
        for d in (SITE_DIR, HIST):
            d.mkdir(parents=True, exist_ok=True)
        for r in rep["skipped"]:
            print(f"  group: skipped {r}", file=sys.stderr)
    else:
        SITE_DIR, HIST = ROOT / "site", ROOT / "history"
    s = cfg["settings"]
    global SITE_URL, CLIPS_ON, TABS, REPO_URL, LICENSE_NAME, FEEDS_ON
    CLIPS_ON = bool(s.get("clips", False))
    TABS = [t for t in TABS_ALL if CLIPS_ON or t[0] != "posts"]
    SITE_URL = (s.get("base_url") or "").strip()
    FEEDS_ON = bool(SITE_URL)
    REPO_URL, LICENSE_NAME = (s.get("repo_url") or "").strip().rstrip("/"), (s.get("license") or "").strip()
    SITE_URL = SITE_URL + ("/" if SITE_URL and not SITE_URL.endswith("/") else "")
    load_feed_state()
    cutoff = datetime.now(timezone.utc) - timedelta(hours=s["hours_back"])
    global OPEN_WITH
    OPEN_WITH = cfg.get("open_with", {})

    print("Fetching feeds...")
    with ThreadPoolExecutor(8) as pool:
        feed_results = list(pool.map(lambda f: fetch_feed(f, cutoff, s["max_per_feed"]), cfg["feeds"]))
    save_feed_state()
    print(f"  feeds: {_feed_stats['unchanged']} unchanged (304), {_feed_stats['fresh']} downloaded")
    for ch in cfg["channels"]:  # one at a time: they share a cache file
        try:
            ch["id"] = channel_id(ch["handle"])
        except Exception as ex:
            ch["_err"] = str(ex)
            print(f"  skipped video channel {ch['name']}: {ex}", file=sys.stderr)
    channels = [c for c in cfg["channels"] if "id" in c]
    with ThreadPoolExecutor(8) as pool:
        video_results = list(pool.map(lambda c: fetch_channel(c, cutoff), channels))
    for ch, res in zip(channels, video_results):
        ch["_n"] = len(res)
    articles = [i for r in feed_results for i in r]
    tick("feeds and channels fetched")
    min_articles = s.get("min_articles", 50)
    if len(articles) < min_articles:
        sys.exit(f"Only {len(articles)} articles were fetched (expected at least {min_articles}). "
                 "Keeping the last good site; check the network connection.")
    buzz = fetch_buzz()
    tick("popularity signals fetched")
    for a in articles:
        a["buzz"] = buzz.get(norm_url(a["link"]), NO_BUZZ)
    print(f"  buzz signals matched on {sum(1 for a in articles if a['buzz'] is not NO_BUZZ)} articles")
    videos = pick_videos([v for r in video_results for v in r], s["max_videos"])
    print(f"  {len(articles)} articles, {len(videos)} videos selected")
    video_posters = set()
    if s.get("clip_thumbnails", True):  # copy each thumbnail here, so a reader's browser never asks YouTube for it
        for v in videos:
            try:
                v["poster_local"] = cache_poster(f"https://i.ytimg.com/vi/{v['vid']}/hqdefault.jpg", SITE_DIR)
            except Exception as ex:
                print(f"  thumbnail skipped for {v['source']}: {ex}", file=sys.stderr)
            if v.get("poster_local"):
                video_posters.add(v["poster_local"])

    built_topics, archive_topics, raw, tech_singles = {}, {}, {}, {}
    for topic in ("us", "world", "tech"):
        singles = []
        clusters = build_stories([a for a in articles if a["topic"] == topic],
                                 s["cluster_threshold"], singles if topic in s.get("singles_topics", ["us", "world", "tech"]) else None)
        raw[topic], tech_singles[topic] = clusters, singles
    before = sum(len(v) for v in raw.values())
    tick("stories grouped")
    merged = merge_related(raw, articles, s.get("merge_threshold", 0.78))
    tick("duplicate stories merged")
    print(f"  merged {before - sum(len(v) for v in merged.values())} duplicate stories (from {before})")
    for topic in ("us", "world", "tech"):
        clusters = merged[topic]
        archive_topics[topic] = (clusters, [])  # every multi-outlet story gets remembered and a page
        built_topics[topic] = (clusters[:15], tech_singles[topic])
        print(f"  {topic}: {len(clusters)} multi-outlet stories, {min(len(clusters), 15)} shown")

    all_stories = [st for stories, _ in built_topics.values() for st in analytics.annotate(stories)]
    for topic_, (stories_, _) in built_topics.items():
        for st in stories_:
            st["topic"] = topic_
    brk_stories = mark_breaking(all_stories, datetime.now(timezone.utc), s)  # decided first: they get their summaries first
    blind_stories = mark_blindspots(all_stories, cfg, datetime.now(timezone.utc), s, skip={id(st) for st in brk_stories})
    if blind_stories:
        print(f"  blindspots: {len(blind_stories)} ({', '.join(st['label'][:30] + ' [' + st['blindspot']['side'] + ']' for st in blind_stories)})")
    ALL_SUMS = "--all-summaries" in sys.argv
    built = int(time.time())
    try:  # the archive is additive: if it fails, the site still publishes
        done = archive.record_build(HIST / "archive.sqlite", built, articles, archive_topics, s.get("archive_days", 365))
        print(f"  archive: {done['new_articles']} new headlines, {done['edits']} headline edits, {done['new_stories']} new stories")
    except Exception as ex:
        print(f"  archive skipped: {ex}", file=sys.stderr)
    if "--summaries-only" in sys.argv:
        # the summary job (./schedule.sh summaries-install): the stories are grouped and numbered, so write the summaries that are
        # missing and stop. No pages are written and nothing is published; the next ordinary build shows what this run saved.
        summaries.attach(all_stories, s, HIST)
        tick("summaries written")
        return

    followed = cfg.get("social", []) if CLIPS_ON else []
    posts, post_matches = [], []
    if followed:
        now_utc = datetime.now(timezone.utc)

        def pull(src):
            try:
                got = social.fetch(src, get, now_utc, cutoff)
                src["_n"] = len(got)
                return got
            except Exception as ex:
                src["_err"] = str(ex)[:90]
                print(f"  skipped social account {src.get('name')}: {ex}", file=sys.stderr)
                return []

        with ThreadPoolExecutor(4) as pool:
            posts = sorted([p for r in pool.map(pull, followed) for p in r], key=lambda p: p["when"], reverse=True)
        flat = [st for stories_, _ in archive_topics.values() for st in stories_]
        post_matches = social.match_posts(posts, flat, s.get("post_match", 0.2))
        if s.get("clip_thumbnails", True):
            attach_posters(posts, SITE_DIR)
        try:
            got = archive.record_posts(HIST / "archive.sqlite", built, posts, post_matches, s.get("archive_days", 365))
            print(f"  clips and posts: {got['posts']} from {len(followed)} accounts, {got['matched']} matched to stories")
        except Exception as ex:
            print(f"  clips and posts not archived: {ex}", file=sys.stderr)

    tick("archive and clips")
    # first pass uses only summaries already written, so the page can go out at once; new ones are written after publishing.
    # It runs after the archive has numbered the stories, so a story keeps its previous summary under its own id while a new one is written.
    summaries.attach(all_stories, s, HIST, per_build=10**6 if ALL_SUMS else 0, budget_s=10**6 if ALL_SUMS else 0)
    tick("cached summaries attached")
    matches = match_trends([st for stories, _ in built_topics.values() for st in stories],
                           fetch_bluesky_trends(), s.get("trend_match", 0.3))
    print(f"  Bluesky trends matched to {len(matches)} stories")
    if "--debug-trends" in sys.argv:
        for st, t, sim in sorted(matches, key=lambda x: -x[2]):
            print(f"    {sim:.2f}  {t['name']!r}  <->  {st['members'][0]['title'][:70]!r}")

    brk_ids = {id(st) for st in brk_stories}
    if brk_stories:
        print(f"  breaking: {len(brk_stories)} ({', '.join(st['label'][:30] for st in brk_stories)})")
    if brk_stories:
        TABS = [("breaking", "Breaking")] + TABS
    if blind_stories:
        at = [k for k, _ in TABS].index("us")  # after Breaking and Clips, before the topic sections
        TABS = TABS[:at] + [("blindspots", "Blindspots")] + TABS[at:]

    def render_sections():
        """The Breaking block and the topic sections; called again if summaries arrive after the first publish."""
        sections, breaking_html = "", ""
        if brk_stories:
            breaking_html = (f'<section data-section id="breaking"><h2 class="sec">Breaking</h2>'
                         f'<p class="sec-note">First reported in the last {s.get("breaking_max_age_h", 4)} hours and still being reported by several outlets, '
                         f'as of {tm(datetime.now())}. <a href="methods.html#breaking">How this is decided</a></p>'
                         f'<div class="stories">{"".join(render_story(st) for st in brk_stories)}</div>'
                         f'<p class="none-left" hidden>Everything here is hidden by your settings.</p></section>')
        for topic, (stories, singles) in built_topics.items():
            body = "".join(render_story(st) for st in stories if id(st) not in brk_ids)
            body = f'<div class="stories">{body}</div>' if body else ""
            if singles:
                singles.sort(key=lambda i: i["when"], reverse=True)
                body += render_singles(singles[:15], topic)
            body = body or '<p class="empty">Nothing matched in this update.</p>'
            sections += (f'<section data-section id="{topic}"><h2 class="sec">{TITLES[topic]}</h2>{body}'
                         f'<p class="none-left" hidden>Everything here is hidden by your settings.</p></section>')
        if blind_stories:
            sections = render_blindspots(blind_stories, s["hours_back"]) + sections  # first of the topic sections
        return sections, breaking_html

    summary = analytics.day_summary(all_stories, articles)
    stats = analytics.outlet_stats(all_stories)
    updated = datetime.now().strftime("%b %d, %-I:%M %p")
    site = SITE_DIR
    site.mkdir(exist_ok=True)
    latest_days = s.get("latest_days", 3)
    head_rows = []
    try:  # everything the archive has seen recently, for the Latest page and its search
        hconn = archive.open_archive(HIST / "archive.sqlite")
        head_rows = archive.headlines_since(hconn, built - latest_days * 86400)
        hconn.close()
    except Exception as ex:
        print(f"  latest headlines not built: {ex}", file=sys.stderr)
    vids_new = sorted(videos, key=lambda v: v["when"], reverse=True)  # newest first: freshness leads
    def index_content(updated):
        sections, breaking_html = render_sections()
        return news_page(
            sections, "".join(render_video(v) for v in vids_new) or '<p class="empty">No videos loaded.</p>',
            updated, {"clips": min(len(posts), 40), "videos": len(videos), "stories": sum(len(st) for st, _ in built_topics.values()), "headlines": len(head_rows),
                      "sources": len(cfg["feeds"]) + len(cfg["channels"]) + len(cfg.get("social", []))}, summary,
            stat_panels(all_stories, articles, s["hours_back"]), s["hours_back"],
            posts_section(posts, {p["url"]: st for p, st, _ in post_matches}, followed) if CLIPS_ON else "", breaking_html, "".join(render_video_row(v) for v in vids_new))

    pages = {
        "index.html": (SITE_NAME, "news", index_content(updated)),
        "latest.html": (f"Latest · {SITE_NAME}", "latest", latest_page(latest_days, len(head_rows))),
        "sources.html": (f"Sources · {SITE_NAME}", "sources", sources_page(cfg, s["hours_back"], updated, stats, len(all_stories))),
        "methods.html": (f"How the numbers are made · {SITE_NAME}", "methods", fill_repo((ROOT / "template" / "methods.html").read_text())),
        "settings.html": (f"Settings · {SITE_NAME}", "settings", (ROOT / "template" / "settings.html").read_text()),
        "fork.html": (f"Run your own · {SITE_NAME}", "fork", fill_repo((ROOT / "template" / "fork.html").read_text())),
    }
    if WORKBENCH:
        pages["manage.html"] = (f"Manage sources · {SITE_NAME}", "manage", (ROOT / "template" / "manage.html").read_text())
        pages["manage-readonly.html"] = (f"Manage sources · {SITE_NAME}", "manage",
            '<div class="page"><h1>Manage sources</h1><p class="lead">Adding, removing and relabeling sources is done on the Mac that runs the workbench. '
            'This phone view is read-only, so nothing can be changed from here.</p><p class="muted-note">On the Mac, open the workbench and choose Manage.</p></div>')
    (site / "data").mkdir(exist_ok=True)
    health_path = site / "data" / "health.json"
    try:
        previous = json.loads(health_path.read_text()).get("sources", {}) if health_path.exists() else {}
    except (ValueError, OSError):
        previous = {}
    write_atomic(site / "data" / "headlines.json", headlines_json(head_rows, latest_days))
    write_atomic(health_path, json.dumps({"built": built, "sources": source_health(cfg, built, previous)}, separators=(",", ":")))
    for asset in ("style.css", "app.js", "clips.js", "latest.js"):
        write_atomic(site / asset, (ROOT / "template" / asset).read_text())
    shutil.copytree(ROOT / "template" / "vendor", site / "vendor", dirs_exist_ok=True)
    for name, (title, key, content) in pages.items():
        write_atomic(site / name, page(title, key, content, built))

    def write_feeds():
        """Atom feeds of the stories and an OPML file of the sources: the open formats other tools and copies can follow."""
        write_atomic(site / "sources.opml", federation.opml(SITE_NAME, cfg))
        if not FEEDS_ON:
            return
        base = SITE_URL if SITE_URL.endswith("/") else SITE_URL + "/"
        now_utc = datetime.now(timezone.utc)
        shown = [st for stories_, _ in built_topics.values() for st in stories_]
        for fn, label, sub, sts in (("feed.xml", "", "Stories grouped by how many different outlets covered them", shown),
                                    ("breaking.xml", " \u00b7 Breaking", "Stories unfolding now, by the stated rule", brk_stories),
                                    ("blindspots.xml", " \u00b7 Blindspots", "Stories only one side has covered so far", blind_stories)):
            write_atomic(site / fn, federation.atom(SITE_NAME + label, sub, base, fn, sts, now_utc))

    write_feeds()
    stories = sum(len(st) for st, _ in built_topics.values())
    archive_path = HIST / "archive.sqlite"
    try:  # story pages and the archive page are additive: a problem here never stops the main site
        story_dir = site / "story"
        story_dir.mkdir(exist_ok=True)
        sides = {t: {f["lean"] for f in cfg["feeds"] if f.get("topic", "us") == t} for t in ("us", "world", "tech")}
        days = s.get("archive_page_days", 14)
        conn = archive.open_archive(archive_path)
        ids = {st["sid"] for stories_, _ in archive_topics.values() for st in stories_ if st.get("sid")}
        ids |= set(archive.story_ids_since(conn, built - 30 * 86400))  # unchanged pages are left alone by write_if_changed
        written = 0
        for sid in ids:
            rec = archive.story_record(conn, sid)
            if not rec or not rec["reports"]:
                continue
            asof = datetime.fromtimestamp(rec["changed_at"], timezone.utc)
            body, f, missing = story_page(rec, asof, sides)
            written += write_if_changed(story_dir / f"{sid}.html",
                                        page(f"{analytics.story_label(story_members(rec))[0]} · {SITE_NAME}", "story", body, rec["changed_at"], base="../"))
            written += write_if_changed(story_dir / f"{sid}.json",
                                        json.dumps(story_json(rec, asof, f, missing), separators=(",", ":")))
        write_atomic(site / "archive.html", page(f"Archive · {SITE_NAME}", "archive",
                                                 archive_page(archive.story_listing(conn, built - days * 86400), days), built))
        valid = archive.all_story_ids(conn)
        conn.close()
        for p in story_dir.iterdir():  # drop pages for stories the archive has let go of
            if p.suffix in (".html", ".json") and p.stem not in valid:
                p.unlink()
        print(f"  story pages: {len(ids)} checked, {written} files written")
    except Exception as ex:
        print(f"  story pages skipped: {ex}", file=sys.stderr)
    try:  # forget preview frames no recent clip uses
        keep = archive.recent_posters(archive_path, built - 14 * 86400) | video_posters
        for f in (site / "clips").glob("*"):
            if f.suffix != ".tmp" and f"clips/{f.name}" not in keep:
                f.unlink()
    except Exception as ex:
        print(f"  preview-frame cleanup skipped: {ex}", file=sys.stderr)
    try:
        edits = archive.edited_headlines(HIST / "archive.sqlite", [m["link"] for st in all_stories for m in st["members"]])
    except Exception as ex:
        edits = {}
        print(f"  headline versions skipped: {ex}", file=sys.stderr)
    try:
        recent = archive.recent_edits(HIST / "archive.sqlite", built - 7 * 86400)
    except Exception as ex:
        recent = []
        print(f"  headline edits skipped: {ex}", file=sys.stderr)
    matched_sid = {p["url"]: (st.get("sid"), score) for p, st, score in post_matches}
    clips_json = [{"platform": p["platform"], "account": p["source"], "handle": p["handle"], "url": p["url"], "text": p["text"],
                   "published": p["when"].astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"), "video": p["video"],
                   "matched_story": matched_sid.get(p["url"], (None, None))[0],
                   "match_score": round(matched_sid[p["url"]][1], 3) if p["url"] in matched_sid else None} for p in posts]
    (site / "data").mkdir(exist_ok=True)
    write_atomic(site / "data" / "latest.json",
                 json.dumps(analytics.snapshot(built, built_topics, summary, stats, cfg, s["hours_back"], edits, recent, clips_json), separators=(",", ":")))
    analytics.record_history(HIST / "snapshots.jsonl", built, built_topics, articles)
    # written last: its presence says the build finished, and open pages poll it to learn there is news
    write_atomic(site / "build.json", json.dumps({"built": built, "articles": len(articles), "stories": stories}))
    tick("all pages written")
    print("Wrote site/ (index, sources, settings, fork)")
    if not ALL_SUMS and s.get("summaries", False) and s.get("summaries_in_build", True):
        # the page is already live; now write the summaries it is missing (breaking first) and refresh the front page if any arrive
        if summaries.attach(all_stories, s, HIST):
            built2 = int(time.time())
            write_atomic(site / "index.html", page(SITE_NAME, "news", index_content(datetime.now().strftime("%b %d, %-I:%M %p")), built2))
            write_atomic(site / "build.json", json.dumps({"built": built2, "articles": len(articles), "stories": stories}))
            write_feeds()
            tick("front page refreshed with new summaries")
    if "--group" not in sys.argv:  # a group's pages are its own; only the main site is published, and only when publish.local.toml exists
        report = publish.run(site)
        if report:
            print(f"  {report}")


if __name__ == "__main__":
    main()
