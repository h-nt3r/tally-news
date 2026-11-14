"""A persistent archive of what outlets published, so stories can be followed across days.

Stores, per headline: its link, outlet, side label, topic, publish time, when it was first and last seen, every
version of its headline (so edits can be detected), and which story it belongs to. It stores no article text and
nothing about readers. Lives in one SQLite file on the machine that builds the site; it is never published.

Stories keep the same id from build to build: a new cluster of headlines inherits the id of the earlier story it
shares the most headlines with. See the Methods page for how this is described to readers.
"""
import calendar
import hashlib
import json
import sqlite3
import time
from datetime import datetime, timezone
from pathlib import Path

import analytics

SCHEMA = """
CREATE TABLE IF NOT EXISTS articles(
  url TEXT PRIMARY KEY, source TEXT, lean TEXT, fringe INTEGER, topic TEXT, title TEXT,
  published INTEGER, first_seen INTEGER, last_seen INTEGER, story_id TEXT, type TEXT);  -- fringe is a retired column, kept so old archives still open
CREATE TABLE IF NOT EXISTS titles(
  url TEXT, title TEXT, first_seen INTEGER, last_seen INTEGER, PRIMARY KEY(url, title));
CREATE TABLE IF NOT EXISTS stories(
  id TEXT PRIMARY KEY, topic TEXT, first_seen INTEGER, last_seen INTEGER, first_published INTEGER, lead_title TEXT);
CREATE TABLE IF NOT EXISTS observations(
  built INTEGER, story_id TEXT, outlets INTEGER, left_n INTEGER, center_n INTEGER, right_n INTEGER,
  PRIMARY KEY(built, story_id));
CREATE TABLE IF NOT EXISTS meta(key TEXT PRIMARY KEY, value TEXT);
CREATE TABLE IF NOT EXISTS posts(
  url TEXT PRIMARY KEY, platform TEXT, source TEXT, handle TEXT, text TEXT, published INTEGER,
  first_seen INTEGER, last_seen INTEGER, video INTEGER);
CREATE TABLE IF NOT EXISTS post_story(url TEXT PRIMARY KEY, story_id TEXT, score REAL);
CREATE INDEX IF NOT EXISTS idx_post_story_story ON post_story(story_id);
CREATE INDEX IF NOT EXISTS idx_articles_story ON articles(story_id);
CREATE INDEX IF NOT EXISTS idx_articles_published ON articles(published);
"""
LEANS = ("left", "center", "right")


def open_archive(path):
    path = Path(path)
    path.parent.mkdir(exist_ok=True)
    conn = sqlite3.connect(path, timeout=30)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.executescript(SCHEMA)
    if "media_json" not in [r[1] for r in conn.execute("PRAGMA table_info(posts)")]:
        conn.execute("ALTER TABLE posts ADD COLUMN media_json TEXT")
        conn.commit()
    if "type" not in [r[1] for r in conn.execute("PRAGMA table_info(articles)")]:
        conn.execute("ALTER TABLE articles ADD COLUMN type TEXT")
        conn.commit()
    _repair_publish_times(conn)
    _relabel_stories(conn)
    return conn


def _relabel_stories(conn):
    """One-time: stories used to be named after one outlet's headline. Recompute each as a neutral label."""
    if conn.execute("SELECT 1 FROM meta WHERE key='story_labels_v2'").fetchone():
        return
    with conn:
        for (sid,) in conn.execute("SELECT id FROM stories").fetchall():
            members = [{"source": o, "lean": l, "type": ty or "", "title": t, "when": datetime.fromtimestamp(p, timezone.utc)}
                       for o, l, ty, t, p in conn.execute("SELECT source, lean, type, title, published FROM articles WHERE story_id=?", (sid,))]
            if members:
                conn.execute("UPDATE stories SET lead_title=? WHERE id=?", (_lead(members), sid))
        conn.execute("INSERT INTO meta VALUES('story_labels_v2', '1')")


def _repair_publish_times(conn):
    """One-time fix. Early builds converted feed times with mktime, which shifted every stored publish time by this
    computer's UTC offset. localtime() undoes that exactly. A fresh archive has nothing to fix and just gets the marker."""
    if conn.execute("SELECT 1 FROM meta WHERE key='publish_times_utc'").fetchone():
        return
    rows = conn.execute("SELECT url, published FROM articles").fetchall()
    with conn:
        if rows:
            conn.executemany("UPDATE articles SET published=? WHERE url=?",
                             [(calendar.timegm(time.localtime(p)), u) for u, p in rows])
            conn.execute("UPDATE stories SET first_published = (SELECT MIN(published) FROM articles WHERE story_id = stories.id) "
                         "WHERE id IN (SELECT DISTINCT story_id FROM articles WHERE story_id IS NOT NULL)")
        conn.execute("INSERT INTO meta VALUES('publish_times_utc', '1')")


def _clean(title):
    return " ".join(title.split())


def _lead(members):
    """The story's neutral label (the words its outlets' headlines share), not any one outlet's headline."""
    return analytics.story_label(members)[0]


def _assign_story_ids(conn, built, topics):
    """Give every story an id that survives from build to build.

    A cluster inherits the id of the earlier story it shares the most headlines with. If two clusters want the
    same earlier story (it split), the larger one keeps the id and the other gets a new one. A cluster that shares
    nothing with an earlier story is new. When two earlier stories merge, the cluster keeps the better overlap
    and the other id simply stops being updated; it stays in the archive as history.
    """
    clusters = [(topic, s) for topic, (stories, _) in topics.items() for s in stories]
    clusters.sort(key=lambda ts: -len(ts[1]["members"]))  # larger clusters choose first
    used, new_ids = set(), 0
    for topic, s in clusters:
        urls = [m["link"] for m in s["members"]]
        marks = ",".join("?" * len(urls))
        rows = conn.execute(
            f"SELECT a.story_id, COUNT(*) AS c, st.first_seen FROM articles a JOIN stories st ON st.id = a.story_id "
            f"WHERE a.url IN ({marks}) AND a.story_id IS NOT NULL GROUP BY a.story_id", urls).fetchall()
        rows.sort(key=lambda r: (-r[1], r[2]))  # most shared headlines, then the older story
        sid = next((r[0] for r in rows if r[0] not in used), None)
        if sid is None:
            first = min(s["members"], key=lambda m: m["when"])
            sid = hashlib.sha1(f"{first['link']}|{built}".encode()).hexdigest()[:12]
            new_ids += 1
        used.add(sid)
        s["sid"] = sid
        pubs = [int(m["when"].timestamp()) for m in s["members"]]
        counts = {l: sum(m["lean"] == l for m in s["members"]) for l in LEANS}
        conn.execute(
            "INSERT INTO stories(id, topic, first_seen, last_seen, first_published, lead_title) VALUES(?,?,?,?,?,?) "
            "ON CONFLICT(id) DO UPDATE SET last_seen=excluded.last_seen, lead_title=excluded.lead_title, "
            "topic=excluded.topic, first_published=MIN(first_published, excluded.first_published)",
            (sid, topic, built, built, min(pubs), _lead(s["members"])))
        conn.executemany("UPDATE articles SET story_id=? WHERE url=?", [(sid, u) for u in urls])
        shape = (len(s["members"]), counts["left"], counts["center"], counts["right"])
        last = conn.execute("SELECT outlets, left_n, center_n, right_n FROM observations WHERE story_id=? "
                            "ORDER BY built DESC LIMIT 1", (sid,)).fetchone()
        if last != shape:  # a step function: only when the story's size or side mix changed
            conn.execute("INSERT OR REPLACE INTO observations VALUES(?,?,?,?,?,?)", (built, sid, *shape))
    return new_ids


def record_build(path, built, articles, topics, keep_days=365):
    """Save this build into the archive. Sets s["sid"] on every story. Returns small counts for the log."""
    conn = open_archive(path)
    try:
        with conn:
            new_articles = edits = 0
            for a in articles:
                url, title = a["link"], _clean(a["title"])
                row = conn.execute("SELECT title FROM articles WHERE url=?", (url,)).fetchone()
                if row is None:
                    conn.execute("INSERT INTO articles(url, source, lean, type, topic, title, published, first_seen, last_seen) "
                                 "VALUES(?,?,?,?,?,?,?,?,?)",
                                 (url, a["source"], a["lean"], a.get("type", ""), a["topic"], title,
                                  int(a["when"].timestamp()), built, built))
                    new_articles += 1
                else:
                    conn.execute("UPDATE articles SET title=?, source=?, lean=?, type=?, topic=?, last_seen=? WHERE url=?",
                                 (title, a["source"], a["lean"], a.get("type", ""), a["topic"], built, url))
                    if row[0] != title:
                        edits += 1
                conn.execute("INSERT INTO titles(url, title, first_seen, last_seen) VALUES(?,?,?,?) "
                             "ON CONFLICT(url, title) DO UPDATE SET last_seen=excluded.last_seen",
                             (url, title, built, built))
            new_stories = _assign_story_ids(conn, built, topics)
            cutoff = built - keep_days * 86400
            conn.execute("DELETE FROM titles WHERE url IN (SELECT url FROM articles WHERE last_seen < ?)", (cutoff,))
            conn.execute("DELETE FROM articles WHERE last_seen < ?", (cutoff,))
            conn.execute("DELETE FROM observations WHERE built < ?", (cutoff,))
            conn.execute("DELETE FROM stories WHERE last_seen < ?", (cutoff,))
        return {"new_articles": new_articles, "edits": edits, "new_stories": new_stories}
    finally:
        conn.close()


def edited_headlines(path, urls):
    """For the given links, every headline version we saw, but only where there was more than one."""
    path = Path(path)
    if not path.exists() or not urls:
        return {}
    conn = sqlite3.connect(path, timeout=30)
    try:
        out = {}
        for i in range(0, len(urls), 500):
            chunk = urls[i:i + 500]
            marks = ",".join("?" * len(chunk))
            rows = conn.execute(
                f"SELECT url, title, first_seen, last_seen FROM titles WHERE url IN ({marks}) "
                f"AND url IN (SELECT url FROM titles GROUP BY url HAVING COUNT(*) > 1) ORDER BY url, first_seen", chunk)
            for url, title, first, last in rows:
                out.setdefault(url, []).append({"headline": title, "first_seen": first, "last_seen": last})
        return out
    finally:
        conn.close()


def recent_edits(path, since):
    """Every article whose headline changed after `since`, with all its versions (any article we track, not just the page's stories)."""
    path = Path(path)
    if not path.exists():
        return []
    conn = sqlite3.connect(path, timeout=30)
    try:
        rows = conn.execute(
            "SELECT a.url, a.source, a.lean, t.title, t.first_seen, t.last_seen FROM titles t JOIN articles a ON a.url = t.url "
            "WHERE t.url IN (SELECT url FROM titles GROUP BY url HAVING COUNT(*) > 1 AND MAX(first_seen) >= ?) "
            "ORDER BY a.url, t.first_seen", (since,)).fetchall()
    finally:
        conn.close()
    out = {}
    for url, source, lean, title, first, last in rows:
        e = out.setdefault(url, {"url": url, "outlet": source, "side": lean, "versions": []})
        e["versions"].append({"headline": title, "first_seen": first, "last_seen": last})
    return list(out.values())


def story_record(conn, sid):
    """One story with every report the archive holds for it (across days), and each report's headline versions."""
    st = conn.execute("SELECT id, topic, first_seen, last_seen, first_published, lead_title FROM stories WHERE id=?", (sid,)).fetchone()
    if st is None:
        return None
    rows = conn.execute("SELECT url, source, lean, type, title, published, first_seen FROM articles WHERE story_id=? "
                        "ORDER BY published, url", (sid,)).fetchall()
    changed_at = max([r[6] for r in rows] or [st[3]])
    versions = {}
    for i in range(0, len(rows), 500):
        urls = [r[0] for r in rows[i:i + 500]]
        marks = ",".join("?" * len(urls))
        for url, title, first, last in conn.execute(
                f"SELECT url, title, first_seen, last_seen FROM titles WHERE url IN ({marks}) ORDER BY url, first_seen", urls):
            versions.setdefault(url, []).append({"headline": title, "first_seen": first, "last_seen": last})
    for vs in versions.values():
        changed_at = max([changed_at] + [v["first_seen"] for v in vs])
    posts = []
    for url, platform, source, handle, text, published, video, score, first_seen, media_json in conn.execute(
            "SELECT p.url, p.platform, p.source, p.handle, p.text, p.published, p.video, ps.score, p.first_seen, p.media_json "
            "FROM post_story ps JOIN posts p ON p.url = ps.url WHERE ps.story_id=? ORDER BY p.published DESC", (sid,)):
        posts.append({"url": url, "platform": platform, "source": source, "handle": handle, "text": text,
                      "published": published, "video": bool(video), "score": score,
                      "media": json.loads(media_json) if media_json else None})
        changed_at = max(changed_at, first_seen)  # a new matching clip means the page should be rebuilt
    return {
        "id": st[0], "topic": st[1], "first_seen": st[2], "last_seen": st[3], "first_published": st[4], "lead": st[5],
        "changed_at": changed_at,  # when a report joined, a headline changed or a clip matched, so unchanged stories rebuild identically
        "posts": posts,
        "reports": [{"url": u, "outlet": o, "side": l, "type": f or "", "headline": t, "published": p,
                     "versions": versions[u] if len(versions.get(u, [])) > 1 else []} for u, o, l, f, t, p, _ in rows],
    }


def story_ids_since(conn, since):
    return [r[0] for r in conn.execute("SELECT id FROM stories WHERE last_seen >= ?", (since,))]


def all_story_ids(conn):
    return {r[0] for r in conn.execute("SELECT id FROM stories")}


def story_listing(conn, since):
    """A one-line summary of every story seen since `since`, newest first, for the archive page."""
    return conn.execute(
        "SELECT s.id, s.topic, s.lead_title, s.first_published, s.last_seen, "
        "COUNT(DISTINCT a.source), "
        "COUNT(DISTINCT CASE WHEN a.lean='left' THEN a.source END), "
        "COUNT(DISTINCT CASE WHEN a.lean='center' THEN a.source END), "
        "COUNT(DISTINCT CASE WHEN a.lean='right' THEN a.source END), "
        "(SELECT source FROM articles WHERE story_id = s.id ORDER BY published LIMIT 1) "
        "FROM stories s JOIN articles a ON a.story_id = s.id WHERE s.last_seen >= ? "
        "GROUP BY s.id ORDER BY s.first_published DESC", (since,)).fetchall()


def headlines_since(conn, since, limit=12000):
    """Every article remembered since `since`, newest first, including the ones no other outlet ran."""
    return conn.execute(
        "SELECT url, source, lean, type, topic, title, published, story_id FROM articles "
        "WHERE published >= ? AND published <= ? ORDER BY published DESC LIMIT ?",
        (since, int(time.time()) + 600, limit)).fetchall()


def record_posts(path, built, posts, matches, keep_days=365):
    """Remember clips and posts from followed accounts, and which story each one matched."""
    conn = open_archive(path)
    try:
        with conn:
            for p in posts:
                conn.execute(
                    "INSERT INTO posts(url, platform, source, handle, text, published, first_seen, last_seen, video, media_json) "
                    "VALUES(?,?,?,?,?,?,?,?,?,?) ON CONFLICT(url) DO UPDATE SET last_seen=excluded.last_seen, text=excluded.text, "
                    "video=excluded.video, media_json=excluded.media_json",
                    (p["url"], p["platform"], p["source"], p["handle"], p["text"], int(p["when"].timestamp()), built, built,
                     int(p["video"]), json.dumps(p.get("media")) if p.get("media") else None))
            for p, s, score in matches:
                if s.get("sid"):
                    conn.execute("INSERT INTO post_story(url, story_id, score) VALUES(?,?,?) "
                                 "ON CONFLICT(url) DO UPDATE SET story_id=excluded.story_id, score=excluded.score",
                                 (p["url"], s["sid"], score))
            cutoff = built - keep_days * 86400
            conn.execute("DELETE FROM post_story WHERE url IN (SELECT url FROM posts WHERE last_seen < ?)", (cutoff,))
            conn.execute("DELETE FROM posts WHERE last_seen < ?", (cutoff,))
        return {"posts": len(posts), "matched": sum(1 for _, s, _ in matches if s.get("sid"))}
    finally:
        conn.close()


def recent_posters(path, since):
    """Locally cached preview frames still in use by clips seen since `since`, so the rest can be cleaned up."""
    path = Path(path)
    if not path.exists():
        return set()
    conn = sqlite3.connect(path, timeout=30)
    try:
        out = set()
        for (mj,) in conn.execute("SELECT media_json FROM posts WHERE last_seen >= ? AND media_json IS NOT NULL", (since,)):
            local = (json.loads(mj) or {}).get("poster_local")
            if local:
                out.add(local)
        return out
    finally:
        conn.close()
