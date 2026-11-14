"""Run: python hub/test_anchor.py — fake bluetoothctl lines through the anchor, no Bluetooth needed."""
import hub, anchor  # noqa: F401  (hub import checks the placement it makes is valid)

A = "C1:3F:B9:F4:08:66"
assert anchor.parse(f"\x1b[0;93m[CHG]\x1b[0m Device {A} RSSI: 0xffffffb5 (-75)") == ("rssi", A, -75)
assert anchor.parse(f"[CHG] Device {A} RSSI: -48") == ("rssi", A, -48)
assert anchor.parse(f"[NEW] Device {A} Vexo-HACK-27") == ("name", A, "Vexo-HACK-27")
assert anchor.parse(f"[CHG] Device {A} Name: Vexo-HACK-27") == ("name", A, "Vexo-HACK-27")
assert anchor.parse(f"[CHG] Device {A} ManufacturerData Key: 0x0059") is None
assert anchor.parse("[bluetooth]# scan on") is None

a = anchor.Anchor(near_dbm=-60, alpha=1.0)  # alpha 1 = no smoothing, easier to reason about
a.feed("[CHG] Device AA:BB:CC:DD:EE:FF RSSI: -40", 0)  # not the band yet
assert a.ema is None and a.placement(0)["signal"] == 0
a.feed("[NEW] Device F9:C5:72:A6:36:8C Vexo-HACK-38", 0)  # another team's band: ignored
assert a.addr is None
a.feed(f"[NEW] Device {A} Vexo-HACK-27", 0)
a.feed(f"[CHG] Device {A} RSSI: -75", 0.0)
p = a.placement(0.1)
assert not p["on_target"] and p["signal"] == 1 and p["distance_cm"] is None and p["direction"] is None
a.feed(f"[CHG] Device {A} RSSI: -58", 0.5)
p = a.placement(0.5)
assert p["on_target"] and p["trend"] == "closer"
a.feed(f"[CHG] Device {A} RSSI: -62", 0.7)  # inside the 3 dB hysteresis: stays on
assert a.placement(0.7)["on_target"]
a.feed(f"[CHG] Device {A} RSSI: -70", 1.6)
p = a.placement(1.6)
assert not p["on_target"] and p["trend"] == "farther"
b = anchor.Anchor(addr=anchor.OUR_BAND, alpha=1.0)  # locked to our band from the start
b.feed("[CHG] Device F9:C5:72:A6:36:8C RSSI: -30", 0)  # another team's band, very close: ignored
b.feed("[NEW] Device F9:C5:72:A6:36:8C Vexo-HACK-27", 0)  # even if it has our name
assert b.ema is None and b.addr == A
assert a.placement(5)["signal"] == 0 and not a.placement(5)["on_target"]  # band went quiet
assert hub.validate(p) is None, hub.validate(p)
print("ok")
