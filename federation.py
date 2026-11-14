"""Open formats in and out, so instances and people can follow each other without a new protocol.

In: turn a Mastodon or Bluesky address into the ordinary feed that service already publishes
    (@name@instance, https://instance/@name, #tag@instance, bsky.app/profile/handle).
Out: Atom feeds of the stories (all, Breaking, Blindspots) and an OPML file of the sources. Any feed reader, or another
    copy of this project, can follow them: add the address as a source like any other.

Standard library only. Atom needs absolute addresses, so feeds are written only when settings.base_url is set.
"""
import re
import urllib.parse
from datetime import timezone
from xml.sax.saxutils import escape, quoteattr

HANDLE = re.compile(r"^@([\w.-]{1,60})@([A-Za-z0-9.-]+\.[A-Za-z]{2,})$")
TAG = re.compile(r"^#([\w]{1,60})@([A-Za-z0-9.-]+\.[A-Za-z]{2,})$")


def feed_for(text):
    """The feed address for a pasted fediverse or Bluesky address, or None when it is neither."""
    t = (text or "").strip()
    m = HANDLE.match(t)
    if m:
        return f"https://{m.group(2)}/@{m.group(1)}.rss"
    m = TAG.match(t)
    if m:
        return f"https://{m.group(2)}/tags/{m.group(1)}.rss"
    p = urllib.parse.urlsplit(t if "//" in t else "https://" + t)
    host, path = (p.hostname or "").lower(), p.path.rstrip("/")
    if host in ("bsky.app", "www.bsky.app"):
        m = re.match(r"^/profile/([\w:.%-]+)(?:/rss)?$", path)
        if m:
            return f"https://bsky.app/profile/{m.group(1)}/rss"
    if re.fullmatch(r"/@[\w.-]+", path) and "." in host and host not in ("youtube.com", "www.youtube.com", "medium.com"):
        return f"https://{host}{path}.rss"  # a Mastodon-style profile address
    m = re.fullmatch(r"/tags/([\w]+)", path)
    if m and "." in host:
        return f"https://{host}/tags/{m.group(1)}.rss"
    return None


def is_social_feed(url):
    """Mastodon and Bluesky feeds carry posts, not headlines: their items have no title of their own."""
    p = urllib.parse.urlsplit(url or "")
    path = p.path
    return (p.hostname or "") == "bsky.app" and path.endswith("/rss") or bool(
        re.fullmatch(r"/@[\w.-]+\.rss", path) or re.fullmatch(r"/tags/\w+\.rss", path))


def title_from_post(text, limit=140):
    """A post's first words as a headline: whole words, one line, an ellipsis if cut."""
    t = " ".join((text or "").split())
    if len(t) <= limit:
        return t
    cut = t[:limit].rsplit(" ", 1)[0].rstrip(".,;:!?-")
    return cut + "…"


# ---- Atom out ---------------------------------------------------------------

def _iso(dt):
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _entry(st, base):
    members = sorted(st["members"], key=lambda m: m["when"])
    counts = {l: sum(1 for m in members if m["lean"] == l) for l in ("left", "center", "right")}
    sid = st.get("sid", "")
    url = f"{base}story/{sid}.html"
    first = members[0]
    line = (f"{len(members)} outlets: {counts['left']} left, {counts['center']} center, {counts['right']} right. "
            f"First reported by {first['source']} ({first['lean']}) among the outlets tracked here. "
            "Sides are one maintainer's labels, not facts.")
    sm = st.get("summary")
    body = (f"Machine-written from the outlets' own excerpts, and it can be wrong: {sm['text']}\n\n{line}" if sm else line)
    cats = [st.get("topic", "us")] + (["breaking"] if st.get("breaking") else []) + (["blindspot"] if st.get("blindspot") else [])
    out = [f"<entry><id>{escape(url)}</id><title>{escape(st['label'])}</title>",
           f'<link rel="alternate" type="text/html" href={quoteattr(url)}/>',
           f"<published>{_iso(first['when'])}</published><updated>{_iso(st['newest'])}</updated>",
           f'<summary type="text">{escape(line)}</summary>', f'<content type="text">{escape(body)}</content>']
    out += [f"<category term={quoteattr(c)}/>" for c in cats]
    out += [f'<link rel="related" type="text/html" href={quoteattr(m["link"])} title={quoteattr(m["source"] + " (" + m["lean"] + ")")}/>'
            for m in members[:20]]
    return "".join(out) + "</entry>"


def atom(site_name, subtitle, base, filename, stories, now):
    """An Atom feed of stories, newest first. `base` is the site address, ending in a slash."""
    stories = sorted(stories, key=lambda s: s["newest"], reverse=True)
    head = (f'<?xml version="1.0" encoding="utf-8"?>\n<feed xmlns="http://www.w3.org/2005/Atom">'
            f"<id>{escape(base + filename)}</id><title>{escape(site_name)}</title><subtitle>{escape(subtitle)}</subtitle>"
            f'<link rel="self" type="application/atom+xml" href={quoteattr(base + filename)}/>'
            f'<link rel="alternate" type="text/html" href={quoteattr(base)}/>'
            f"<updated>{_iso(now)}</updated>"
            f"<rights>Headlines and links belong to their publishers. Counts, labels and summaries are this site's own and can be wrong.</rights>")
    return head + "".join(_entry(s, base) for s in stories if s.get("sid")) + "</feed>\n"


# ---- OPML out ---------------------------------------------------------------

def opml(site_name, cfg):
    """The sources as OPML, grouped by topic. `tally:side` carries the left, center or right label (one maintainer's)."""
    topics = {}
    for f in cfg["feeds"]:
        topics.setdefault(f.get("topic", "us"), []).append(f)
    body = ""
    for topic, feeds in topics.items():
        rows = ""
        for f in feeds:
            kind = "link" if f.get("method") == "page" else "rss"
            addr = "url" if kind == "link" else "xmlUrl"  # a watched page is a link, not a feed
            attrs = f'text={quoteattr(f["name"])} type={quoteattr(kind)} {addr}={quoteattr(f["url"])} tally:side={quoteattr(f["lean"])}'
            if f.get("type"):
                attrs += f' tally:type={quoteattr(f["type"])}'
            rows += f"<outline {attrs}/>"
        body += f"<outline text={quoteattr(topic)}>{rows}</outline>"
    return ('<?xml version="1.0" encoding="utf-8"?>\n<opml version="2.0" xmlns:tally="https://github.com/h-nt3r/tally-news">'
            f"<head><title>{escape(site_name)} sources</title></head><body>{body}</body></opml>\n")
