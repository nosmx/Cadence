"""Cadence hub (Person 3). Message format: ../PROTOCOL.md

Run:  python hub/hub.py [port]      (default 8000; dashboard at http://localhost:8000)
Stdlib HTTP + Server-Sent Events. The only dependency is `anthropic`, used for
voice note -> timeline entry. Live cues never touch the LLM.
"""
import json, os, queue, socket, sys, threading, time, uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import anthropic

PHASES = {"check", "call", "position", "compress", "aed"}
QUALITIES = {"good", "harder", "softer", "faster", "slower"}
NUM = (int, float)
REQUIRED = {  # type -> {field: allowed types}
    "trigger": {"near": bool, "rssi": NUM},
    "compression": {"count": int, "rate_cpm": NUM, "quality": str, "confidence": NUM},
    "vitals": {"hr_bpm": NUM},
    "state": {"phase": str},
    "voice_event": {"text": str},
    "log_entry": {"id": str, "status": str},
}
MODEL = "claude-opus-5-5"
DASHBOARD = Path(__file__).with_name("dashboard.html")

# ponytail: no key in env -> no LLM, voice notes are logged as raw text (an `ant auth login`
# profile alone isn't detected; export ANTHROPIC_API_KEY)
HAS_KEY = os.environ.get("ANTHROPIC_API_KEY") or os.environ.get("ANTHROPIC_AUTH_TOKEN")
CLIENT = anthropic.Anthropic(timeout=20, max_retries=1) if HAS_KEY else None

lock = threading.Lock()
subs: list[queue.Queue] = []
latest: dict[str, dict] = {}
log: dict[str, dict] = {}
T0 = time.time()


def validate(m):
    if not isinstance(m, dict):
        return "body must be a JSON object"
    fields = REQUIRED.get(m.get("type"))
    if fields is None:
        return f"type must be one of {sorted(REQUIRED)}"
    for k, typ in fields.items():
        if not isinstance(m.get(k), typ) or (typ is not bool and isinstance(m.get(k), bool)):
            return f"{m['type']}.{k} missing or wrong type"
    if m["type"] == "state" and m["phase"] not in PHASES:
        return f"phase must be one of {sorted(PHASES)}"
    if m["type"] == "compression":
        if m["quality"] not in QUALITIES:
            return f"quality must be one of {sorted(QUALITIES)}"
        if not 0 <= m["confidence"] <= 1:
            return "confidence must be 0-1"
    if m["type"] == "log_entry":
        if m["status"] not in ("confirmed", "rejected"):
            return "clients may only set status to confirmed or rejected"
        if m["id"] not in log:
            return "unknown log_entry id"
    return None


def publish(m):
    m.setdefault("ts", int(time.time() * 1000))
    m.setdefault("src", "hub")
    m["t"] = round(time.time() - T0, 2)
    with lock:
        if m["type"] == "log_entry":
            log[m["id"]] = m
        else:
            latest[m["type"]] = m
        for q in subs:
            q.put(m)


def snapshot():
    with lock:
        return list(latest.values()) + list(log.values())


def summarize(text, phase):
    """Voice note -> {event, detail}. Falls back to the raw text on any failure."""
    raw = {"event": text[:60], "detail": ""}
    if CLIENT is None:
        return raw
    try:
        r = CLIENT.beta.messages.create(
            model=MODEL,
            max_tokens=16000,
            betas=["server-side-fallback-2026-07-01"],
            fallbacks="default",
            output_config={
                "effort": "low",
                "format": {"type": "json_schema", "schema": {
                    "type": "object",
                    "properties": {"event": {"type": "string"}, "detail": {"type": "string"}},
                    "required": ["event", "detail"],
                    "additionalProperties": False,
                }},
            },
            system=(
                "You log events for a CPR *training* session on a manikin. Turn the rescuer's "
                "spoken note into one timeline entry. event: at most 6 words naming what happened "
                "(e.g. '911 called', 'AED pads on', 'Rescuer swap'). detail: anything else they "
                "said, or ''. Use only what was said. Never add advice, diagnosis or inferences."
            ),
            messages=[{"role": "user", "content": f"Current phase: {phase}\nNote: {text}"}],
        )
        if r.stop_reason == "refusal":
            return raw
        return json.loads(next(b.text for b in r.content if b.type == "text"))
    except (anthropic.AnthropicError, StopIteration, json.JSONDecodeError) as e:
        print(f"[llm] fallback to raw text: {e!r}", file=sys.stderr)
        return raw


def on_voice(m):
    phase = latest.get("state", {}).get("phase", "?")
    entry = summarize(m["text"], phase)
    publish({"type": "log_entry", "id": uuid.uuid4().hex[:8], "status": "proposed",
             "event": entry["event"], "detail": entry["detail"], "said": m["text"], "at": m["t"]})


def handle(m):
    if m["type"] == "log_entry":  # confirm/reject: merge into the stored entry
        with lock:
            m = {**log[m["id"]], "status": m["status"], "src": m.get("src", "?"), "ts": m.get("ts")}
    publish(m)
    if m["type"] == "voice_event":
        threading.Thread(target=on_voice, args=(m,), daemon=True).start()


class Handler(BaseHTTPRequestHandler):
    def _head(self, code, ctype="application/json"):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.send_header("Cache-Control", "no-cache")
        self.end_headers()

    def _json(self, code, obj):
        self._head(code)
        self.wfile.write(json.dumps(obj).encode())

    def do_OPTIONS(self):
        self._head(204)

    def do_GET(self):
        if self.path == "/":
            self._head(200, "text/html; charset=utf-8")
            self.wfile.write(DASHBOARD.read_bytes())
        elif self.path == "/snapshot":
            self._json(200, snapshot())
        elif self.path == "/events":
            self._sse()
        else:
            self._json(404, {"error": "not found"})

    def do_POST(self):
        if self.path != "/msg":
            return self._json(404, {"error": "not found"})
        try:
            m = json.loads(self.rfile.read(int(self.headers.get("Content-Length", 0))) or b"null")
        except json.JSONDecodeError:
            return self._json(400, {"error": "invalid JSON"})
        err = validate(m)
        if err:
            return self._json(400, {"error": err})
        handle(m)
        self._json(200, {"ok": True})

    def _sse(self):
        q = queue.Queue()
        with lock:
            subs.append(q)
            backlog = list(latest.values()) + list(log.values())
        self._head(200, "text/event-stream")
        try:
            for m in backlog:
                self.wfile.write(f"data: {json.dumps(m)}\n\n".encode())
            self.wfile.flush()
            while True:
                try:
                    self.wfile.write(f"data: {json.dumps(q.get(timeout=15))}\n\n".encode())
                except queue.Empty:
                    self.wfile.write(b": ping\n\n")
                self.wfile.flush()
        except (BrokenPipeError, ConnectionResetError):
            pass
        finally:
            with lock:
                subs.remove(q)

    def log_message(self, fmt, *args):  # quiet: SSE + 2 msgs/s would flood the terminal
        if not args or not str(args[1]).startswith("2"):
            super().log_message(fmt, *args)


def lan_ip():
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
        try:
            s.connect(("10.255.255.255", 1))
            return s.getsockname()[0]
        except OSError:
            return "127.0.0.1"


def make_server(port):
    publish({"type": "state", "phase": "check"})
    srv = ThreadingHTTPServer(("0.0.0.0", port), Handler)  # LAN so the phone can reach it
    srv.daemon_threads = True
    return srv


if __name__ == "__main__":
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8000
    srv = make_server(port)
    print(f"Cadence hub on http://{lan_ip()}:{port}  (dashboard: http://localhost:{port})")
    srv.serve_forever()
