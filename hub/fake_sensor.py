"""Fake band + anchor (stands in for Person 1 and the UNO Q until they're wired up).

Run:  python hub/fake_sensor.py [hub_url]     (default http://localhost:8000)
Sends placement at 5 Hz (hands drift onto the spot), ~110/min compressions with noise,
vitals every 5 s, an occasional low-confidence reading, and a 3 s compression dropout
every 40 compressions (tests "lost" on the glasses).
"""
import json, random, sys, threading, time, urllib.request

HUB = (sys.argv[1] if len(sys.argv) > 1 else "http://localhost:8000").rstrip("/") + "/msg"


def send(m):
    m |= {"ts": int(time.time() * 1000), "source": "fake"}
    req = urllib.request.Request(HUB, json.dumps(m).encode(), {"Content-Type": "application/json"})
    try:
        urllib.request.urlopen(req, timeout=2).read()
    except OSError as e:
        print("hub unreachable:", e)


def placement():  # hands start 8 cm toward the feet and move onto the spot
    dist = 8.0
    while True:
        dist = max(0.0, dist - 0.3)
        on = dist < 1.2
        send({"type": "placement", "on_target": on, "distance_cm": round(dist, 1),
              "direction": None if on else "head", "signal": round(random.uniform(0.75, 0.9), 2)})
        time.sleep(0.2)


def quality(rate, depth):  # ponytail: placeholder labels, same words as the glasses mock; Person 1's model replaces this
    if depth < 5: return "shallow"
    if rate < 100: return "slow"
    if rate > 120: return "fast"
    return "good"


threading.Thread(target=placement, daemon=True).start()
count, last_vitals = 0, 0.0
while True:
    rate = random.gauss(112, 8)
    time.sleep(60 / rate)
    count += 1
    depth = round(random.gauss(5.4, 0.5), 1)
    conf = 0.3 if random.random() < 0.05 else round(random.uniform(0.75, 0.95), 2)
    send({"type": "compression", "rate_cpm": round(rate), "depth_cm": depth,
          "pressure": round(random.uniform(0.6, 0.8), 2), "quality": quality(rate, depth), "confidence": conf})
    if time.time() - last_vitals > 5:
        send({"type": "vitals", "hr_bpm": round(random.gauss(120, 6))})
        last_vitals = time.time()
    if count % 40 == 0:
        print("simulating 3 s sensor dropout")
        time.sleep(3)
