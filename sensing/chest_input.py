"""Distance readings from the Arduino under the body.

One small interface for every way the data may arrive:

    chest.latest()   -> (distance_cm, timestamp) or None      timestamp: time.monotonic() seconds
    chest.drain()    -> the readings that arrived since the last drain, oldest first

Adapters:
    MessageChestInput   a JSON message {"type": "chest", "distance_cm": 12.3} from WebSocket or HTTP
    HttpChestListener   a tiny HTTP server: POST such a message to http://<laptop>:8766/
    HttpPollChestInput  asks an Arduino web server for its reading (GET URL), many times a second
    SerialChestInput    USB serial lines: one number, or one JSON object, per line
    FakeChestInput      for tests and for replaying recordings

The field names are here and nowhere else. NOT yet confirmed with the Arduino's author.
"""
import json
import sys
import threading
import time
from collections import deque

from . import config

MESSAGE_TYPE = "chest"
# field name -> factor that turns its value into centimetres
DISTANCE_FIELDS = (("distance_cm", 1.0), ("distance", 1.0), ("cm", 1.0), ("d", 1.0),
                   ("distance_mm", 0.1), ("mm", 0.1))
SERIAL_BAUD = 115200            # GUESSED: must match Serial.begin(...) in the Arduino sketch
HTTP_PORT = 8766
POLL_HZ = 25                    # GUESSED


def distance_from(data):
    """A dict (parsed JSON) or a number -> distance in cm, or None."""
    if isinstance(data, bool):
        return None
    if isinstance(data, (int, float)):
        return float(data)
    if isinstance(data, dict):
        if "type" in data and data["type"] != MESSAGE_TYPE:
            return None
        for name, factor in DISTANCE_FIELDS:
            value = data.get(name)
            if isinstance(value, (int, float)) and not isinstance(value, bool):
                return float(value) * factor
    return None


def parse_line(line):
    """One serial line -> distance in cm, or None. Accepts "12.3", "12.3 cm",
    "distance: 12.3" and a JSON object."""
    if isinstance(line, bytes):
        line = line.decode("utf-8", "replace")
    line = line.strip()
    if not line:
        return None
    if line.startswith("{"):
        try:
            return distance_from(json.loads(line))
        except ValueError:
            return None
    for token in line.replace(",", " ").replace(":", " ").replace("=", " ").split():
        try:
            return float(token)
        except ValueError:
            continue
    return None


class ChestInput:
    """Base: keeps the readings. Adapters call _add from their own thread."""

    def __init__(self):
        self._lock = threading.Lock()
        self._new = deque(maxlen=2000)
        self._latest = None
        self.count = 0

    def _add(self, distance_cm, timestamp=None):
        if distance_cm is None or distance_cm != distance_cm:      # None or NaN
            return
        reading = (float(distance_cm), time.monotonic() if timestamp is None else timestamp)
        with self._lock:
            self._latest = reading
            self._new.append(reading)
            self.count += 1

    def latest(self):
        return self._latest

    def drain(self):
        with self._lock:
            out = list(self._new)
            self._new.clear()
        return out

    def close(self):
        pass


class FakeChestInput(ChestInput):
    def push(self, distance_cm, timestamp=None):
        self._add(distance_cm, timestamp)


class MessageChestInput(ChestInput):
    """feed(dict) with every message that arrives; others than type "chest" are ignored."""

    def feed(self, data):
        if isinstance(data, dict) and data.get("type") == MESSAGE_TYPE:
            self._add(distance_from(data))


class HttpChestListener(MessageChestInput):
    """POST {"type": "chest", "distance_cm": 12.3} (or just a number) to this laptop."""

    def __init__(self, port=HTTP_PORT):
        super().__init__()
        from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
        chest = self

        class Handler(BaseHTTPRequestHandler):
            def do_POST(self):
                body = self.rfile.read(min(int(self.headers.get("Content-Length") or 0), 4096))
                chest._add(parse_line(body))
                self.send_response(204)
                self.end_headers()

            def log_message(self, *args):
                pass

        self._server = ThreadingHTTPServer(("0.0.0.0", port), Handler)
        threading.Thread(target=self._server.serve_forever, name="chest-http", daemon=True).start()

    def close(self):
        self._server.shutdown()


class _ThreadedInput(ChestInput):
    def __init__(self, name):
        super().__init__()
        self._running = True
        self._warned = False
        self._name = name

    def _start(self):
        threading.Thread(target=self._loop, name=self._name, daemon=True).start()

    def _loop(self):
        while self._running:
            try:
                self._step()
                self._warned = False
            except Exception as e:
                if not self._warned:
                    self._warned = True
                    print("%s: no Arduino data (%s). Carrying on with the band alone." % (self._name, e),
                          file=sys.stderr)
                time.sleep(0.5)

    def close(self):
        self._running = False


class HttpPollChestInput(_ThreadedInput):
    """For an Arduino that is a web server: GET its reading again and again."""

    def __init__(self, url):
        super().__init__("chest-poll")
        self.url = url
        self._start()

    def _step(self):
        import urllib.request
        started = time.monotonic()
        with urllib.request.urlopen(self.url, timeout=0.5) as response:
            self._add(parse_line(response.read(4096)))
        time.sleep(max(0.0, 1.0 / POLL_HZ - (time.monotonic() - started)))


class SerialChestInput(_ThreadedInput):
    """USB serial: one number or one JSON object per line. write(bytes) sends to the
    Arduino on the same port (used when the Arduino is also the hub)."""

    def __init__(self, port, baud=SERIAL_BAUD, opener=None):
        super().__init__("chest-serial")
        self._opener = opener or (lambda: __import__("serial").Serial(port, baud, timeout=0.2, write_timeout=0.5))
        self._serial = None
        self._write_lock = threading.Lock()
        self._start()

    def _step(self):
        if self._serial is None:
            self._serial = self._opener()
        try:
            line = self._serial.readline()
        except Exception:
            self._drop()
            raise
        if line:
            self._add(parse_line(line))

    def _drop(self):
        try:
            self._serial.close()
        except Exception:
            pass
        self._serial = None

    def write(self, data):
        with self._write_lock:
            if self._serial is None:
                raise OSError("the serial port is not open")
            self._serial.write(data)

    def close(self):
        super().close()
        if self._serial is not None:
            self._drop()


def from_spec(spec):
    """--arduino value -> (chest input, needs_ws_messages).
    serial:COM5 | serial:COM5:9600 | ws | http | http:8766 | poll:http://192.168.4.1/distance"""
    if not spec or spec == "none":
        return None, False
    kind, _, rest = spec.partition(":")
    if kind == "ws":
        return MessageChestInput(), True
    if kind == "http":
        return HttpChestListener(int(rest) if rest else HTTP_PORT), False
    if kind == "poll" and rest:
        return HttpPollChestInput(rest), False
    if kind == "serial" and rest:
        port, _, baud = rest.partition(":")
        return SerialChestInput(port, int(baud) if baud else SERIAL_BAUD), False
    raise SystemExit('--arduino: write serial:COM5, ws, http, or poll:http://ADDRESS/PATH (got "%s").' % spec)


class SpotDetector:
    """Arduino distances -> are the hands pressing on the spot right above it?
    On when the chest is pressed SPOT_PRESS_CM below its rest level; stays on SPOT_HOLD_S
    after the last press so it does not flicker between pushes.
    ponytail: rest = least-pressed reading of the last SPOT_REST_WINDOW_S, so leaning still
    for longer than that window reads as rest again. Fine for "place hands, then push"."""

    def __init__(self):
        self.readings = deque()     # (time, distance_cm)
        self.on_until = 0.0

    def add(self, distance_cm, now):
        self.readings.append((now, distance_cm))
        while self.readings[0][0] < now - config.SPOT_REST_WINDOW_S:
            self.readings.popleft()
        if self.press_cm() >= config.SPOT_PRESS_CM:
            self.on_until = now + config.SPOT_HOLD_S

    def press_cm(self):
        """How far the chest is pressed now, in cm (0 = at rest)."""
        ds = [d for _, d in self.readings]
        if config.CHEST_COMPRESSED_IS_SMALLER:
            return max(ds) - ds[-1]
        return ds[-1] - min(ds)

    def fresh(self, now):
        return bool(self.readings) and now - self.readings[-1][0] < config.CHEST_FRESH_S

    def on_target(self, now):
        return now < self.on_until
