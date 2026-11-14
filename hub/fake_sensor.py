"""Fake wrist sensor (stands in for Person 1 until the Vexo band is wired up).

Run:  python hub/fake_sensor.py [hub_url]     (default http://localhost:8000)
Sends trigger, ~110/min compressions with noise, vitals every 5 s, an occasional
low-confidence reading, and a 3 s dropout every 40 compressions (tests SENSOR LOST).
"""
import json, random, sys, time, urllib.request

HUB = (sys.argv[1] if len(sys.argv) > 1 else "http://localhost:8000").rstrip("/") + "/msg"


def send(m):
    m |= {"ts": int(time.time() * 1000), "src": "fake"}
    req = urllib.request.Request(HUB, json.dumps(m).encode(), {"Content-Type": "application/json"})
    try:
        urllib.request.urlopen(req, timeout=2).read()
    except OSError as e:
        print("hub unreachable:", e)


def quality(rate, depth):  # ponytail: placeholder rules; Person 1's model replaces this
    if depth < 5: return "harder"
    if depth > 6: return "softer"
    if rate < 100: return "faster"
    if rate > 120: return "slower"
    return "good"


send({"type": "trigger", "near": True, "rssi": -55})
count, last_vitals = 0, 0.0
while True:
    rate = random.gauss(112, 8)
    time.sleep(60 / rate)
    count += 1
    depth = round(random.gauss(5.4, 0.5), 1)
    conf = 0.3 if random.random() < 0.05 else round(random.uniform(0.75, 0.95), 2)
    send({"type": "compression", "count": count, "rate_cpm": round(rate),
          "depth_cm": depth, "quality": quality(rate, depth), "confidence": conf})
    if time.time() - last_vitals > 5:
        send({"type": "vitals", "hr_bpm": round(random.gauss(120, 6))})
        last_vitals = time.time()
    if count % 40 == 0:
        print("simulating 3 s sensor dropout")
        time.sleep(3)
