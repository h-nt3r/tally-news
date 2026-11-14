"""Groups: one copy of Tally News per community (a mutual aid network, a union local, a DSA chapter, a neighborhood).

Each group is one plain file, groups/<name>/group.toml: a name, which outlets it follows, and a few settings. It builds
into its own folder with its own archive and its own port, so one computer can run several. Nothing is shared between groups
and nothing leaves the computer.

    .venv/bin/python groups.py new "Eastside Mutual Aid"          make groups/eastside-mutual-aid/group.toml
    .venv/bin/python groups.py new "Eastside Mutual Aid" --empty  same, but start from no outlets instead of the default list
    .venv/bin/python groups.py add eastside-mutual-aid https://example.org   find the feed on a pasted address and add it
    .venv/bin/python groups.py add-page eastside-mutual-aid https://example.gov/council/news --link-contains /news/
                                                                  watch a page that has no feed for new links (see pages.py)
    .venv/bin/python groups.py list
    ./group.sh eastside-mutual-aid                                build it and serve it
"""
import argparse
import re
import sys
import tomllib
import urllib.parse
import urllib.request
from pathlib import Path

import workbench as wb

ROOT = Path(__file__).resolve().parent
GROUPS = ROOT / "groups"
UA = {"User-Agent": "Mozilla/5.0 (compatible; TallyNewsGroups/1.0)"}
MAX_FETCH = 2_000_000
FIRST_PORT = 8771


class _SafeRedirects(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        wb.check_url_is_public(newurl)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


_OPENER = urllib.request.build_opener(_SafeRedirects)


def fetch(url):
    wb.check_url_is_public(url)
    with _OPENER.open(urllib.request.Request(url, headers=UA), timeout=15) as r:
        return r.read(MAX_FETCH)


def slugify(name):
    s = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")
    if not s:
        raise ValueError("Give the group a name with at least one letter or number.")
    return s[:40]


def group_dir(slug):
    if not re.fullmatch(r"[a-z0-9][a-z0-9-]{0,39}", slug):
        raise ValueError(f"'{slug}' is not a group folder name (lowercase letters, numbers and dashes).")
    return GROUPS / slug


def load(slug):
    """The group's file as a dict, with defaults filled in. Raises ValueError with a plain message."""
    path = group_dir(slug) / "group.toml"
    if not path.exists():
        raise ValueError(f"No group called '{slug}'. Make one with: .venv/bin/python groups.py new \"Its Name\"")
    try:
        g = tomllib.loads(path.read_text())
    except tomllib.TOMLDecodeError as ex:
        raise ValueError(f"{path} is not valid TOML ({ex}).")
    g.setdefault("name", slug)
    g.setdefault("base", "defaults")
    if g["base"] not in ("defaults", "none"):
        raise ValueError(f'{path}: base should be "defaults" (start from the default outlets) or "none" (only your own).')
    g.setdefault("settings", {})
    g["changes"] = wb.load_changes(path)  # [[remove]], [[feeds]], [[channels]] and [[override]] work exactly as in the workbench
    g["slug"] = slug
    return g


def apply(cfg, g):
    """The default config shaped for this group. Returns (config, report)."""
    base = dict(cfg)
    if g["base"] == "none":
        base = {**cfg, "feeds": [], "channels": [], "social": []}
    new, rep = wb.apply_changes(base, g["changes"])
    new["settings"] = {**cfg["settings"], **g["settings"]}
    st = new["settings"]
    # a small group follows fewer outlets, so it fetches fewer articles, and its local outlets rarely cover the same story:
    # keep the "something went wrong" safeguard in proportion, and list single-outlet stories too (the main page only groups multi-outlet ones)
    st.setdefault("min_articles", min(cfg["settings"].get("min_articles", 50), 5 * max(len(new["feeds"]), 1)))
    if "singles_topics" not in g["settings"]:
        st["singles_topics"] = ["us", "world", "tech"]
    return new, rep


def port_for(slug, g=None):
    g = g or load(slug)
    if isinstance(g.get("port"), int):
        return g["port"]
    names = sorted(p.parent.name for p in GROUPS.glob("*/group.toml"))
    return FIRST_PORT + (names.index(slug) if slug in names else 0)


TEMPLATE = '''# {name}: a Tally News group.
# This one file is the whole group: who it follows and a few settings. Edit it in any text editor, then run ./group.sh {slug}

name = {name_q}
tagline = "News from the outlets that matter to us."

# Where the outlet list starts:
#   "defaults" = the full default list in config/sources.toml, then your changes below
#   "none"     = only the outlets you add below
base = "{base}"

# port = {port}   # the address the group's page is served on, http://localhost:<port>

[settings]
# Anything in [settings] of config/sources.toml can be changed just for this group. Examples:
# hours_back = 72      # show the last 3 days instead of 36 hours (good for a group that follows slower outlets)
# summaries = false    # skip the machine-written summaries
# max_videos = 6

# ---- Outlets ----
# Add an outlet with:  .venv/bin/python groups.py add {slug} https://their-website.org
# or copy a block like this by hand. lean is yours to set: left, center or right. topic: us, world or tech.
# Local news can go under any topic; "us" is usually right.
#
# [[feeds]]
# name = "Example Neighborhood Paper"
# url = "https://example.org/feed"
# site = "https://example.org"
# lean = "center"
# topic = "us"

# Remove a default outlet this group never wants to see (only has an effect when base = "defaults"):
#
# [[remove]]
# kind = "feeds"
# name = "ZeroHedge"

# Relabel a default outlet for this group:
#
# [[override]]
# kind = "feeds"
# name = "Newsweek"
# lean = "right"
'''


def cmd_new(a):
    slug = slugify(a.name)
    d = group_dir(slug)
    if (d / "group.toml").exists():
        raise ValueError(f"groups/{slug}/group.toml already exists. Edit it, or pick another name.")
    d.mkdir(parents=True, exist_ok=True)
    existing = sorted(p.parent.name for p in GROUPS.glob("*/group.toml"))
    port = FIRST_PORT + len(existing)
    (d / "group.toml").write_text(TEMPLATE.format(name=a.name, name_q=wb._toml_str(a.name), slug=slug,
                                                  base="none" if a.empty else "defaults", port=port))
    print(f"Made groups/{slug}/group.toml")
    print(f"Next: add outlets with   .venv/bin/python groups.py add {slug} <a website or feed address>")
    print(f"Then: ./group.sh {slug}   (opens at http://localhost:{port})")


def cmd_add(a):
    import feedparser
    g = load(a.slug)
    cfg = tomllib.loads((ROOT / "config" / "sources.toml").read_text())
    cur, _ = apply(cfg, g)
    found = wb.discover(a.address, fetch, lambda b: feedparser.parse(b))
    if found["kind"] != "feeds":
        raise ValueError("Groups follow written outlets for now. For a YouTube channel, add it to the file by hand under [[channels]].")
    entry = wb.clean_entry("feeds", {"name": a.name or found["name"], "url": found["url"], "site": found["site"],
                                     "lean": a.lean, "topic": a.topic, "type": a.type or ""}, cur)
    block = "\n[[feeds]]\n" + "".join(f"{k} = {wb._toml_val(v)}\n" for k, v in entry.items())
    with open(group_dir(a.slug) / "group.toml", "a") as f:
        f.write(block)
    print(f"Added {entry['name']} ({entry['url']}) as {entry['lean']}, topic {entry['topic']}. Its latest items:")
    for it in found["items"][:3]:
        print("  -", it["title"])
    if found.get("others"):
        print("Other feeds on that site, if you want a different one:", ", ".join(found["others"][:3]))


def cmd_add_page(a):
    """Watch a page that has no feed. Shows what it finds first, so you can tell whether it will work."""
    import pages
    g = load(a.slug)
    wb.check_url_is_public(a.address)
    cfg = tomllib.loads((ROOT / "config" / "sources.toml").read_text())
    cur, _ = apply(cfg, g)
    html_text = pages._read(a.address)
    found = pages.extract(html_text, a.address, a.link_contains or "", a.min_words)
    if not found:
        raise ValueError("No headline-like links found on that page. Try --link-contains with part of the address that "
                         "news items share (for example /news/), or lower --min-words.")
    name = wb._clean_name(a.name or urllib.parse.urlsplit(a.address).hostname.removeprefix("www."))
    if any(e["name"] == name for e in cur["feeds"]) or any(e["url"] == a.address for e in cur["feeds"]):
        raise ValueError(f"There is already a source called {name} or with that address.")
    entry = {"name": name, "url": a.address, "method": "page", "lean": a.lean, "topic": a.topic}
    if a.link_contains: entry["link_contains"] = a.link_contains
    if a.min_words != 4: entry["min_words"] = a.min_words
    if a.type: entry["type"] = a.type
    with open(group_dir(a.slug) / "group.toml", "a") as f:
        f.write("\n[[feeds]]\n" + "".join(f"{k} = {wb._toml_val(v)}\n" for k, v in entry.items()))
    print(f"Watching {name} ({a.address}) as {a.lean}, topic {a.topic}. {len(found)} headline-like links found, for example:")
    for t, u in found[:5]:
        print("  -", t[:90])
    print("These are remembered as already there. Each new link that appears from now on will show up as a new item.")
    print("If the list above looks wrong (menus, or missing items), edit that entry's link_contains / min_words in group.toml.")


def cmd_list(a):
    rows = sorted(GROUPS.glob("*/group.toml"))
    if not rows:
        print("No groups yet. Make one with: .venv/bin/python groups.py new \"Its Name\"")
    for p in rows:
        g = load(p.parent.name)
        n = len(g["changes"]["feeds"])
        print(f"{p.parent.name:28} {g['name']}  (starts from {g['base']}, {n} added, port {port_for(p.parent.name, g)})")


def cmd_port(a):
    print(port_for(a.slug))


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("new"); p.add_argument("name"); p.add_argument("--empty", action="store_true"); p.set_defaults(fn=cmd_new)
    p = sub.add_parser("add"); p.add_argument("slug"); p.add_argument("address")
    p.add_argument("--lean", default="center", choices=wb.LEANS); p.add_argument("--topic", default="us", choices=wb.TOPICS)
    p.add_argument("--name"); p.add_argument("--type", choices=wb.TYPES); p.set_defaults(fn=cmd_add)
    p = sub.add_parser("add-page"); p.add_argument("slug"); p.add_argument("address")
    p.add_argument("--lean", default="center", choices=wb.LEANS); p.add_argument("--topic", default="us", choices=wb.TOPICS)
    p.add_argument("--name"); p.add_argument("--type", choices=wb.TYPES)
    p.add_argument("--link-contains", dest="link_contains"); p.add_argument("--min-words", dest="min_words", type=int, default=4)
    p.set_defaults(fn=cmd_add_page)
    p = sub.add_parser("list"); p.set_defaults(fn=cmd_list)
    p = sub.add_parser("port"); p.add_argument("slug"); p.set_defaults(fn=cmd_port)
    a = ap.parse_args()
    try:
        a.fn(a)
    except ValueError as ex:
        sys.exit(str(ex))


if __name__ == "__main__":
    main()
