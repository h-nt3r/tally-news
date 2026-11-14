"""Publish the finished site/ folder to a static host (a Git repository served by GitHub Pages).

Off unless a local file named publish.local.toml exists (it is not saved to git, so a fork never publishes by accident):

    repo = "https://github.com/h-nt3r/tally-news-site.git"   # where the pages are pushed
    branch = "main"
    min_minutes = 10            # never push more often than this (Pages builds are capped at about 10 an hour)
    exclude_thumbnails = false  # true leaves out the preview frames and thumbnails stored in site/clips/

What it does, in order: copy site/ into a working clone under cache/publish/, add .nojekyll, keep a single commit
(amended each time, force-pushed, so the repository never accumulates history), and push. It runs at the end of
build.py, never stops the build, and says in the build log what happened. It only sends the finished page: no
history/, cache/, logs/, settings or tokens ever sit in site/.
"""
import json
import re
import shutil
import subprocess
import time
import tomllib
from pathlib import Path

ROOT = Path(__file__).parent
CONFIG = ROOT / "publish.local.toml"
WORK = ROOT / "cache" / "publish"
STATE = ROOT / "cache" / "publish.json"
GH = shutil.which("gh") or "/usr/local/bin/gh"  # GitHub's own command-line tool supplies the stored login


def _git(*args, check=True):
    # the credential helper is the stored GitHub login; nothing is read from or written to a file here
    base = ["git", "-C", str(WORK), "-c", "http.postBuffer=524288000", "-c", "credential.helper=", "-c", f"credential.helper=!{GH} auth git-credential"]
    return subprocess.run(base + list(args), capture_output=True, text=True, check=check, timeout=180)


def _state():
    try:
        return json.loads(STATE.read_text())
    except Exception:
        return {}


def _save(**kw):
    STATE.parent.mkdir(exist_ok=True)
    STATE.write_text(json.dumps({**_state(), **kw}))


def run(site_dir):
    """Returns a one-line report, or None when publishing is not set up. Never raises."""
    if not CONFIG.exists():
        return None
    try:
        cfg = tomllib.loads(CONFIG.read_text())
        repo, branch = cfg["repo"], cfg.get("branch", "main")
        wait = int(cfg.get("min_minutes", 10)) * 60
        st = _state()
        ago = time.time() - st.get("at", 0)
        if ago < wait:
            return f"publish: skipped (last push {int(ago // 60)} min ago; at most one every {wait // 60} min)"
        if not (Path(site_dir) / "index.html").exists():
            return "publish: skipped (no index.html to send)"
        WORK.mkdir(parents=True, exist_ok=True)
        if not (WORK / ".git").exists():
            subprocess.run(["git", "init", "-q", "-b", branch, str(WORK)], check=True)
            _git("config", "user.name", "tally-news build")
            _git("config", "user.email", "tally-news-build@users.noreply.github.com")
        _git("remote", "remove", "origin", check=False)
        _git("remote", "add", "origin", repo)
        # a copy of the finished site; the working clone keeps only its .git
        for p in WORK.iterdir():
            if p.name != ".git":
                shutil.rmtree(p) if p.is_dir() else p.unlink()
        skip = {"README.md"}  # site/README.md is a note for people editing this project, not part of the page
        for p in Path(site_dir).iterdir():
            if p.name in skip or p.name.endswith(".tmp"):
                continue
            if p.name == "clips" and cfg.get("exclude_thumbnails", False):
                continue
            shutil.copytree(p, WORK / p.name) if p.is_dir() else shutil.copy2(p, WORK / p.name)
        if cfg.get("exclude_thumbnails", False):  # drop the image tags that pointed into clips/
            for h in WORK.rglob("*.html"):
                h.write_text(re.sub(r'<img\b[^>]*\bsrc="(?:\.\./)?clips/[^"]*"[^>]*>', "", h.read_text()))
        (WORK / ".nojekyll").write_text("")  # serve the files as they are
        _git("add", "-A")
        msg = "Published " + time.strftime("%Y-%m-%d %H:%M UTC", time.gmtime())
        has_commit = _git("rev-parse", "--verify", "-q", "HEAD", check=False).returncode == 0
        _git("commit", "-q", "-m", msg, *(["--amend"] if has_commit else []), "--allow-empty")
        out = _git("push", "--force", "-q", "origin", f"HEAD:{branch}", check=False)
        if out.returncode != 0:
            _save(at=time.time(), error=out.stderr.strip()[-200:])  # back off for the same interval, then try again
            return f"publish: push failed ({out.stderr.strip().splitlines()[-1][:120] if out.stderr.strip() else 'unknown'})"
        _save(at=time.time(), error="")
        return f"publish: pushed {sum(1 for _ in WORK.rglob('*') if _.is_file() and '.git' not in _.parts)} files to {repo}"
    except Exception as ex:
        try:
            _save(at=time.time(), error=str(ex)[:200])
        except Exception:
            pass
        return f"publish: skipped ({str(ex)[:120]})"
