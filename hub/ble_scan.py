"""List nearby Bluetooth LE devices, strongest first. Works on macOS and on the UNO Q (Linux/BlueZ).

Run: .venv/bin/python hub/ble_scan.py [name-filter] [seconds]     e.g.  hub/ble_scan.py vexo 15
On macOS run it from the Terminal app: it needs Bluetooth permission (System Settings >
Privacy & Security > Bluetooth), or macOS kills it with exit code 134.
"""
import asyncio, sys

from bleak import BleakScanner

want = sys.argv[1].lower() if len(sys.argv) > 1 else ""
secs = float(sys.argv[2]) if len(sys.argv) > 2 else 12


async def main():
    found = await BleakScanner.discover(timeout=secs, return_adv=True)
    rows = [(d, a) for d, a in found.values() if want in (a.local_name or d.name or "").lower()]
    print(f"{len(rows)} device(s) in {secs:.0f}s" + (f" matching {want!r}" if want else ""))
    for d, a in sorted(rows, key=lambda r: -r[1].rssi):
        print(f"{a.rssi:>4} dBm  {(a.local_name or d.name or '?')[:28]:28}  {d.address}"
              f"  services={a.service_uuids}  mfr_ids={list(a.manufacturer_data)}")


asyncio.run(main())
