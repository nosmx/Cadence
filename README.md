# Cadence

CPR coaching on Even Realities G2 glasses with a wrist sensor.
**Training tool for manikin or pillow practice. Not a medical device. Never practice on a person.**

## Parts

- [sensing/](sensing/README.md): wrist band → live compression messages (Person 1)
- [glasses-app/](glasses-app/README.md): the G2 glasses app, voice controlled (Person 2)
- [hub/](hub/): the hub that joins them, dashboard, voice-note timeline, UNO Q anchor (Person 3)
- [PROTOCOL.md](PROTOCOL.md): the message format every part uses

## Hub (Person 3)

```bash
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
cp .env.example .env                  # then put your OpenAI key in .env (git ignores it)
.venv/bin/python hub/hub.py           # prints the LAN address for the glasses; dashboard at http://localhost:8000
.venv/bin/python hub/fake_sensor.py   # fake band + anchor until the real ones are wired up
.venv/bin/python hub/test_hub.py      # self-check
.venv/bin/python -m sensing.fake_messages --no-ws --post http://localhost:8000/msg --post-all  # fake band in Person 1's format
```

- Person 1 (band): `python -m sensing.run 27 --arduino serial:COM5 --post http://<hub-ip>:8000/msg --post-all`
  With `--arduino`, it also sends the glasses `placement` (hands on the spot = the Arduino sees the
  chest pressed). Tune `SPOT_PRESS_CM` / `SPOT_HOLD_S` in `sensing/config.py`.
- Person 2 (glasses): open the app with `?ws=ws://<hub-ip>:8000` (the hub prints it). The hub's
  address must be in `glasses-app/app.json`'s network whitelist.
- UNO Q (anchor): `hub/anchor.py` posts `placement` messages from the band's Bluetooth signal
  strength, from our band only (`C1:3F:B9:F4:08:66`; every other Bluetooth device is ignored).
  It tells on-spot and closer/farther only, never centimetres. Replaced by the Arduino above:

```bash
adb push hub/anchor.py /home/arduino/anchor.py
adb reverse tcp:8000 tcp:8000      # venue WiFi blocks board<->laptop; this goes over the USB cable
adb shell 'python3 /home/arduino/anchor.py --hub http://127.0.0.1:8000/msg'   # prints dBm 1/s
```

  Hands on the spot, then off: note both dBm values and restart with `--near-dbm` halfway between.
  If it stays on `band=searching`, the band stops advertising while the band laptop is connected
  to it; check `bluetoothctl` sees it at all. Another band: `--addr "" --name Vexo-HACK-NN`.
  Self-check without a board: `.venv/bin/python hub/test_anchor.py`.
  Measured 2026-11-14: the band only advertises while NOT connected to the band laptop, and wrist
  on vs off the spot moved the reading by 3-5 dB (-87 vs -90..-94 dBm), no more than its jitter,
  with gaps of 3-5 s between readings. Not usable for on-spot as set up; don't run it in a session
  (its constant "off spot" makes the glasses ignore READY on the alignment screen).
