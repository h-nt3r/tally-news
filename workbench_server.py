"""The workbench's local web server: your own copy of the news page plus a Manage sources page that can change it.

It listens on this Mac only (127.0.0.1), refuses any request that is not addressed to this Mac by name, and needs a
secret token for every change, so a web page you visit cannot edit your list. Nothing here is reachable from your
phone or your Wi-Fi. Start it with:  .venv/bin/python workbench.py serve
"""
import json
import mimetypes
import subprocess
import sys
import threading
import time
import tomllib
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import feedparser

import workbench as wb

ROOT, WORK = wb.ROOT, wb.WORK
PORT = 8766
UA = {"User-Agent": "Mozilla/5.0 (compatible; TallyNewsWorkbench/1.0)"}
MAX_BODY = 20_000
MAX_FETCH = 2_000_000


class SafeRedirects(urllib.request.HTTPRedirectHandler):
    """Every hop of a redirect has to be a public address too, not just the first."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        wb.check_url_is_public(newurl)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


OPENER = urllib.request.build_opener(SafeRedirects)


def fetch(url):
    wb.check_url_is_public(url)
    with OPENER.open(urllib.request.Request(url, headers=UA), timeout=15) as r:
        return r.read(MAX_FETCH)


class Shared:
    """What the handlers share: the token, the lock around the changes file, and the build in progress."""

    def __init__(self):
        self.token = wb.make_token()
        self.lock = threading.Lock()
        self.proc = None
        self.dirty = False
        self.last_error = ""
        self.log = WORK / "build.log"

    def building(self):
        if self.proc is not None and self.proc.poll() is not None:
            if self.proc.returncode != 0:
                lines = self.log.read_text().strip().splitlines() if self.log.exists() else []
                self.last_error = " ".join(lines[-3:])[:300] or "The build failed."
            else:
                self.last_error = ""
            self.proc = None
        return self.proc is not None

    def start_build(self):
        if self.building():
            return False
        WORK.mkdir(exist_ok=True)
        self.dirty = False  # edits made from here on are not in this build
        with open(self.log, "w") as f:
            self.proc = subprocess.Popen([sys.executable, "build.py", "--workbench"], cwd=ROOT, stdout=f, stderr=subprocess.STDOUT)
        return True


SH = Shared()


def defaults_cfg():
    return tomllib.loads((ROOT / "config" / "sources.toml").read_text())


def state():
    changes = wb.load_changes()
    out = wb.describe(defaults_cfg(), changes)
    site_index = WORK / "site" / "index.html"
    out.update({"building": SH.building(), "dirty": SH.dirty, "error": SH.last_error,
                "built_at": int(site_index.stat().st_mtime) if site_index.exists() else 0,
                "kinds": wb.KIND_WORD, "types": list(wb.TYPES)})
    return out


def mutate(fn):
    """Read the changes, apply one edit, save. Everything under one lock so two clicks cannot clobber each other."""
    with SH.lock:
        changes = wb.load_changes()
        fn(changes)
        wb.save_changes(changes)
        SH.dirty = True


def handle_post(path, data):
    d = defaults_cfg()
    if path == "/api/remove":
        mutate(lambda c: wb.remove_source(c, data.get("kind"), data.get("name"), d))
    elif path == "/api/restore":
        mutate(lambda c: wb.restore_source(c, data.get("kind"), data.get("name")))
    elif path == "/api/restore_all":
        mutate(lambda c: c.__setitem__("remove", []))
    elif path == "/api/reset":
        with SH.lock:
            wb.save_changes(wb.empty_changes())
            SH.dirty = True
    elif path == "/api/set":
        mutate(lambda c: wb.set_label(c, data.get("kind"), data.get("name"), d, data.get("field"), data.get("value", "")))
    elif path == "/api/add":
        def add(c):
            both = {k: d[k] + c[k] for k in wb.KINDS}  # a new source must not clash with a default or with one you added
            c[data.get("kind")].append(wb.clean_entry(data.get("kind"), data, both))
        mutate(add)
    elif path == "/api/discover":
        return wb.discover(str(data.get("url", "")), fetch, feedparser.parse)
    elif path == "/api/rebuild":
        return {"started": SH.start_build()}
    else:
        raise LookupError
    return state()


class Handler(BaseHTTPRequestHandler):
    server_version = "TallyWorkbench"

    def log_message(self, fmt, *args):
        pass

    def _send(self, code, body, ctype="application/json; charset=utf-8"):
        if isinstance(body, (dict, list)):
            body = json.dumps(body).encode()
        elif isinstance(body, str):
            body = body.encode()
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        self.end_headers()
        self.wfile.write(body)

    def _guard(self):
        if not wb.host_ok(self.headers.get("Host"), self.server.server_address[1]):
            self._send(403, {"error": "This server only answers requests addressed to this Mac (localhost)."})
            return False
        return True

    def do_GET(self):
        if not self._guard():
            return
        path = self.path.split("?")[0].split("#")[0]
        if path == "/api/state":
            return self._send(200, state())
        site = WORK / "site"
        if not (site / "index.html").exists():
            return self._send(200, "<!doctype html><meta charset=utf-8><title>Building</title><body style='font:16px system-ui;margin:2rem'>"
                              "<h1>Building your workbench for the first time</h1><p>This takes about a minute. Refresh in a moment.</p>", "text/html; charset=utf-8")
        rel = "index.html" if path in ("", "/") else path.lstrip("/")
        target = (site / rel).resolve()
        if site.resolve() not in target.parents and target != site.resolve():
            return self._send(404, {"error": "not found"})
        if target.is_dir():
            target = target / "index.html"
        if not target.is_file():
            return self._send(404, "Not found", "text/plain; charset=utf-8")
        data = target.read_bytes()
        if target.name == "manage.html":
            data = data.replace(b"__TOKEN__", SH.token.encode())
        ctype = mimetypes.guess_type(str(target))[0] or "application/octet-stream"
        if ctype.startswith("text/") or ctype in ("application/javascript", "application/json"):
            ctype += "; charset=utf-8"
        self._send(200, data, ctype)

    def do_POST(self):
        if not self._guard():
            return
        port = self.server.server_address[1]
        if not wb.origin_ok(self.headers.get("Origin"), port):
            return self._send(403, {"error": "Blocked: this request came from another web page."})
        if self.headers.get("X-Workbench-Token") != SH.token:
            return self._send(403, {"error": "Missing or wrong token. Reload the Manage page."})
        try:
            n = int(self.headers.get("Content-Length") or 0)
            if n > MAX_BODY:
                return self._send(413, {"error": "Request too large."})
            data = json.loads(self.rfile.read(n) or b"{}")
            if not isinstance(data, dict):
                raise ValueError("Bad request.")
            self._send(200, handle_post(self.path.split("?")[0], data))
        except LookupError:
            self._send(404, {"error": "Unknown action."})
        except ValueError as ex:
            self._send(400, {"error": str(ex)})
        except Exception as ex:  # never show a stack trace to the page
            print(f"workbench: {type(ex).__name__}: {ex}", file=sys.stderr)
            self._send(500, {"error": "Something went wrong. Check the terminal where the workbench is running."})


class ReadOnlyHandler(BaseHTTPRequestHandler):
    """The phone view: only your built pages, nothing that can change anything. No API, no token, GET and HEAD only."""
    server_version = "TallyWorkbenchView"

    def log_message(self, fmt, *args):
        pass

    def _serve(self, head):
        site = (WORK / "site").resolve()
        path = self.path.split("?")[0].split("#")[0]
        if path.startswith("/api/"):
            return self._plain(404, "Not found")
        rel = "index.html" if path in ("", "/") else path.lstrip("/")
        if rel == "manage.html":
            rel = "manage-readonly.html"  # the editing page is for the Mac; the phone gets a note instead
        target = (site / rel).resolve()
        if target.is_dir():
            target = target / "index.html"
        if not target.is_file() or (site not in target.parents):
            return self._plain(404, "Not found")
        data = target.read_bytes()
        ctype = mimetypes.guess_type(str(target))[0] or "application/octet-stream"
        if ctype.startswith("text/") or ctype in ("application/javascript", "application/json"):
            ctype += "; charset=utf-8"
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        self.end_headers()
        if not head:
            self.wfile.write(data)

    def _plain(self, code, text):
        body = text.encode()
        self.send_response(code)
        self.send_header("Content-Type", "text/plain; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        self._serve(False)

    def do_HEAD(self):
        self._serve(True)

    def _no(self):
        self._plain(405, "This is the read-only view. Edit sources on the Mac.")

    do_POST = do_PUT = do_DELETE = do_PATCH = _no


def lan_address():
    """This Mac's address on the local network (no traffic is sent; it only asks the OS which interface it would use)."""
    import socket
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.connect(("10.255.255.255", 1))
            return s.getsockname()[0]
    except OSError:
        return "<your-mac-ip>"


def rebuild_loop(every, skip_first=False):
    """Rebuild whenever the page is older than `every` seconds. Checking once a minute (instead of sleeping the whole
    interval) keeps it on time after the Mac wakes from sleep or the job restarts."""
    index = WORK / "site" / "index.html"
    if skip_first:  # started with --no-build: leave what is there alone until it is due
        time.sleep(every)
    while True:
        age = time.time() - index.stat().st_mtime if index.exists() else every
        if age >= every:
            SH.start_build()
        time.sleep(60)


def main(argv):
    port, every, build_first, lan, lan_port = PORT, 1200, True, False, PORT + 1
    args = list(argv)
    if not args or args[0] != "serve":
        sys.exit("Usage: python workbench.py serve [--lan] [--port N] [--every SECONDS] [--no-build]")
    if "--port" in args:
        port = int(args[args.index("--port") + 1])
    if "--every" in args:
        every = int(args[args.index("--every") + 1])
    if "--no-build" in args:
        build_first = False
    if "--lan" in args:
        lan = True
    server = ThreadingHTTPServer(("127.0.0.1", port), Handler)  # this Mac only
    threading.Thread(target=rebuild_loop, args=(every, not build_first), daemon=True).start()
    if lan:  # a second, read-only server for the phone; the editing server above stays on this Mac
        view = ThreadingHTTPServer(("0.0.0.0", lan_port), ReadOnlyHandler)
        threading.Thread(target=view.serve_forever, daemon=True).start()
        print(f"\nOpen this on your phone (same Wi-Fi):  http://{lan_address()}:{lan_port}\n"
              f"It is read-only: pages only, nothing can be changed from it. Anyone on this Wi-Fi can open it while this runs,\n"
              f"so don't use it on public Wi-Fi. Editing stays on this Mac.")
    print(f"\nWorkbench: http://localhost:{port}   (this Mac only; Ctrl+C to stop)\n"
          f"Manage sources: http://localhost:{port}/manage.html\n"
          f"It rebuilds every {every // 60} minutes while it runs.\n")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopped.")


if __name__ == "__main__":
    main(sys.argv[1:])
