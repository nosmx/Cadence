"""Cadence hub (Person 3). Message format: ../PROTOCOL.md

Run:  python hub/hub.py [port]      (default 8000; dashboard at http://localhost:8000)
Stdlib HTTP + Server-Sent Events (dashboard) + WebSocket (glasses app). The only
dependency is `openai`, used for voice note -> timeline entry. Live cues never touch the LLM.
Needs OPENAI_API_KEY in ../.env (copy .env.example) or the environment.
"""
import base64, hashlib, json, os, queue, socket, sys, threading, time, uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import openai

PHASES = {"check", "call", "position", "compress", "aed"}
DIRECTIONS = {"head", "feet", "left", "right", None}
CONFIRMS = {"hands_placed": None, "start_compressions": "compress", "end_session": "check"}  # -> phase
TRENDS = {"closer", "farther", "steady", None}
NUM = (int, float)
NULL_NUM = (int, float, type(None))
REQUIRED = {  # type -> {field: allowed types}. Matches glasses-app/src/protocol.ts
    "placement": {"on_target": bool, "signal": NUM},
    # The band sends null rate (first push after a pause) and null depth/quality; the glasses
    # skip those, the dashboard shows "?". Extra band fields (count, recoil_ok...) pass through.
    "compression": {"rate_cpm": NULL_NUM, "depth_cm": NULL_NUM, "quality": (str, type(None)), "confidence": NUM},
    "vitals": {"hr_bpm": NUM},
    "state": {"phase": str},
    "voice_event": {"phrase": str},
    "confirm": {"what": str},
    "log_entry": {"id": str, "status": str},
    "status": {},     # band: connected, battery_percent, arduino_ok... (sensing/messages.py)
    "heartbeat": {},  # band, 1/s: latest compression fields + status fields
}
WS_GUID = "258EAFA5-E914-47DA-95CA-C5AB0DC85B11"
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
        if k not in m or not isinstance(m[k], typ) or (typ is not bool and isinstance(m[k], bool)):
            return f"{m['type']}.{k} missing or wrong type"
    if m["type"] == "state" and m["phase"] not in PHASES:
        return f"phase must be one of {sorted(PHASES)}"
    isnum = lambda v: isinstance(v, NUM) and not isinstance(v, bool)
    if m["type"] == "compression":
        if not 0 <= m["confidence"] <= 1:
            return "confidence must be 0-1"
        if "pressure" in m and not (isnum(m["pressure"]) and 0 <= m["pressure"] <= 1):
            return "pressure must be 0-1"
    if m["type"] == "placement":
        if not 0 <= m["signal"] <= 1:
            return "signal must be 0-1"
        if m.get("direction") not in DIRECTIONS:
            return "direction must be head, feet, left, right or null"
        if m.get("distance_cm") is not None and not isnum(m["distance_cm"]):
            return "distance_cm must be a number or null"
        if m.get("trend") not in TRENDS:
            return "trend must be closer, farther, steady or null"
    if m["type"] == "confirm" and m["what"] not in CONFIRMS:
        return f"what must be one of {sorted(CONFIRMS)}"
    if m["type"] == "log_entry":
        if m["status"] not in ("confirmed", "rejected"):
            return "clients may only set status to confirmed or rejected"
        if m["id"] not in log:
            return "unknown log_entry id"
    return None


def publish(m):
    m.setdefault("ts", int(time.time() * 1000))
    m.setdefault("source", "hub")
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
    if CLIENT is None or len(text.split()) < 2:  # one word ("ready") is a command, not a note
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
    entry = summarize(m["phrase"], phase)
    publish({"type": "log_entry", "id": uuid.uuid4().hex[:8], "status": "proposed", "confirmed": False,
             "event": entry["event"], "detail": entry["detail"], "llm": entry["llm"],
             "said": m["phrase"], "at": m["t"]})


def handle(m):
    if m["type"] == "log_entry":  # confirm/reject: merge into the stored entry
        with lock:
            m = {**log[m["id"]], "status": m["status"], "confirmed": m["status"] == "confirmed",
                 "source": m.get("source", "?"), "ts": m.get("ts")}
    publish(m)
    if m["type"] == "confirm" and CONFIRMS[m["what"]]:
        publish({"type": "state", "phase": CONFIRMS[m["what"]]})
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
        if self.headers.get("Upgrade", "").lower() == "websocket":  # any path: glasses use ?ws=ws://ip:8000
            self._ws()
        elif self.path == "/":
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

    def _ws(self):
        """WebSocket for the glasses: live messages out, voice_event/confirm in. Live only, no
        backlog replay: a replayed compression would look fresh to the glasses' staleness check."""
        key = self.headers.get("Sec-WebSocket-Key", "")
        accept = base64.b64encode(hashlib.sha1((key + WS_GUID).encode()).digest()).decode()
        self.wfile.write(("HTTP/1.1 101 Switching Protocols\r\nUpgrade: websocket\r\n"
                          f"Connection: Upgrade\r\nSec-WebSocket-Accept: {accept}\r\n\r\n").encode())
        self.wfile.flush()
        q = queue.Queue()
        with lock:
            subs.append(q)

        def reader():  # client -> hub; puts None on close so the writer loop ends
            try:
                while (frame := ws_read(self.rfile)) is not None:
                    op, data = frame
                    if op == 8:
                        break
                    if op == 1:
                        try:
                            m = json.loads(data)
                        except json.JSONDecodeError:
                            continue
                        err = validate(m)
                        if err:
                            print(f"[ws] dropped: {err}", file=sys.stderr)
                        else:
                            handle(m)
            except OSError:
                pass
            q.put(None)

        threading.Thread(target=reader, daemon=True).start()
        try:
            while True:
                try:
                    m = q.get(timeout=15)
                except queue.Empty:
                    self.wfile.write(ws_frame(b"", 0x9))  # ping keeps the WebView socket alive
                else:
                    if m is None:
                        break
                    self.wfile.write(ws_frame(json.dumps(m).encode()))
                self.wfile.flush()
        except OSError:
            pass
        finally:
            with lock:
                subs.remove(q)
            self.close_connection = True

    def log_message(self, fmt, *args):  # quiet: SSE + 2 msgs/s would flood the terminal
        if not args or not str(args[1]).startswith("2"):
            super().log_message(fmt, *args)


def ws_frame(payload, op=0x1):
    n = len(payload)
    size = bytes([n]) if n < 126 else bytes([126]) + n.to_bytes(2, "big") if n < 65536 else bytes([127]) + n.to_bytes(8, "big")
    return bytes([0x80 | op]) + size + payload


def ws_read(rfile):
    """One client frame -> (opcode, payload), or None when the socket closes.
    ponytail: no fragmented frames; the glasses send one small JSON object per frame."""
    head = rfile.read(2)
    if len(head) < 2:
        return None
    n = head[1] & 0x7F
    if n == 126:
        n = int.from_bytes(rfile.read(2), "big")
    elif n == 127:
        n = int.from_bytes(rfile.read(8), "big")
    if n > 65536:
        return None  # nothing legitimate is this big; drop the client
    mask = rfile.read(4) if head[1] & 0x80 else b"\0\0\0\0"
    data = rfile.read(n)
    return head[0] & 0x0F, bytes(b ^ mask[i % 4] for i, b in enumerate(data))


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
    print(f"Cadence hub on http://{lan_ip()}:{port}  (dashboard: http://localhost:{port}, "
          f"glasses: ?ws=ws://{lan_ip()}:{port})")
    srv.serve_forever()
