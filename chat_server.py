"""The Ask page's helper: answers a question from the stories on this site with a small open model on this computer.

It listens on this computer only (127.0.0.1) unless started with --lan (for a phone on your Wi-Fi). It refuses any request
not addressed to it by name, and accepts browser requests only from this site's own page, so another web page you visit
cannot use it. With --lan it also refuses anyone who is not on a private network, and only accepts requests addressed by
IP address or a .local name, never by a web address, which is what DNS-rebinding tricks need. The model (llama.cpp's
llama-server, Qwen3 by default) is started when the first question arrives and stopped after a quiet spell, so it
holds no memory while you are not asking. Questions are not logged or sent anywhere. Start it with ./chat.sh
(or:  .venv/bin/python chat_server.py). How an answer is made: the top of chat.py.
"""
import atexit
import http.client
import ipaddress
import json
import os
import secrets
import select
import socket
import subprocess
import sys
import threading
import time
import tomllib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import chat

ROOT = Path(__file__).resolve().parent
MAX_BODY = 4_000
MAX_TOKENS = 220           # longest answer, in tokens (about 160 words)
ANSWER_TIMEOUT_S = 420     # stop writing after this long, however far it got
START_TIMEOUT_S = 240      # waiting for the model to load into memory
LLAMA_PORT_OFFSET = 1      # the model server listens on the helper's port + 1, on this computer only


def settings():
    return tomllib.loads((ROOT / "config" / "sources.toml").read_text()).get("settings", {})


LOCAL_NAMES = ("localhost", "127.0.0.1")


def split_host(host_header):
    """('name', 'port') from a Host header, or None when it is not that shape. IPv6 literals are not accepted."""
    name, sep, port = (host_header or "").rpartition(":")
    return (name, port) if sep and name and port.isdigit() and "[" not in name else None


HOME_NETWORKS = [ipaddress.ip_network(n) for n in ("10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16", "169.254.0.0/16")]


def home_network(ip):
    """Exactly the ranges routers hand out at home or at work. (Python's is_private also counts reserved and documentation ranges.)"""
    return ip.version == 4 and any(ip in n for n in HOME_NETWORKS)


def private_host(name):
    """A private-network IP address (192.168.x.x, 10.x.x.x, 172.16-31.x.x, 169.254.x.x) or a Bonjour .local name.
    A web address that merely resolves to a private IP does not count, which is what blocks DNS rebinding."""
    if name.endswith(".local") and len(name) > len(".local") and all(c.isalnum() or c in "-." for c in name):
        return True
    try:
        ip = ipaddress.ip_address(name)
    except ValueError:
        return False
    return home_network(ip)


def host_ok(host_header, port, lan=False):
    """Only requests addressed to this computer by name. This blocks DNS-rebinding tricks from other web pages.
    With lan on, this computer's address on your network (or its .local name) is accepted too."""
    parts = split_host(host_header)
    if not parts or parts[1] != str(port):
        return False
    return parts[0] in LOCAL_NAMES or (lan and private_host(parts[0]))


def client_ok(address, lan=False):
    """Who may connect. Always this computer; with lan on, also anything on a private network, never the open internet."""
    try:
        ip = ipaddress.ip_address(address)
    except ValueError:
        return False
    return ip.is_loopback or (lan and home_network(ip))


def origin_ok(origin, site_port, host_header=None, lan=False):
    """A browser always names the page a request comes from. Only this site's own pages are accepted: this computer's
    own names, and with lan on the same address the request was sent to (so a phone on the news site's address works).
    No origin at all means a command-line tool, not a web page."""
    if origin is None:
        return True
    if origin in {f"http://{n}:{site_port}" for n in LOCAL_NAMES}:
        return True
    parts = split_host(host_header)
    return bool(lan and parts and private_host(parts[0]) and origin == f"http://{parts[0]}:{site_port}")


class Model:
    """llama-server, started on the first question and stopped when idle."""

    def __init__(self, cfg, port):
        self.bin = ROOT / cfg.get("chat_server_bin", "tools/llama/llama-server")
        self.path = ROOT / cfg.get("chat_model", "tools/Qwen3-4B-Q4_K_M.gguf")
        self.threads = int(cfg.get("chat_threads", 2))
        self.idle_s = float(cfg.get("chat_idle_min", 10)) * 60
        self.port = port
        self.key = secrets.token_hex(16)   # so another program on this computer cannot use the model server by accident
        self.proc = None
        self.last_used = time.time()
        self.lock = threading.Lock()

    @property
    def name(self):
        return self.path.stem

    def installed(self):
        return self.bin.is_file() and self.path.is_file()

    def running(self):
        return self.proc is not None and self.proc.poll() is None

    def _headers(self):
        return {"Authorization": f"Bearer {self.key}", "Content-Type": "application/json"}

    def _healthy(self):
        try:
            c = http.client.HTTPConnection("127.0.0.1", self.port, timeout=2)
            c.request("GET", "/health", headers=self._headers())
            ok = c.getresponse().status == 200
            c.close()
            return ok
        except OSError:
            return False

    def ensure(self, status=lambda text: None, cancelled=lambda: False):
        """Make sure the model is loaded. The first question after a quiet spell waits here."""
        with self.lock:
            if self.running() and self._healthy():
                return
            if not self.running():
                status("Loading the model (only the first question after a quiet spell waits for this)")
                (ROOT / "logs").mkdir(exist_ok=True)
                log = open(ROOT / "logs" / "chat-model.log", "w")
                self.proc = subprocess.Popen(
                    [str(self.bin), "-m", str(self.path), "--host", "127.0.0.1", "--port", str(self.port), "-c", "2048",
                     "-t", str(self.threads), "-np", "1", "--api-key", self.key],
                    stdout=log, stderr=subprocess.STDOUT, cwd=str(self.bin.parent))
            deadline = time.time() + START_TIMEOUT_S
            while time.time() < deadline:
                if cancelled():
                    return
                if not self.running():
                    raise RuntimeError("The model program stopped while loading. See logs/chat-model.log.")
                if self._healthy():
                    return
                time.sleep(1)
            self.stop()
            raise RuntimeError("The model took too long to load. See logs/chat-model.log.")

    def stream(self, prompt, on_connect=lambda conn: None):
        """Yield the answer piece by piece. Closing the generator drops the connection, which stops the model writing.
        on_connect gets the connection so a watcher can cut it if the reader leaves while the model is still reading the prompt."""
        self.last_used = time.time()
        body = json.dumps({"prompt": prompt, "n_predict": MAX_TOKENS, "temperature": 0.2, "stream": True,
                           "cache_prompt": True, "stop": ["<|im_end|>"]})
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=ANSWER_TIMEOUT_S)
        started = time.time()
        try:
            conn.connect()
            on_connect(conn)
            conn.request("POST", "/completion", body=body, headers=self._headers())
            resp = conn.getresponse()
            if resp.status != 200:
                raise RuntimeError(f"The model program answered with an error ({resp.status}).")
            while True:
                line = resp.readline()
                if not line:
                    return
                line = line.decode("utf-8", "replace").strip()
                if not line.startswith("data:"):
                    continue
                data = json.loads(line[5:])
                if data.get("content"):
                    yield data["content"]
                if data.get("stop"):
                    return
                if time.time() - started > ANSWER_TIMEOUT_S:
                    return
        finally:
            conn.close()
            self.last_used = time.time()

    def stop(self):
        if self.proc is not None and self.proc.poll() is None:
            self.proc.terminate()
            try:
                self.proc.wait(10)
            except subprocess.TimeoutExpired:
                self.proc.kill()
        self.proc = None

    def watch_idle(self, busy):
        while True:
            time.sleep(30)
            if self.running() and not busy() and time.time() - self.last_used > self.idle_s:
                self.stop()


class App:
    def __init__(self, cfg, site, port, lan=False):
        self.cfg = cfg
        self.port = port
        self.lan = lan
        self.site_port = int(cfg.get("chat_site_port", 8765))
        self.data = Path(site) / "data" / "latest.json"
        self.system = chat.system_text()
        self.model = Model(cfg, port + LLAMA_PORT_OFFSET)
        self.busy = threading.Lock()
        self._stories, self._mtime = [], None

    def stories(self):
        """The last build's stories, re-read only when the file changes."""
        try:
            m = self.data.stat().st_mtime
        except OSError:
            return []
        if m != self._mtime:
            self._stories, self._mtime = chat.load_stories(self.data), m
        return self._stories


APP = None


class Handler(BaseHTTPRequestHandler):
    server_version = "TallyAsk"

    def log_message(self, fmt, *args):
        pass  # questions are never written to a log

    def _cors(self):
        origin = self.headers.get("Origin")
        if origin and origin_ok(origin, APP.site_port, self.headers.get("Host"), APP.lan):
            self.send_header("Access-Control-Allow-Origin", origin)
            self.send_header("Vary", "Origin")

    def _head(self, code, ctype="application/json; charset=utf-8", length=None):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        if length is not None:
            self.send_header("Content-Length", str(length))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        self._cors()
        self.end_headers()

    def _json(self, code, obj):
        body = json.dumps(obj).encode()
        self._head(code, length=len(body))
        self.wfile.write(body)

    def _event(self, obj):
        self.wfile.write(json.dumps(obj, ensure_ascii=False).encode() + b"\n")
        self.wfile.flush()

    def _guard(self):
        if not client_ok(self.client_address[0], APP.lan):
            self._json(403, {"error": "This helper only answers devices on your own network."})
            return False
        if not host_ok(self.headers.get("Host"), APP.port, APP.lan):
            self._json(403, {"error": "This helper only answers requests addressed to this computer (localhost)."})
            return False
        if not origin_ok(self.headers.get("Origin"), APP.site_port, self.headers.get("Host"), APP.lan):
            self._json(403, {"error": "Blocked: this request came from another web page."})
            return False
        return True

    def do_OPTIONS(self):
        if not self._guard():
            return
        self.send_response(204)
        self._cors()
        self.send_header("Access-Control-Allow-Methods", "GET, POST")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.send_header("Access-Control-Allow-Private-Network", "true")
        self.send_header("Access-Control-Max-Age", "600")
        self.end_headers()

    def do_GET(self):
        if not self._guard():
            return
        if self.path.split("?")[0] != "/api/status":
            return self._json(404, {"error": "Not found."})
        m = APP.model
        self._json(200, {"installed": m.installed(), "running": m.running(), "busy": APP.busy.locked(),
                         "model": m.name, "stories": len(APP.stories())})

    def do_POST(self):
        if not self._guard():
            return
        if self.path.split("?")[0] != "/api/chat":
            return self._json(404, {"error": "Not found."})
        try:
            n = int(self.headers.get("Content-Length") or 0)
            if n > MAX_BODY:
                return self._json(413, {"error": "That question is too long."})
            body = json.loads(self.rfile.read(n) or b"{}")
            q, write = body.get("question", ""), body.get("write") is True
            if not isinstance(q, str) or not q.strip():
                raise ValueError
        except (ValueError, AttributeError):
            return self._json(400, {"error": "Send a question."})
        if not APP.busy.acquire(blocking=False):
            return self._json(429, {"error": "Another question is being answered. Try again in a minute."})
        try:
            self._answer(q.strip()[:chat.MAX_QUESTION], write)
        except (BrokenPipeError, ConnectionResetError):
            pass  # the reader left; leaving the loop below already told the model to stop
        except Exception as ex:  # never show a stack trace to the page
            print(f"ask: {type(ex).__name__}: {ex}", file=sys.stderr)
            try:
                self._event({"type": "error", "text": "Something went wrong. Check the terminal where the helper is running."})
            except OSError:
                pass
        finally:
            APP.busy.release()

    def _watch_reader(self, done, held):
        """Notice when the page closes the connection (Stop, or leaving the page) and cut the model's connection at once,
        so the model stops and the next question is not refused as busy. Writing alone would only notice after the first word."""
        while not done.is_set():
            try:
                ready, _, _ = select.select([self.connection], [], [], 0.5)
                if ready and self.connection.recv(1, socket.MSG_PEEK) == b"":
                    break
            except (OSError, ValueError):
                break
        else:
            return
        held["gone"] = True
        conn = held.get("conn")
        if conn is not None and conn.sock is not None:
            try:
                conn.sock.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass

    def _answer(self, question, write=False):
        self._head(200, "application/x-ndjson; charset=utf-8")
        if write:  # the reader pressed "compare how each side worded it": the rows are already on the page, so only the model's text is sent
            prompt = chat.write_prompt(question, APP.stories(), APP.system)
            if prompt is None:
                self._event({"type": "error", "text": "That story is no longer in the latest build. Ask again."})
                return
        else:
            prep = chat.prepare(question, APP.stories(), APP.system)
            self._event({"type": "sources", "mode": prep["mode"], "stories": prep["sources"], "model": prep.get("model") or APP.model.name,
                         "note": prep.get("note"), "can_write": bool(prep.get("can_write")), "show_first": bool(prep.get("show_first"))})
            if prep["prompt"] is None:  # a lookup counted by code, a stored summary, or nothing matched: the model is not needed
                self._event({"type": "text", "text": prep["text"] or chat.NOT_COVERED})
                return self._event({"type": "done"})
            prompt = prep["prompt"]
        if not APP.model.installed():
            return self._event({"type": "error", "text": "The model is not installed yet. The README's \"summaries written on your own computer\" "
                                "section shows how; the Ask page needs the same two files."})
        done, held = threading.Event(), {}
        threading.Thread(target=self._watch_reader, args=(done, held), daemon=True).start()
        try:
            try:
                APP.model.ensure(lambda t: self._event({"type": "status", "text": t}), lambda: held.get("gone", False))
            except RuntimeError as ex:
                return self._event({"type": "error", "text": str(ex)})
            if held.get("gone"):
                return
            self._event({"type": "status", "text": "Reading the stories"})
            for piece in APP.model.stream(prompt, lambda c: held.__setitem__("conn", c)):
                self._event({"type": "text", "text": piece})
            if not held.get("gone"):
                self._event({"type": "done"})
        finally:
            done.set()


def main(argv):
    global APP
    cfg = settings()
    port, site = int(cfg.get("chat_port", 8770)), ROOT / "site"
    args = list(argv)
    if "--port" in args:
        port = int(args[args.index("--port") + 1])
    if "--site" in args:
        site = Path(args[args.index("--site") + 1]).resolve()
    if "--site-port" in args:  # the port the news site is served on, if it is not the one in config/sources.toml
        cfg = dict(cfg, chat_site_port=int(args[args.index("--site-port") + 1]))
    lan = "--lan" in args
    APP = App(cfg, site, port, lan)
    atexit.register(APP.model.stop)
    threading.Thread(target=APP.model.watch_idle, args=(APP.busy.locked,), daemon=True).start()
    server = ThreadingHTTPServer(("0.0.0.0" if lan else "127.0.0.1", port), Handler)  # this computer only, unless --lan
    where = ("this computer and devices on your private network (a phone on your Wi-Fi). Anyone on this Wi-Fi can ask it questions while it runs,\n"
             "so don't use --lan on public Wi-Fi" if lan else "this computer only")
    print(f"\nAsk helper: http://localhost:{port}   ({where}; Ctrl+C to stop)\n"
          f"Model: {APP.model.name} ({'installed' if APP.model.installed() else 'NOT installed, see the README'}). "
          f"It loads on the first question and unloads after {int(APP.model.idle_s // 60)} quiet minutes.\n"
          f"Questions are not logged. Open the Ask page on the news site at http://localhost:{APP.site_port}/chat.html\n")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopped.")


if __name__ == "__main__":
    main(sys.argv[1:])
