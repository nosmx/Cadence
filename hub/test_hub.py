"""Run: python hub/test_hub.py  — starts the hub on a spare port, checks the message flow."""
import base64, json, os, socket, threading, time, urllib.error, urllib.request

import hub

hub.CLIENT = None  # no LLM in tests: voice notes fall back to raw text
srv = hub.make_server(0)
threading.Thread(target=srv.serve_forever, daemon=True).start()
URL = f"http://127.0.0.1:{srv.server_address[1]}"


def post(m):
    req = urllib.request.Request(URL + "/msg", json.dumps(m).encode(), {"Content-Type": "application/json"})
    try:
        return urllib.request.urlopen(req).status
    except urllib.error.HTTPError as e:
        return e.code


def snap():
    return json.loads(urllib.request.urlopen(URL + "/snapshot").read())


ok = {"type": "compression", "ts": 1, "source": "fake", "rate_cpm": 110,
      "depth_cm": 5.2, "pressure": 0.7, "quality": "good", "confidence": 0.9}
assert post(ok) == 200
assert post({**ok, "confidence": 2}) == 400
assert post({**ok, "pressure": 1.5}) == 400
assert post({**ok, "depth_cm": None}) == 400  # glasses need a number
place = {"type": "placement", "on_target": False, "distance_cm": 6, "direction": "head", "signal": 0.8}
assert post(place) == 200
assert post({**place, "distance_cm": None, "direction": None}) == 200
assert post({**place, "on_target": 1}) == 400  # must be a bool
assert post({**place, "direction": "up"}) == 400
assert post({"type": "confirm", "what": "nope"}) == 400
assert post({"type": "nope"}) == 400
assert post({"type": "state", "phase": "compress"}) == 200
assert {m["type"]: m for m in snap()}["state"]["phase"] == "compress"

# SSE: a subscriber gets the backlog then live messages
stream = urllib.request.urlopen(URL + "/events")
assert post({"type": "vitals", "hr_bpm": 120}) == 200
seen = []
while not any(m["type"] == "vitals" for m in seen):
    line = stream.readline().decode().strip()
    if line.startswith("data: "):
        seen.append(json.loads(line[6:]))
assert {"state", "compression", "vitals"} <= {m["type"] for m in seen}

# voice note -> proposed entry -> confirmed
assert post({"type": "voice_event", "phrase": "AED arrived"}) == 200
for _ in range(50):
    entries = [m for m in snap() if m["type"] == "log_entry"]
    if entries: break
    time.sleep(0.05)
e = entries[0]
assert e["status"] == "proposed" and e["confirmed"] is False and e["llm"] is False
assert e["event"] == "AED arrived" and e["said"] == "AED arrived" and e["at"] > 0
assert post({"type": "log_entry", "id": "missing", "status": "confirmed"}) == 400
assert post({"type": "log_entry", "id": e["id"], "status": "proposed"}) == 400
assert post({"type": "log_entry", "id": e["id"], "status": "confirmed"}) == 200
e2 = next(m for m in snap() if m["type"] == "log_entry")
assert e2["status"] == "confirmed" and e2["confirmed"] is True and e2["event"] == "AED arrived"

# WebSocket (glasses): handshake, hub -> glasses, glasses -> hub
port = srv.server_address[1]
ws = socket.create_connection(("127.0.0.1", port), timeout=3)
key = base64.b64encode(os.urandom(16)).decode()
ws.sendall(f"GET /?x HTTP/1.1\r\nHost: x\r\nUpgrade: websocket\r\nConnection: Upgrade\r\n"
           f"Sec-WebSocket-Key: {key}\r\nSec-WebSocket-Version: 13\r\n\r\n".encode())
f = ws.makefile("rb")
assert f.readline().startswith(b"HTTP/1.1 101")
while f.readline() not in (b"\r\n", b""): pass


def ws_recv():  # next text frame from the hub, as JSON
    while True:
        op, data = hub.ws_read(f)
        if op == 1:
            return json.loads(data)


def ws_send(m):  # clients must mask their frames
    data, mask = json.dumps(m).encode(), os.urandom(4)
    ws.sendall(bytes([0x81, 0x80 | len(data)]) + mask + bytes(b ^ mask[i % 4] for i, b in enumerate(data)))


time.sleep(0.1)  # let the hub register the subscriber
assert post(place) == 200
got = ws_recv()
assert got["type"] == "placement" and got["direction"] == "head" and got["source"] == "hub"
ws_send({"type": "confirm", "ts": 1, "source": "glasses", "what": "start_compressions"})
for _ in range(50):
    if {m["type"]: m for m in snap()}["state"]["phase"] == "compress": break
    time.sleep(0.05)
assert {m["type"]: m for m in snap()}["state"]["phase"] == "compress"
ws.close()

# rate limit: LLM_PER_MIN calls allowed, the next one refused
hub.llm_calls.clear()
assert all(hub.llm_allowed() for _ in range(hub.LLM_PER_MIN)) and not hub.llm_allowed()
hub.llm_calls[:] = [time.time() - 61] * (hub.LLM_PER_RUN - 1)  # old calls: minute window is clear
assert hub.llm_allowed() and not hub.llm_allowed()  # ...but the per-run cap is reached

print("ok")
