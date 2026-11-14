"""UNO Q anchor: the band's Bluetooth signal strength -> `placement` messages for the hub.

The board sits under the manikin's chest. A stronger signal from the band means the
rescuer's wrist is closer. This tells on-spot / not, and closer / farther. It can NOT
measure centimetres, so distance_cm and direction are always null, and nothing here feeds
compression depth. Tune --near-dbm on the real setup: watch the printed dBm with hands on
the spot, then off it, and pick a value in between.

Run on the UNO Q (stdlib only, needs bluez's bluetoothctl):
    python3 anchor.py --hub http://127.0.0.1:8000/msg            only our band, C1:3F:B9:F4:08:66 (Vexo-HACK-27)
    python3 anchor.py --addr "" --name Vexo-HACK-27              another band: found by exact name instead
Test anywhere: python3 hub/test_anchor.py
"""
import argparse, json, re, subprocess, sys, threading, time, urllib.request

OUR_BAND = "C1:3F:B9:F4:08:66"  # Vexo-HACK-27. Other teams' Vexo bands are in the same room.
ANSI = re.compile(r"\x1b\[[0-9;]*m|\x01|\x02")
# [NEW] Device C1:3F:B9:F4:08:66 Vexo-HACK-27     [CHG] Device C1:..:66 Name: Vexo-HACK-27
NAME = re.compile(r"Device ([0-9A-F:]{17}) (?:Name: |Alias: )?(.+)$", re.I)
# [CHG] Device C1:..:66 RSSI: -75      or      RSSI: 0xffffffb5 (-75)
RSSI = re.compile(r"Device ([0-9A-F:]{17}) RSSI: (?:0x[0-9a-f]+ \()?(-?\d+)\)?", re.I)


def parse(line):
    """bluetoothctl line -> ("rssi", addr, dbm) | ("name", addr, name) | None"""
    line = ANSI.sub("", line).strip()
    if m := RSSI.search(line):
        return "rssi", m[1].upper(), int(m[2])
    if (m := NAME.search(line)) and ":" not in m[2][:4] and not m[2].startswith(("RSSI", "TxPower", "ManufacturerData", "ServiceData", "UUIDs", "Connected", "Paired")):
        return "name", m[1].upper(), m[2].strip()
    return None


class Anchor:
    """Smoothed RSSI -> placement. All the calibration knobs are here."""

    def __init__(self, name="Vexo-HACK-27", addr=None, near_dbm=-60, hyst_db=3, alpha=0.3, trend_db=2, trend_s=1.0):
        self.want_name, self.addr = name.lower(), addr and addr.upper()
        self.near, self.hyst, self.alpha, self.trend_db, self.trend_s = near_dbm, hyst_db, alpha, trend_db, trend_s
        self.ema = None
        self.raw = None  # last reading, unsmoothed
        self.found_name = None  # the name the band advertises, once seen
        self.on = False
        self.last_at = 0.0
        self.history = []  # (time, ema) for the trend

    def feed(self, line, now):
        p = parse(line)
        if not p:
            return
        kind, addr, val = p
        if kind == "name" and addr == self.addr:
            self.found_name = val
        if kind == "name" and self.addr is None and val.lower() == self.want_name:
            self.addr, self.found_name = addr, val
            print(f"[anchor] band found: {val} {addr}", file=sys.stderr)
        elif kind == "rssi" and addr == self.addr:
            self.raw = val
            self.ema = val if self.ema is None else self.alpha * val + (1 - self.alpha) * self.ema
            self.last_at = now
            # hysteresis: a reading hovering at the threshold must not flicker on/off
            self.on = self.ema >= (self.near - self.hyst if self.on else self.near)
            self.history = [h for h in self.history if now - h[0] <= self.trend_s] + [(now, self.ema)]

    def placement(self, now):
        age = now - self.last_at
        signal = 0.0 if self.ema is None else max(0.0, min(1.0, 1 - (age - 1) / 2))  # 1 up to 1 s old, 0 at 3 s
        trend = None
        if signal and len(self.history) > 1:
            d = self.history[-1][1] - self.history[0][1]  # stronger = closer
            trend = "closer" if d > self.trend_db else "farther" if d < -self.trend_db else "steady"
        return {"type": "placement", "source": "anchor", "ts": int(time.time() * 1000),
                "on_target": bool(self.on and signal > 0), "distance_cm": None, "direction": None,
                "signal": round(signal, 2), "trend": trend, "rssi_dbm": None if self.ema is None else round(self.ema, 1),
                "band": self.addr, "band_name": self.found_name, "rssi_raw": self.raw, "age_s": None if self.ema is None else round(age, 1)}


def scan_lines():
    """Run bluetoothctl and yield its output lines. ponytail: bluetoothctl over pipes, not D-Bus;
    swap to bleak/dbus if bluetoothctl's output format changes."""
    p = subprocess.Popen(["bluetoothctl"], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                         stderr=subprocess.STDOUT, text=True, bufsize=1)
    # duplicate-data on: report every advert, not only changes. Older bluez lacks the scan menu; harmless.
    p.stdin.write("menu scan\nduplicate-data on\nback\nscan on\n")
    p.stdin.flush()
    yield from p.stdout


def post(url, m):
    req = urllib.request.Request(url, json.dumps(m).encode(), {"Content-Type": "application/json"})
    urllib.request.urlopen(req, timeout=1).close()


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--hub", default="http://127.0.0.1:8000/msg")
    ap.add_argument("--name", default="Vexo-HACK-27", help="exact band name; other teams have Vexo bands too")
    ap.add_argument("--addr", default=OUR_BAND, help='band address; every other device is ignored ("" = find by --name)')
    ap.add_argument("--near-dbm", type=float, default=-60, help="smoothed RSSI at or above this = on the spot")
    ap.add_argument("--stdin", action="store_true", help="read bluetoothctl lines from stdin (replay)")
    a = ap.parse_args()
    anchor = Anchor(a.name, a.addr or None, a.near_dbm)

    def reader():
        for line in (sys.stdin if a.stdin else scan_lines()):
            anchor.feed(line, time.monotonic())

    threading.Thread(target=reader, daemon=True).start()
    n = 0
    while True:  # 5 Hz: the glasses call placement lost after 1.5 s
        m = anchor.placement(time.monotonic())
        try:
            post(a.hub, m)
        except OSError as e:
            print(f"[anchor] hub unreachable: {e}", file=sys.stderr)
        if n % 5 == 0:
            print(f"{m['rssi_dbm']} dBm  on_target={m['on_target']}  trend={m['trend']}  signal={m['signal']}"
                  f"  band={anchor.addr or 'searching'}", flush=True)
        n += 1
        time.sleep(0.2)


if __name__ == "__main__":
    main()
