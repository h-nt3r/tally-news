"""Reader-facing news analytics: counts and timings worked out from data the build already has.

No scores and no judgments. Every number here is something a person could recount by hand, and each one is
described on the Methods page (template/methods.html). Nothing here looks at who is reading.
"""
import hashlib
import json
import math
import os
import re
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

from sklearn.feature_extraction.text import ENGLISH_STOP_WORDS

LEANS = ("left", "center", "right")
# words that carry no information about how a side frames a story
STOP = set(ENGLISH_STOP_WORDS) | {
    "says", "said", "say", "new", "news", "report", "reports", "reportedly", "video", "live", "updates", "update",
    "watch", "amid", "could", "would", "will", "just", "like", "get", "gets", "how", "why", "what", "who", "here",
    "now", "year", "years", "day", "today", "week", "first", "two", "three", "one", "may", "might", "after", "over",
}
WORD = re.compile(r"[a-z][a-z'-]{2,}")


def words(title):
    """The meaningful lowercase words in a headline, each counted once."""
    out = set()
    for w in WORD.findall(title.lower().replace("’", "'")):
        w = w.removesuffix("'s").strip("'-")
        if len(w) >= 3 and w not in STOP:
            out.add(w)
    return out


TOKEN = re.compile(r"[A-Za-z0-9][A-Za-z0-9'\u2019.\-]*")


def _key(tok):
    t = tok.lower().replace("\u2019", "'")
    return t.removesuffix("'s").strip("'.-")


def story_label(members, max_words=7):
    """A neutral label for a story, so no single outlet's headline stands in for all of them.

    It is made of the words that a third or more of the story's outlets' headlines have in common (at least two
    outlets), kept in the order they appear in the headline that contains the most of them. When fewer than two words
    are shared it falls back to the earliest report's headline and says whose it is.
    Returns (label, kind, source) where kind is "shared" or "earliest".
    """
    ordered = sorted(members, key=lambda m: m["when"])
    heads = {}
    for m in ordered:  # one headline per outlet, the earliest, so reprints don't count twice
        heads.setdefault(m["source"], m["title"])
    sets = [{k for k in map(_key, TOKEN.findall(t)) if len(k) >= 3 and k not in STOP} for t in heads.values()]
    df = Counter(k for s in sets for k in s)
    chosen = {k for k, c in df.items() if c >= max(2, math.ceil(len(heads) / 3))}
    if len(chosen) < 2:
        chosen = {k for k, c in df.items() if c >= 2}
    if len(chosen) > max_words:  # too many: keep the most widely shared
        chosen = set(sorted(chosen, key=lambda k: (-df[k], -len(k), k))[:max_words])
    if len(chosen) >= 2:
        def caps(t):  # prefer a sentence-case headline as the model, so the label's casing is consistent
            return sum(1 for m in TOKEN.finditer(t) if m.start() > 0 and m.group()[0].isupper() and _key(m.group()) not in chosen)
        ref = min(heads.values(), key=lambda t: (-sum(1 for k in {_key(x) for x in TOKEN.findall(t)} if k in chosen), caps(t)))
        runs, run, used = [], [], set()
        for m in TOKEN.finditer(ref):
            k = _key(m.group())
            if k in chosen and k not in used:
                run.append(m.group())
                used.add(k)
            elif run:
                runs.append(run)
                run = []
        if run:
            runs.append(run)
        label = "\u00a0\u00b7 ".join(" ".join(r) for r in runs)  # the dot stays with the phrase before it, so a line never starts with one
        if len(label.split()) >= 2:
            return label[0].upper() + label[1:], "shared", None
    first = ordered[0]
    return first["title"], "earliest", first["source"]


def story_facts(members):
    """When each outlet reported, and when each side first did."""
    ordered = sorted(members, key=lambda m: m["when"])
    by_side = {l: next((m for m in ordered if m["lean"] == l), None) for l in LEANS}
    present = [l for l in LEANS if by_side[l]]
    nxt = next((m for m in ordered if m["source"] != ordered[0]["source"]), None)  # the next different outlet
    return {
        "ordered": ordered,
        "first": ordered[0],
        "next": nxt,
        "last": ordered[-1],
        "by_side": by_side,
        "all_sides_at": max(by_side[l]["when"] for l in present) if len(present) == len(LEANS) else None,
    }


def annotate(stories):
    """Attach the timing facts to each story."""
    for s in stories:
        s["facts"] = story_facts(s["members"])
        s["label"], s["label_kind"], s["label_src"] = story_label(s["members"])
    return stories


def fmt_dur(seconds):
    m = seconds / 60
    if m < 90:
        return f"{max(round(m), 1)} min"
    h = m / 60
    if h < 48:
        return (f"{h:.1f}".rstrip("0").rstrip(".")) + " h"
    return f"{round(h / 24)} days"


def clock(dt):
    """A time of day in this machine's time zone (the page re-shows it in the reader's own zone)."""
    local = dt.astimezone()
    same_day = local.date() == datetime.now().astimezone().date()
    return local.strftime("%-I:%M %p" if same_day else "%a %-I:%M %p")


def day_summary(stories, articles):
    all_three = [s for s in stories if s["facts"]["all_sides_at"]]
    fastest = None
    for s in all_three:
        f = s["facts"]
        took = (f["all_sides_at"] - f["first"]["when"]).total_seconds()
        if fastest is None or took < fastest[0]:
            fastest = (took, s)
    return {
        "stories": len(stories),
        "articles": len(articles),
        "outlets": len({a["source"] for a in articles}),
        "all_three": len(all_three),
        "no_left": sum("left" in s["missing"] for s in stories),
        "no_right": sum("right" in s["missing"] for s in stories),
        "fastest": fastest,
    }


def outlet_stats(stories):
    """For each outlet: how many of this page's stories it appears in, and in how many it reported first."""
    stats = {}
    for s in stories:
        for m in s["members"]:
            stats.setdefault(m["source"], {"stories": 0, "first": 0})["stories"] += 1
        stats[s["facts"]["first"]["source"]]["first"] += 1
    return stats


def _iso(dt):
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def snapshot(built, topics, summary, stats, cfg, hours, edits=None, recent=None, clips=None):
    """The whole build as plain data, for anyone to download and analyze."""
    stories = []
    for topic, (items, _) in topics.items():
        for s in items:
            f = s["facts"]
            stories.append({
                "id": s.get("sid") or hashlib.sha1(f["first"]["link"].encode()).hexdigest()[:12],
                "page": f"story/{s.get('sid')}.html" if s.get("sid") else None,
                "topic": topic,
                "label": s["label"],
                "label_kind": s["label_kind"],
                "label_headline_from": s["label_src"],
                "outlets": len(s["members"]),
                "by_side": {l: sum(m["lean"] == l for m in s["members"]) for l in LEANS},
                "not_covered_by": s["missing"],
                "first_reported": {"outlet": f["first"]["source"], "side": f["first"]["lean"], "at": _iso(f["first"]["when"])},
                "first_by_side": {l: (_iso(f["by_side"][l]["when"]) if f["by_side"][l] else None) for l in LEANS},
                "all_sides_at": _iso(f["all_sides_at"]) if f["all_sides_at"] else None,
                "popularity": {"mastodon_people": s["buzz"]["mastodon"], "hacker_news_points": s["buzz"]["hn_points"],
                               "bluesky_trend": (s["buzz"]["bluesky"] or {}).get("name")},
                "reports": [dict({"outlet": m["source"], "side": m["lean"], "type": m.get("type", ""), "headline": m["title"],
                                  "url": m["link"], "published": _iso(m["when"])},
                                 **({"headline_versions": [dict(v, first_seen=_iso(datetime.fromtimestamp(v["first_seen"], timezone.utc)),
                                                                last_seen=_iso(datetime.fromtimestamp(v["last_seen"], timezone.utc)))
                                                           for v in edits[m["link"]]]} if edits and m["link"] in edits else {}))
                            for m in f["ordered"]],
            })
    sources = [{"outlet": c["name"], "type": "articles", "side": c["lean"], "type": c.get("type", ""),
                "topic": c.get("topic", "us"), "site": c.get("site"), "feed": c["url"],
                "items_in_window": c.get("_n"), "stories_on_page": stats.get(c["name"], {}).get("stories", 0),
                "first_in_stories": stats.get(c["name"], {}).get("first", 0)} for c in cfg["feeds"]]
    sources += [{"outlet": c["name"], "type": "social", "platform": c["platform"], "handle": c["handle"],
                 "items_in_window": c.get("_n")} for c in cfg.get("social", [])]
    sources += [{"outlet": c["name"], "type": "video", "side": c["lean"], "type": c.get("type", ""),
                 "channel": f"https://www.youtube.com/@{c['handle']}", "items_in_window": c.get("_n")} for c in cfg["channels"]]
    return {
        "schema": 1,
        "built": _iso(datetime.fromtimestamp(built, timezone.utc)),
        "window_hours": hours,
        "note": "Sides are one maintainer's judgment, not facts. Story ids stay the same from build to build. A report carries headline_versions only if its headline changed between our checks; headline_edits lists every tracked article whose headline changed in the last 7 days. See methods.html for how every field is worked out.",
        "summary": {k: v for k, v in summary.items() if k != "fastest"},
        "stories": stories,
        "headline_edits": [dict(e, versions=[dict(v, first_seen=_iso(datetime.fromtimestamp(v["first_seen"], timezone.utc)),
                                                  last_seen=_iso(datetime.fromtimestamp(v["last_seen"], timezone.utc)))
                                             for v in e["versions"]]) for e in (recent or [])],
        "sources": sources,
        "clips_and_posts": clips or [],
    }


def record_history(path, built, topics, articles, min_gap=3300, keep_days=90):
    """Append a small hourly snapshot so later versions can compare today with a typical day.

    Stored on this machine only (never published): the size of each story, how one-sided the day was, and how
    often each headline word appeared. Entries older than `keep_days` are dropped.
    """
    path.parent.mkdir(exist_ok=True)
    lines = path.read_text().splitlines() if path.exists() else []
    if lines:
        try:
            if built - json.loads(lines[-1])["built"] < min_gap:
                return False
        except (ValueError, KeyError):
            pass
    by_topic = {}
    for topic, (items, _) in topics.items():
        by_topic[topic] = {
            "articles": sum(a["topic"] == topic for a in articles),
            "stories": [len(s["members"]) for s in items],
            "no_left": sum("left" in s["missing"] for s in items),
            "no_right": sum("right" in s["missing"] for s in items),
        }
    terms = Counter(w for a in articles for w in words(a["title"]))
    rec = {"built": built, "topics": by_topic, "terms": dict(terms.most_common(300))}
    cutoff = built - keep_days * 86400
    keep = []
    for ln in lines:
        try:
            if json.loads(ln)["built"] >= cutoff:
                keep.append(ln)
        except (ValueError, KeyError):
            continue
    keep.append(json.dumps(rec, separators=(",", ":")))
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text("\n".join(keep) + "\n")
    os.replace(tmp, path)
    return True
