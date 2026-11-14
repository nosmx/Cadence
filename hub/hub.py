"""Cadence hub (Person 3). Message format: ../PROTOCOL.md

Run:  python hub/hub.py [port]      (default 8000; dashboard at http://localhost:8000)
Stdlib HTTP + Server-Sent Events. The only dependency is `openai`, used for
voice note -> timeline entry. Live cues never touch the LLM.
Needs OPENAI_API_KEY in ../.env (copy .env.example) or the environment.
"""
import json, os, queue, socket, sys, threading, time, uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import openai

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
MODEL = "gpt-5-mini"
ENV_FILE = Path(__file__).resolve().parent.parent / ".env"
DASHBOARD = Path(__file__).with_name("dashboard.html")

CLIENT = None  # set by make_client() at startup; tests leave it None (raw-text entries)
# Spend caps. Over a cap the note is still logged, as raw text (llm: false).
LLM_PER_MIN = 4          # calls in any 60 s window
LLM_PER_RUN = 40         # calls per hub run; restart the hub to reset
NOTE_MAX_CHARS = 300     # longer notes are cut before they reach the API
MAX_OUT_TOKENS = 1000    # includes reasoning tokens
llm_calls: list[float] = []

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


def llm_allowed():
    now = time.time()
    with lock:
        if len(llm_calls) >= LLM_PER_RUN or sum(now - t < 60 for t in llm_calls) >= LLM_PER_MIN:
            return False
        llm_calls.append(now)
        return True


def summarize(text, phase):
    """Voice note -> {event, detail}. Falls back to the raw text on any failure."""
    raw = {"event": text[:60], "detail": "", "llm": False}
    if CLIENT is None:
        return raw
    if not llm_allowed():
        print(f"[llm] rate limit ({LLM_PER_MIN}/min, {LLM_PER_RUN}/run): logged as raw text",
              file=sys.stderr)
        return raw
    text = text[:NOTE_MAX_CHARS]
    try:
        r = CLIENT.chat.completions.create(
            model=MODEL,
            reasoning_effort="low",
            max_completion_tokens=MAX_OUT_TOKENS,
            response_format={"type": "json_schema", "json_schema": {
                "name": "timeline_entry", "strict": True, "schema": {
                    "type": "object",
                    "properties": {"event": {"type": "string"}, "detail": {"type": "string"}},
                    "required": ["event", "detail"],
                    "additionalProperties": False,
                }}},
            messages=[
                {"role": "system", "content": (
                    "You log events for a CPR *training* session on a manikin. Turn the rescuer's "
                    "spoken note into one timeline entry. event: at most 6 words naming what happened "
                    "(e.g. '911 called', 'AED pads on', 'Rescuer swap'). detail: anything else they "
                    "said, or ''. Use only what was said. Never add advice, diagnosis or inferences.")},
                {"role": "user", "content": f"Current phase: {phase}\nNote: {text}"},
            ],
        )
        msg = r.choices[0].message
        if msg.refusal or not msg.content:
            return raw
        return json.loads(msg.content) | {"llm": True}
    except (openai.OpenAIError, json.JSONDecodeError) as e:
        # type and status only: OpenAI auth errors echo part of the key in their message
        print(f"[llm] fallback to raw text: {type(e).__name__} {getattr(e, 'status_code', '')}",
              file=sys.stderr)
        return raw


def on_voice(m):
    phase = latest.get("state", {}).get("phase", "?")
    entry = summarize(m["text"], phase)
    publish({"type": "log_entry", "id": uuid.uuid4().hex[:8], "status": "proposed", "confirmed": False,
             "event": entry["event"], "detail": entry["detail"], "llm": entry["llm"],
             "said": m["text"], "at": m["t"]})


def handle(m):
    if m["type"] == "log_entry":  # confirm/reject: merge into the stored entry
        with lock:
            m = {**log[m["id"]], "status": m["status"], "confirmed": m["status"] == "confirmed",
                 "src": m.get("src", "?"), "ts": m.get("ts")}
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


def make_client():
    """Load OPENAI_API_KEY from .env (real env vars win) or exit with a clear message. Never prints it."""
    if ENV_FILE.exists():
        for line in ENV_FILE.read_text().splitlines():
            k, sep, v = line.strip().partition("=")
            if sep and not k.startswith("#"):
                os.environ.setdefault(k.strip(), v.strip().strip("'\""))
    if not os.environ.get("OPENAI_API_KEY", "").strip() or os.environ["OPENAI_API_KEY"] == "your-key-here":
        sys.exit(f"OPENAI_API_KEY is missing. Put OPENAI_API_KEY=<your key> in {ENV_FILE} "
                 "(see .env.example) or export it, then start the hub again.")
    return openai.OpenAI(timeout=20, max_retries=0)  # no retries: each one costs


def make_server(port):
    publish({"type": "state", "phase": "check"})
    srv = ThreadingHTTPServer(("0.0.0.0", port), Handler)  # LAN so the phone can reach it
    srv.daemon_threads = True
    return srv


if __name__ == "__main__":
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8000
    CLIENT = make_client()
    srv = make_server(port)
    print(f"Cadence hub on http://{lan_ip()}:{port}  (dashboard: http://localhost:{port})")
    srv.serve_forever()
