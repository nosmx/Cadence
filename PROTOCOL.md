# Cadence message format (v2)

Owner: Person 3. Everyone builds against this; change it here first.
v2 matches the glasses app (`glasses-app/src/protocol.ts`), so the glasses parse hub messages unchanged.

Transport: JSON to the hub (default port 8000; it runs on the UNO Q or a laptop).

| Endpoint | Use |
|---|---|
| `ws://<hub-ip>:8000` | WebSocket for the glasses. Hub → glasses: every message, live (no replay). Glasses → hub: `voice_event`, `confirm`. One JSON object per text frame. |
| `POST /msg` | Send one message (body = one JSON object below). 400 if invalid. Band, anchor, dashboard. |
| `GET /events` | Server-Sent Events stream of every message. On connect it replays the latest of each type plus all log entries. Dashboard. |
| `GET /snapshot` | Same replay as one JSON array, for clients that poll. |
| `GET /` | Dashboard. |

CORS is open (`*`).

## Common fields (every message)

| Field | Type | Notes |
|---|---|---|
| `type` | string | One of the types below. |
| `ts` | number | Sender clock, Unix milliseconds. |
| `source` | string | `band`, `anchor`, `glasses`, `hub`, `dashboard`, `fake`. |

The hub adds `t` (seconds since the hub started the session) to everything it rebroadcasts.

## Types

**`placement`** (UNO Q anchor → hub → glasses): where the rescuer's hands are relative to the spot.
`{"on_target": false, "distance_cm": 6.2, "direction": "head", "signal": 0.8}`
- `distance_cm`: number or `null` if unknown. `direction`: `head` | `feet` | `left` | `right` | `null`.
- `trend` (optional): `closer` | `farther` | `steady` | `null`, for an anchor that senses direction of change but not centimetres (the UNO Q's Bluetooth signal strength). The glasses use it when `distance_cm` is `null`.
- `signal` 0–1. Send at least every 0.5 s: the glasses treat placement older than 1.5 s as lost.

**`compression`** (band, Person 1 → hub → glasses): one per detected compression.
`{"rate_cpm": 112, "depth_cm": 5.3, "pressure": 0.7, "quality": "good", "confidence": 0.86}`
- `rate_cpm`, `depth_cm`, `quality` may be `null` (first push after a pause; no depth yet). The hub forwards them; the glasses skip that one message, the dashboard shows "?".
- `depth_cm` is an estimate (unverified until ruler-tested). `pressure` 0–1, optional.
- The band adds more fields (`count`, `recoil_ok`, `hands_off_s`, `fatigue`...; see `sensing/README.md`). The hub passes them through.
- `quality`: the band's own label, e.g. `good` | `shallow` | `slow` | `fast`.
- `confidence` 0–1. **Below 0.6 the glasses and dashboard show "?" / low signal, not the numbers.**
- **No compression for 1.5 s while compressing = sensor lost**, judged by local arrival time.

**`status`** (band → hub, dashboard): `{"connected": true, "reconnecting": false, "paused": false, "arduino_ok": true, "battery_percent": 87}` on change.
**`heartbeat`** (band, once a second): the latest compression fields plus the status fields. No required fields.

**`vitals`** (→ hub, dashboard): `{"hr_bpm": 128}`. Nothing real sends this yet.

**`voice_event`** (glasses mic → hub): `{"phrase": "aed arrived, pads on"}`
Text is already transcribed. Two or more words become a proposed `log_entry` (LLM-tidied); one word (`ready`, `back`, `stop`) is a glasses command: no log entry, no LLM call.

**`confirm`** (glasses → hub): `{"what": "start_compressions"}` — `hands_placed` | `start_compressions` | `end_session`.
The hub turns `start_compressions` into phase `compress` and `end_session` into phase `check`.

**`state`** (hub/dashboard → everyone): `{"phase": "compress"}` — `check` | `call` | `position` | `compress` | `aed`.

**`log_entry`** (hub → dashboard; dashboard → hub to confirm):
`{"id": "a1b2c3", "status": "proposed", "confirmed": false, "event": "AED arrived", "detail": "Pads applied", "llm": true, "said": "aed arrived, pads on", "at": 84.2}`
- `at`: session seconds when the note was spoken. `confirmed` stays `false` until confirmed.
- `llm`: `false` means the LLM was unavailable or skipped and `event` is the raw text.
- Confirm with `{"type": "log_entry", "id": "a1b2c3", "status": "confirmed"}` (or `rejected`).

The glasses app ignores `vitals`, `state` and `log_entry` today (its parser drops unknown types).

## Rules

- Live cues (`compression`, `placement`, `state`) never go through the LLM. Only `voice_event` → `log_entry` does.
- If the LLM is unavailable, the hub still proposes a `log_entry` with the raw text as `event`.
- Training tool only. Not a medical device.
