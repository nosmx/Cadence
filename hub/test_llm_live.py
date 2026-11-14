"""Live check of voice note -> timeline against the real OpenAI API (2 calls, a fraction of a cent).

Run: .venv/bin/python hub/test_llm_live.py      (needs OPENAI_API_KEY in .env)
Prints each entry with its session time and confirmed flag, before and after a confirm.
"""
import json, threading, time, urllib.request

import hub

hub.CLIENT = hub.make_client()  # exits with a clear message if the key is missing
srv = hub.make_server(0)
threading.Thread(target=srv.serve_forever, daemon=True).start()
URL = f"http://127.0.0.1:{srv.server_address[1]}"


def post(m):
    req = urllib.request.Request(URL + "/msg", json.dumps(m).encode(), {"Content-Type": "application/json"})
    return urllib.request.urlopen(req).status


def entries():
    return [m for m in json.loads(urllib.request.urlopen(URL + "/snapshot").read()) if m["type"] == "log_entry"]


def show(title):
    print(f"\n{title}")
    for e in sorted(entries(), key=lambda e: e["at"]):
        print(f"  t={e['at']:>5.2f}s  confirmed: {str(e['confirmed']).lower():5}  llm: {str(e['llm']).lower():5}"
              f"  event: {e['event']!r}  detail: {e['detail']!r}\n            said: {e['said']!r}")


notes = ["Okay I called 911, they said eight minutes", "AED is here, putting the pads on now"]
for n in notes:
    post({"type": "voice_event", "phrase": n})
    time.sleep(0.5)
deadline = time.time() + 40
while len(entries()) < len(notes) and time.time() < deadline:
    time.sleep(0.2)

es = entries()
show("Proposed entries")
assert len(es) == len(notes), "timed out waiting for entries"
assert all(e["confirmed"] is False for e in es)
assert all(e["llm"] for e in es), "OpenAI call failed; see [llm] line above for the error type"

first = min(es, key=lambda e: e["at"])
post({"type": "log_entry", "id": first["id"], "status": "confirmed"})
show("After the rescuer confirms the first one")
assert [e["confirmed"] for e in sorted(entries(), key=lambda e: e["at"])] == [True, False]
print("\nok")
