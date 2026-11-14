"""Run: python hub/test_hub.py  — starts the hub on a spare port, checks the message flow."""
import json, threading, time, urllib.error, urllib.request

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


ok = {"type": "compression", "ts": 1, "src": "fake", "count": 1, "rate_cpm": 110,
      "depth_cm": 5.2, "quality": "good", "confidence": 0.9}
assert post(ok) == 200
assert post({**ok, "quality": "great"}) == 400
assert post({**ok, "confidence": 2}) == 400
assert post({"type": "trigger", "near": 1, "rssi": -50}) == 400  # near must be a bool
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
assert post({"type": "voice_event", "text": "AED arrived"}) == 200
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

# rate limit: LLM_PER_MIN calls allowed, the next one refused
hub.llm_calls.clear()
assert all(hub.llm_allowed() for _ in range(hub.LLM_PER_MIN)) and not hub.llm_allowed()
hub.llm_calls[:] = [time.time() - 61] * (hub.LLM_PER_RUN - 1)  # old calls: minute window is clear
assert hub.llm_allowed() and not hub.llm_allowed()  # ...but the per-run cap is reached

print("ok")
