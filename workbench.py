"""The workbench: your own copy of the source list, kept as a short list of changes on top of the defaults.

config/sources.toml is the default list and is never edited here. Your removals, additions and relabelings live in
workbench/changes.toml. "Reset to default" is deleting that one file, so the way back to the full picture is always
a click away, and new default outlets keep arriving even after you have customized.

This file has two halves. The first half is plain functions (read the changes, apply them, check a new source, find a
feed from a pasted address) and has no network or file side effects except where it says so. The second half is a small
web server for the "Manage sources" page. It listens on this Mac only, and every change needs a secret token, so a
web page you happen to visit cannot edit your list.

    .venv/bin/python workbench.py serve        then open http://localhost:8766
"""
import copy
import ipaddress
import json
import re
import secrets
import socket
import sys
import tomllib
import urllib.parse
from pathlib import Path

ROOT = Path(__file__).parent
WORK = ROOT / "workbench"
CHANGES = WORK / "changes.toml"

KINDS = ("feeds", "channels")  # written articles, YouTube channels
LEANS = ("left", "center", "right")
TYPES = ("wire", "public", "state", "nonprofit", "commercial")
TOPICS = ("us", "world", "tech")
KIND_WORD = {"feeds": "articles", "channels": "videos"}


# ---------- the changes file ----------

def empty_changes():
    return {"remove": [], "feeds": [], "channels": [], "override": []}


def load_changes(path=CHANGES):
    """Read the changes file. A missing file means no changes. A broken one raises ValueError with a plain message."""
    path = Path(path)
    if not path.exists():
        return empty_changes()
    try:
        raw = tomllib.loads(path.read_text())
    except tomllib.TOMLDecodeError as ex:
        raise ValueError(f"{path.name} is not valid TOML ({ex}). Fix it, or reset the workbench to the default list.")
    out = empty_changes()
    for key in out:
        rows = raw.get(key, [])
        if not isinstance(rows, list) or not all(isinstance(r, dict) for r in rows):
            raise ValueError(f"{path.name}: [[{key}]] should be a list of entries")
        out[key] = rows
    return out


def _toml_str(s):
    out = ['"']
    for ch in str(s):
        if ch in '\\"':
            out.append("\\" + ch)
        elif ord(ch) < 32 or ord(ch) == 127:
            out.append(f"\\u{ord(ch):04x}")
        else:
            out.append(ch)
    out.append('"')
    return "".join(out)


def _toml_val(v):
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, int):
        return str(v)
    return _toml_str(v)


HEADER = """# Your workbench changes, on top of config/sources.toml (the defaults, which are never edited here).
# The Manage sources page writes this file for you. You can also edit it by hand.
# Delete this file, or press "Reset to default" on the Manage page, to get every default source back.
#   [[remove]]    kind = "feeds" or "channels", name = the outlet's name: hide a default source for good
#   [[feeds]]     a source you added: same fields as in sources.toml
#   [[channels]]  a YouTube channel you added
#   [[override]]  kind, name, plus lean / type / topic: change a default source's label

"""


def dump_changes(changes):
    parts = [HEADER]
    for key in ("remove", "override", "feeds", "channels"):
        for row in changes.get(key, []):
            parts.append(f"[[{key}]]\n" + "".join(f"{k} = {_toml_val(v)}\n" for k, v in row.items() if v not in (None,)) + "\n")
    return "".join(parts)


def save_changes(changes, path=CHANGES):
    path = Path(path)
    path.parent.mkdir(exist_ok=True)
    if not any(changes.get(k) for k in empty_changes()):
        path.unlink(missing_ok=True)  # nothing left to remember
        return
    tmp = path.with_suffix(".tmp")
    tmp.write_text(dump_changes(changes))
    tmp.replace(path)


# ---------- applying the changes ----------

def _find(entries, name):
    return next((e for e in entries if e["name"] == name), None)


def apply_changes(cfg, changes):
    """The default config with the changes applied. Returns (new config, report). The input is not modified."""
    new = copy.deepcopy(cfg)
    rep = {"defaults": len(cfg["feeds"]) + len(cfg["channels"]), "removed": [], "added": [], "relabeled": [], "skipped": []}
    for o in changes.get("override", []):
        e = _find(new.get(o.get("kind"), []), o.get("name"))
        if not e:
            rep["skipped"].append(f'{o.get("name")} (not in the default list, so it was not relabeled)')
            continue
        for field in ("lean", "type", "topic"):
            if field in o and (field != "lean" or o[field] in LEANS):
                if o[field] == "" and field == "type":
                    e.pop("type", None)
                elif field != "topic" or o["kind"] == "feeds":
                    e[field] = o[field]
        rep["relabeled"].append(o["name"])
    for r in changes.get("remove", []):
        kind, name = r.get("kind"), r.get("name")
        if kind in KINDS and _find(new[kind], name):
            new[kind] = [e for e in new[kind] if e["name"] != name]
            rep["removed"].append({"kind": kind, "name": name})
    for kind in KINDS:
        for e in changes.get(kind, []):
            if _find(new[kind], e.get("name")):
                rep["skipped"].append(f'{e.get("name")} (already in the list)')
                continue
            new[kind].append(dict(e))
            rep["added"].append({"kind": kind, "name": e["name"]})
    return new, rep


# ---------- checking a new source ----------

def _clean_name(name):
    name = " ".join(str(name or "").split())
    if not 1 <= len(name) <= 60 or any(ord(c) < 32 for c in name):
        raise ValueError("Give the source a name of 1 to 60 characters.")
    return name


def check_url_is_public(url, resolve=socket.getaddrinfo):
    """Only http(s) addresses on the open internet. This keeps the add tool from being pointed at your own network."""
    p = urllib.parse.urlsplit(url)
    if p.scheme not in ("http", "https") or not p.hostname:
        raise ValueError("That should be a web address starting with http:// or https://")
    try:
        infos = resolve(p.hostname, None)
    except OSError:
        raise ValueError(f"Could not find {p.hostname}. Check the spelling.")
    for info in infos:
        ip = ipaddress.ip_address(info[4][0])
        if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved or ip.is_multicast:
            raise ValueError("That address points at a private or local network, so it is not allowed.")


def clean_entry(kind, d, existing):
    """A validated new source, ready for the changes file. Raises ValueError with a plain message."""
    if kind not in KINDS:
        raise ValueError("Unknown kind of source.")
    name = _clean_name(d.get("name"))
    if any(e["name"] == name for e in existing[kind]):
        raise ValueError(f"There is already a source called {name}.")
    lean = d.get("lean")
    if lean not in LEANS:
        raise ValueError("Choose a side: left, center or right. That label is yours to set.")
    out = {"name": name}
    if kind == "feeds":
        url = str(d.get("url") or "").strip()
        if not re.match(r"https?://", url):
            raise ValueError("The feed address should start with http:// or https://")
        if any(e["url"] == url for e in existing["feeds"]):
            raise ValueError("That feed is already in the list.")
        out["url"] = url
        site = str(d.get("site") or "").strip()
        if site:
            if not re.match(r"https?://", site):
                raise ValueError("The website address should start with http:// or https://")
            out["site"] = site
        topic = d.get("topic", "us")
        if topic not in TOPICS:
            raise ValueError("Choose a topic: us, world or tech.")
        out.update({"lean": lean, "topic": topic})
    else:
        handle = str(d.get("handle") or "").strip().lstrip("@")
        if not re.fullmatch(r"[\w.-]{1,60}", handle):
            raise ValueError("A YouTube handle has only letters, numbers, dots, dashes and underscores.")
        if any(e["handle"].lower() == handle.lower() for e in existing["channels"]):
            raise ValueError("That channel is already in the list.")
        out.update({"handle": handle, "lean": lean})
    t = d.get("type") or ""
    if t:
        if t not in TYPES:
            raise ValueError("Unknown outlet type.")
        out["type"] = t
    return out


# ---------- finding a feed from a pasted address ----------

LINK_TAG = re.compile(r"<link\b[^>]*>", re.I)
COMMON_PATHS = ("/feed", "/rss", "/rss.xml", "/feed.xml", "/atom.xml", "/index.xml")


def _attr(tag, name):
    m = re.search(rf"""\b{name}\s*=\s*(?:"([^"]*)"|'([^']*)'|([^\s>]+))""", tag, re.I)
    return (m.group(1) or m.group(2) or m.group(3)) if m else None


def feed_links(html_text, base_url):
    """Feed addresses a web page advertises in its <head>."""
    out = []
    for tag in LINK_TAG.findall(html_text):
        rel, typ, href = (_attr(tag, "rel") or "").lower(), (_attr(tag, "type") or "").lower(), _attr(tag, "href")
        if href and "alternate" in rel and ("rss" in typ or "atom" in typ):
            out.append(urllib.parse.urljoin(base_url, href))
    return list(dict.fromkeys(out))


def youtube_handle(url):
    """The channel handle in a youtube.com address, or None. /c/Name and /user/Name pages also answer at @Name."""
    p = urllib.parse.urlsplit(url if "//" in url else "https://" + url)
    if not (p.hostname or "").endswith("youtube.com"):
        return None
    m = re.match(r"^/(?:@|c/|user/)([\w.-]+)", p.path)
    return m.group(1) if m else None


def _preview(parsed, limit=5):
    return [{"title": " ".join((e.get("title") or "(no title)").split())[:140],
             "published": e.get("published", "")[:25]} for e in parsed.entries[:limit]]


def discover(text, fetch, parse):
    """Work out what a pasted address is. `fetch(url)` returns bytes, `parse(bytes)` returns a feedparser result.

    Returns {"kind": "feeds", "name", "url", "site", "items", "others": [...]} for an article feed, or
    {"kind": "channels", "name", "handle", "items"} for a YouTube channel. Raises ValueError with a plain message.
    """
    text = text.strip()
    if not text:
        raise ValueError("Paste a website, a feed address or a YouTube channel.")
    handle = youtube_handle(text) if "youtube.com" in text else (text.lstrip("@") if text.startswith("@") else None)
    if handle:
        if not re.fullmatch(r"[\w.-]{1,60}", handle):
            raise ValueError("That does not look like a YouTube handle.")
        url = f"https://www.youtube.com/@{handle}"
        try:
            page = fetch(url).decode("utf-8", "ignore")
        except Exception:
            raise ValueError(f"YouTube has no channel at @{handle}. Check the handle.")
        title = re.search(r"<title>([^<]*)</title>", page)
        name = re.sub(r"\s*-\s*YouTube\s*$", "", title.group(1)).strip() if title else handle
        cid = re.search(r"channel_id=(UC[\w-]{22})", page) or re.search(r'"externalId":"(UC[\w-]{22})"', page)
        items, note = [], ""
        if cid:
            try:
                items = _preview(parse(fetch(f"https://www.youtube.com/feeds/videos.xml?channel_id={cid.group(1)}")))
            except Exception:
                note = "Could not preview its latest videos right now (YouTube's feed is sometimes unavailable). It may still work."
        else:
            note = "Found the channel page but not its feed, so it may not load."
        return {"kind": "channels", "name": html_unescape(name), "handle": handle, "items": items, "note": note}

    if "//" not in text:
        text = "https://" + text
    check_url_is_public(text)
    try:
        body = fetch(text)
    except Exception as ex:
        raise ValueError(f"Could not open that address ({ex}).")
    parsed = parse(body)
    found = []
    if parsed.entries:
        found.append((text, parsed))
    else:
        page = body.decode("utf-8", "ignore")
        candidates = feed_links(page, text) or [urllib.parse.urljoin(text, p) for p in COMMON_PATHS]
        for c in candidates[:8]:
            try:
                check_url_is_public(c)
                got = parse(fetch(c))
            except Exception:
                continue
            if got.entries:
                found.append((c, got))
    if not found:
        raise ValueError("No feed found at that address. Try the site's own feed address (often ends in /feed or /rss).")
    url, first = found[0]
    site = first.feed.get("link") or (urllib.parse.urlsplit(url)._replace(path="", query="", fragment="").geturl())
    return {"kind": "feeds", "name": html_unescape(first.feed.get("title") or urllib.parse.urlsplit(url).hostname)[:60],
            "url": url, "site": site, "items": _preview(first), "others": [u for u, _ in found[1:]], "note": ""}


def html_unescape(s):
    import html
    return html.unescape(s or "").strip()


# ---------- the server ----------

def make_token():
    return secrets.token_urlsafe(24)


def host_ok(host_header, port):
    """Only requests addressed to this Mac by name. This blocks DNS-rebinding tricks from other web pages."""
    return (host_header or "") in (f"127.0.0.1:{port}", f"localhost:{port}")


def origin_ok(origin, port):
    return origin is None or origin in (f"http://127.0.0.1:{port}", f"http://localhost:{port}")


def describe(defaults_cfg, changes):
    """Everything the Manage page needs: each default source with its state, what you added, and the counts."""
    removed = {(r.get("kind"), r.get("name")) for r in changes["remove"]}
    over = {(o.get("kind"), o.get("name")): o for o in changes["override"]}
    rows = []
    for kind in KINDS:
        for e in defaults_cfg[kind]:
            o = over.get((kind, e["name"]), {})
            rows.append({"kind": kind, "name": e["name"], "origin": "default", "removed": (kind, e["name"]) in removed,
                         "lean": o.get("lean", e["lean"]), "type": o.get("type", e.get("type", "")),
                         "topic": o.get("topic", e.get("topic", "us")) if kind == "feeds" else "",
                         "home": e.get("site") or e.get("url") or f"https://www.youtube.com/@{e.get('handle')}",
                         "default_lean": e["lean"], "default_type": e.get("type", "")})
    for kind in KINDS:
        for e in changes[kind]:
            rows.append({"kind": kind, "name": e["name"], "origin": "added", "removed": False, "lean": e.get("lean", ""),
                         "type": e.get("type", ""), "topic": e.get("topic", "") if kind == "feeds" else "",
                         "home": e.get("site") or e.get("url") or f"https://www.youtube.com/@{e.get('handle')}",
                         "default_lean": e.get("lean", ""), "default_type": e.get("type", "")})
    return {"sources": rows, "defaults": len(defaults_cfg["feeds"]) + len(defaults_cfg["channels"]),
            "removed": sum(1 for r in rows if r["removed"]), "added": sum(1 for r in rows if r["origin"] == "added"),
            "relabeled": len(changes["override"])}


def remove_source(changes, kind, name, defaults_cfg):
    if kind not in KINDS:
        raise ValueError("Unknown kind of source.")
    added = _find(changes[kind], name)
    if added:
        changes[kind] = [e for e in changes[kind] if e["name"] != name]
        return
    if not _find(defaults_cfg[kind], name):
        raise ValueError("No such source.")
    if not any(r.get("kind") == kind and r.get("name") == name for r in changes["remove"]):
        changes["remove"].append({"kind": kind, "name": name})


def restore_source(changes, kind, name):
    changes["remove"] = [r for r in changes["remove"] if not (r.get("kind") == kind and r.get("name") == name)]


def set_label(changes, kind, name, defaults_cfg, field, value):
    """Change a source's side, type or topic. A change back to the default removes the override."""
    if field == "lean" and value not in LEANS:
        raise ValueError("Choose left, center or right.")
    if field == "type" and value and value not in TYPES:
        raise ValueError("Unknown outlet type.")
    if field == "topic" and (kind != "feeds" or value not in TOPICS):
        raise ValueError("Topic only applies to written sources: us, world or tech.")
    added = _find(changes[kind], name)
    if added:  # something you added: edit it directly
        if field == "type" and not value:
            added.pop("type", None)
        else:
            added[field] = value
        return
    base = _find(defaults_cfg[kind], name)
    if not base:
        raise ValueError("No such source.")
    o = next((o for o in changes["override"] if o.get("kind") == kind and o.get("name") == name), None)
    if o is None:
        o = {"kind": kind, "name": name}
        changes["override"].append(o)
    o[field] = value
    if all(o.get(f, base.get(f, "")) == base.get(f, "") for f in ("lean", "type", "topic")):
        changes["override"].remove(o)  # back to the default, nothing to remember


if __name__ == "__main__":
    import workbench_server
    workbench_server.main(sys.argv[1:])
