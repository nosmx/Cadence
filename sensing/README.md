# sensing/ — wrist band + Arduino → live CPR messages

Person 1's part of CPR Coach. It reads the Vexo Open band on the rescuer's wrist, detects
chest compressions, combines them with the Arduino's distance reading from under the
body, and publishes JSON messages for the hub, the glasses and the dashboard.

**A hackathon training tool. Not a medical device.**

> **Status:** all of this is tested on synthetic signals and on the kit's *pretend* band
> only. Nothing here has been confirmed on the real band or the real Arduino yet.

## Teammates: get messages right now (no band, no Arduino)

```
python -m pip install websockets
python -m sensing.fake_messages
```

Connect to `ws://localhost:8765` (from another laptop: `ws://<that laptop's IP>:8765`).
You get the exact message format below, cycling through slow, good, fast, shallow, not
releasing and paused, about 60 seconds per round. The numbers are invented.

Options: `--quiet` (no JSON on screen), `--port 9000`, `--post URL` (also HTTP POST each
message), `--serial-out COM5` (also write each message as a line to a serial port),
`--no-arduino` (what you get when the Arduino is missing).

## Run the real pipeline

Typed in the repo root, on Windows PowerShell. `27` is our band number.

```
python -m pip install -r sensing/requirements.txt
python -m sensing.run 27 --ws
```

Before it: close the kit's dashboard tab (the band takes one connection) and double-tap
the band. The band kit (`vexo-open-kit/`) must be in the repo root, one folder up, or in
the folder named by `VEXO_KIT`; it is never committed.

| Command | What it does |
|---|---|
| `python -m sensing.run 27 --ws --voice` | real band, WebSocket, spoken corrections |
| `python -m sensing.run 27 --sim --ws` | pretend band playing a known story (good, slow, shallow, pause, fast, not releasing) |
| `python -m sensing.run 27 --sim --ws --arduino sim` | the same with a pretend Arduino |
| `python -m sensing.run 27 --ws --arduino serial:COM5` | Arduino on USB: one number (cm) or one JSON object per line |
| `python -m sensing.run 27 --ws --arduino ws` | Arduino sends `{"type":"chest","distance_cm":12.3}` to our WebSocket |
| `python -m sensing.run 27 --arduino http` | Arduino POSTs that JSON to `http://<laptop>:8766/` |
| `python -m sensing.run 27 --arduino poll:http://ADDRESS/PATH` | we GET the reading from the Arduino's web server, 25 times a second |
| `python -m sensing.run 27 --post http://HUB-IP:8000/msg` | HTTP POST every compression to the team hub |
| `python -m sensing.run 27 --arduino serial:COM5 --serial-out arduino` | send every message to the Arduino as a JSON line on the same cable |
| `python -m sensing.run 27 --record good1 --label good` | save raw samples to `recordings/good1.csv` |
| `python -m sensing.run --replay recordings/good1.csv --ws` | replay a recording at real speed, no band |
| `python -m sensing.arduino_check COM5` | before a run: what the Arduino sends over USB, at which speed (baud), and the exact `--arduino` to use (Mac: `/dev/cu.usbmodem…`) |
| `python -m sensing.calibrate 27 depth` | band-only depth calibration (20 compressions, type the cm) |
| `python -m sensing.calibrate 27 force` | optional force estimate (type kg from a scale) |
| `python -m sensing.accuracy` | band-only depth error against the Arduino, over the recordings |
| `python -m pytest sensing/tests` | the tests |

JSON lines go to the screen unless `--quiet`. `--no-led` leaves the band's light alone
(green = good, amber = a correction, blue = not sure).

## Message format

One JSON object per message. Field names are defined in one file, `sensing/messages.py`.
Every message has `type`, `ts` (Unix milliseconds, as the hub's `PROTOCOL.md` asks),
`ts_iso` (the same moment as ISO 8601 UTC), `t_band_ms` (the band's clock), and the sender
twice: `src: "band"` (hub) and `source: "band"` (glasses app).

**Fit with the hub (`PROTOCOL.md`):** a `compression` message carries everything the hub's
`POST /msg` checks (`count`, `rate_cpm`, `quality`, `confidence`, `ts`, `src`) plus extra
fields the hub ignores. Send them to the hub with `--post http://HUB-IP:8000/msg`; only
`compression` messages are posted, because the hub answers 400 to `status` and
`heartbeat` (they still go to the WebSocket and the screen).

### `compression` — one per detected compression

```json
{"type":"compression","ts":1794578601512,"ts_iso":"2026-11-14T14:03:21.512Z","t_band_ms":48213,"src":"band","source":"band",
 "count":37,"rate_cpm":109.8,"depth_cm":5.42,"depth_source":"arduino",
 "push_intensity_g":0.371,"push_intensity":0.62,"pressure":0.62,
 "quality":"good","quality_full":"good","confidence":0.93,"low_confidence":false,"recoil_ok":true,
 "session_s":20.4,"hands_off_s":0.0,"swap_in_s":99.6,"fatigue":false}
```

| Field | Meaning |
|---|---|
| `count` | compressions so far |
| `rate_cpm` | per minute: 60 / median of the last 5 intervals. `null` for the first compression after a pause |
| `depth_cm` | depth of the cycle that just ended. `null` when there is no full cycle yet (first compression after a pause) |
| `depth_source` | `"arduino"` (measured under the body) or `"band"` (estimate from the wrist) |
| `push_intensity_g` | peak downward acceleration of the wrist, in g. **Not pressure** |
| `push_intensity` | the same as a 0..1 score against the range seen in good compressions |
| `force_kg_est` | **only present** after a force calibration; an estimate (k × depth), not a measurement |
| `pressure` | the same number as `push_intensity`, under the name the glasses app reads. **It is not pressure** |
| `quality` | one of the hub's five words: `good`, `harder`, `softer`, `faster`, `slower` |
| `quality_full` | our own label: `good`, `faster`, `slower`, `harder`, `lighter` (= `softer`), `release fully`. Targets: 100–120 per minute, 5–6 cm. When several apply: faster, harder, release fully, slower, lighter. `release fully` has no hub word, so `quality` then holds the label that applies without it |
| `confidence` | 0..1 |
| `low_confidence` | `true` below 0.5: **show a warning instead of the numbers** |
| `recoil_ok` | `true` / `false` with the Arduino (did the chest come back up?), `null` without it |
| `session_s` | seconds since the first compression |
| `hands_off_s` | total seconds without compressions (a pause starts after 2 s) |
| `swap_in_s` | seconds until the 2-minute rescuer swap; stays 0 until a pause of 3 s or more, then starts again |
| `fatigue` | `true` when the median depth of the last 20 s is 15 % or more below the first 20 s |

### `status` — when something changes

```json
{"type":"status","ts":1794578601512,"ts_iso":"2026-11-14T14:03:01.004Z","t_band_ms":27801,"src":"band","source":"band",
 "connected":true,"reconnecting":false,"paused":false,"arduino_ok":true,"battery_percent":87}
```

`paused` = hands off (no compression for 2 s). `arduino_ok` = Arduino data under 0.5 s old.

### `heartbeat` — once a second

All fields of the latest `compression` (with `session_s`, `hands_off_s`, `swap_in_s`
kept current) plus all fields of `status`. Before the first compression: `count` 0 and
`null` values.

```json
{"type":"heartbeat","ts":1794578601512,"ts_iso":"2026-11-14T14:03:22.000Z","t_band_ms":48700,"src":"band","source":"band",
 "count":37,"rate_cpm":109.8,"depth_cm":5.42,"depth_source":"arduino",
 "push_intensity_g":0.371,"push_intensity":0.62,"pressure":0.62,
 "quality":"good","quality_full":"good","confidence":0.93,"low_confidence":false,"recoil_ok":true,
 "session_s":20.9,"hands_off_s":0.0,"swap_in_s":99.1,"fatigue":false,
 "connected":true,"reconnecting":false,"paused":false,"arduino_ok":true,"battery_percent":87}
```

## How it works

- `band_source.py` connects (100 samples per second, 8 g range), and only stores samples
  in the band's handler; all work happens in the main loop.
- `detector.py` finds gravity with a slow filter, projects the acceleration onto it (so
  the wrist's orientation does not matter), counts one compression per upward zero
  crossing, and gets depth by integrating each cycle twice with the means removed.
- `fusion.py`: rate, timing and count always come from the band. Depth comes from the
  Arduino while its data is fresh, else from the band. While both are there the band's
  scale follows the Arduino, so the band stays accurate if the Arduino drops out.
- `quality.py`: label, confidence, fatigue, push intensity.
- `publisher.py`: stdout, WebSocket, HTTP POST, serial. A slow or dead client only loses
  its own messages.
- `config.py`: every tunable number, each marked measured or guessed. **All are guesses so far.**

## Where this differs from the rest of the repo (to settle with the team)

- `PROTOCOL.md` lists `trigger` (wrist near a patient anchor) and `vitals` (`hr_bpm`) as
  coming from the band. **Neither is sent.** The band has no heart-rate sensor, and its
  signal strength is to the laptop, not to an anchor on the patient.
- The glasses app drops a `compression` whose `depth_cm` is `null`. That can happen for
  the first push after a pause while the Arduino is connected.
- The glasses show SENSOR LOST after 2 s without a compression; the rhythm lock means
  the first message of a run arrives about 2 s after the first push.
- The glasses app expects its messages on a WebSocket from the Arduino; the hub expects
  HTTP POST. This code offers both (`--ws`, `--post`), plus serial for the Arduino.

## Known limits

- **Band-only depth is an estimate.** The band is on the wrist, not on the chest, and
  depth comes from integrating acceleration twice. Uncalibrated, it lowers `confidence`.
  Calibrate it (`sensing.calibrate 27 depth`) or let the Arduino teach it.
- **Push intensity is not measured pressure.** The band has no pressure or force sensor.
  `force_kg_est` exists only after a force calibration and is still an estimate.
- `recoil_ok` needs the Arduino. Without it the field is `null`; we do not guess.
- It is assumed that pushing down makes the Arduino's distance *smaller*
  (`CHEST_COMPRESSED_IS_SMALLER` in `config.py`). Not confirmed.
- **Rhythm lock:** nothing is counted until 4 evenly spaced pushes in a row were seen, so
  putting the band on or moving the arm is not counted. The first `compression` message
  of a run therefore arrives after about 2 seconds with `count` already at 4 (the first
  four are confirmed together). A cycle in which the wrist turns fast is not counted.
- The Arduino's field names (`chest_input.py`) are not confirmed with its author.
- `--voice` needs the team's `voice.py` (with a `say(text)` function) in `sensing/` or
  the repo root; without it the program says so and runs without voice.
- `sensing/calibration.json` belongs to one band, one person and one setup.
- No accuracy numbers yet: there are no recordings with the real band and Arduino.
