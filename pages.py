"""Page watchers: follow a web page that has no feed (a city council's news page, a union's announcements, a court docket
list) by noticing links that appear on it.

A page watcher is a normal entry in the outlet list with `method = "page"`:

    [[feeds]]
    name = "Example City Council"
    url = "https://example.gov/council/news"
    method = "page"
    link_contains = "/council/news/"   # optional: only links whose address contains this
    min_words = 4                      # optional: ignore links with fewer words (menus, "Read more")
    lean = "center"
    topic = "us"

How it works, in plain terms: each time it looks, it lists the links on the page whose text reads like a headline, and
remembers when it first saw each one. The first time it looks at a page it only remembers what is already there (so an
old page does not flood the news with old items); after that, each link that newly appears is a new item, dated by when
it was first seen, because pages rarely say when they were posted. That date can be later than the real posting time.

It is careful with other people's servers: it asks robots.txt first and respects a "no", looks at a given page at most
once every `min_interval_min` minutes (default 30) no matter how often the site is rebuilt, reads a limited amount, and
introduces itself. It reads public pages only, with no login, and keeps just the headline text, the link and the time.
"""
import json
import re
import urllib.parse
import urllib.request
import urllib.robotparser
from datetime import datetime, timedelta, timezone
from html.parser import HTMLParser
from pathlib import Path

ROOT = Path(__file__).resolve().parent
STATE = ROOT / "cache" / "pages.json"
UA = "TallyNewsPageWatcher/1.0 (+reads public pages; honors robots.txt)"
MAX_BYTES = 1_500_000
KEEP_ITEMS = 80
SKIP_SCHEMES = ("mailto:", "javascript:", "tel:", "#")
BOILERPLATE = re.compile(r"^(go to|read more|learn more|click here|view all|see all|show more|load more|subscribe|sign up|share|donate|log ?in)\b|[>»›]\s*$", re.I)


class _Links(HTMLParser):
    """Every <a href> with its visible text. Ignores scripts, styles, and navigation, header and footer blocks."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.links, self._href, self._buf, self._skip, self._chrome = [], None, [], 0, 0

    def handle_starttag(self, tag, attrs):
        if tag in ("script", "style", "noscript", "template"):
            self._skip += 1
        elif tag in ("nav", "header", "footer", "aside"):
            self._chrome += 1
        elif tag == "a" and not self._skip:
            self._href = dict(attrs).get("href")
            self._buf = []
            self._in_chrome = self._chrome > 0

    def handle_endtag(self, tag):
        if tag in ("script", "style", "noscript", "template"):
            self._skip = max(0, self._skip - 1)
        elif tag in ("nav", "header", "footer", "aside"):
            self._chrome = max(0, self._chrome - 1)
        elif tag == "a" and self._href is not None:
            text = " ".join("".join(self._buf).split())
            self.links.append((self._href, text, getattr(self, "_in_chrome", False)))
            self._href = None

    def handle_data(self, data):
        if self._href is not None and not self._skip:
            self._buf.append(data)


def extract(html_text, base_url, link_contains="", min_words=4, exclude=()):
    """Headline-like links on a page: [(title, absolute url)], in page order, no repeats."""
    p = _Links()
    p.feed(html_text)
    host = urllib.parse.urlsplit(base_url).hostname
    seen, out = set(), []
    for href, text, in_chrome in p.links:
        if not href or href.startswith(SKIP_SCHEMES) or in_chrome:
            continue
        url = urllib.parse.urldefrag(urllib.parse.urljoin(base_url, href.strip()))[0]
        if urllib.parse.urlsplit(url).scheme not in ("http", "https"):
            continue
        if link_contains and link_contains not in url:
            continue
        if any(x and x in url for x in exclude):
            continue
        if not link_contains and urllib.parse.urlsplit(url).hostname != host:
            continue  # without a filter, stay on the same site (no ads or outside links)
        if BOILERPLATE.search(text) or len(text.split()) < min_words or len(text) > 220 or url in seen or url.rstrip("/") == base_url.rstrip("/"):
            continue
        seen.add(url)
        out.append((text, url))
    return out


def _load():
    try:
        return json.loads(STATE.read_text())
    except Exception:
        return {}


def _save(state):
    STATE.parent.mkdir(exist_ok=True)
    tmp = STATE.with_suffix(".tmp")
    tmp.write_text(json.dumps(state))
    tmp.replace(STATE)


def _robots_allows(url, state, now):
    p = urllib.parse.urlsplit(url)
    key = f"robots:{p.scheme}://{p.netloc}"
    ent = state.get(key)
    if not ent or now - ent["at"] > 86400:
        rp = urllib.robotparser.RobotFileParser()
        try:
            req = urllib.request.Request(f"{p.scheme}://{p.netloc}/robots.txt", headers={"User-Agent": UA})
            with urllib.request.urlopen(req, timeout=10) as r:
                lines = r.read(200_000).decode("utf-8", "ignore").splitlines()
            rp.parse(lines)
            ent = {"at": now, "lines": lines}
        except Exception:
            ent = {"at": now, "lines": []}  # no robots.txt (or unreachable): nothing forbids it
        state[key] = ent
    rp = urllib.robotparser.RobotFileParser()
    rp.parse(ent["lines"])
    return rp.can_fetch(UA, url)


def _read(url):
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "text/html,application/xhtml+xml"})
    with urllib.request.urlopen(req, timeout=15) as r:
        return r.read(MAX_BYTES).decode(r.headers.get_content_charset() or "utf-8", "ignore")


def fetch_page(feed, cutoff, cap, now=None):
    """Items for one page watcher, in the same shape as feed items. Sets feed["_n"], and feed["_note"] or feed["_err"]."""
    now = now or datetime.now(timezone.utc)
    ts = now.timestamp()
    state = _load()
    url = feed["url"]
    ent = state.get(url) or {"items": [], "fetched": 0, "baselined": False}
    interval = float(feed.get("min_interval_min", 30)) * 60
    if ts - ent["fetched"] >= interval:
        try:
            if not _robots_allows(url, state, ts):
                feed["_err"] = "the site's robots.txt asks automated readers not to look at this page"
                _save(state)
                return []
            found = extract(_read(url), url, feed.get("link_contains", ""), int(feed.get("min_words", 4)),
                            feed.get("exclude", []) if isinstance(feed.get("exclude", []), list) else [feed["exclude"]])
        except Exception as ex:
            feed["_err"] = str(ex)[:120]
            return _items(feed, ent, cutoff, cap)  # keep showing what was already seen
        old = {i["link"]: i for i in ent["items"]}
        first_look = not ent["baselined"]
        fresh = []
        for title, link in found:
            if link in old:
                old[link]["title"] = title
                continue
            # the first look only records what is already on the page, dated far enough back that it is not news
            fresh.append({"link": link, "title": title, "t": ts - 10 * 365 * 86400 if first_look else ts})
        ent["items"] = (fresh + list(old.values()))[:KEEP_ITEMS] if not first_look else fresh[:KEEP_ITEMS]
        ent["fetched"], ent["baselined"] = ts, True
        ent["found"] = len(found)
        state[url] = ent
        _save(state)
        if first_look:
            feed["_note"] = (f"Watching: found {len(found)} headline-like links. They are remembered as already there; "
                             f"each new link that appears from now on shows up as a new item.")
    return _items(feed, ent, cutoff, cap)


def _items(feed, ent, cutoff, cap):
    out = []
    for i in ent["items"]:
        when = datetime.fromtimestamp(i["t"], timezone.utc)
        if when < cutoff:
            continue
        out.append({"title": i["title"], "link": i["link"], "text": "", "when": when, "source": feed["name"],
                    "lean": feed["lean"], "type": feed.get("type", ""), "topic": feed.get("topic", "us")})
    out.sort(key=lambda x: x["when"], reverse=True)
    feed["_total"] = ent.get("found", len(ent["items"]))
    feed["_n"] = len(out[:cap])
    if not feed.get("_note") and not out and ent.get("baselined"):
        feed["_note"] = f"Watching ({feed['_total']} links seen). Nothing new has appeared in this window."
    return out[:cap]
