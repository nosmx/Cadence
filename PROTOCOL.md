# Cadence message format (v1)

Owner: Person 3. Everyone builds against this; change it here first.

Transport: JSON over HTTP to the hub (default `http://<hub-ip>:8000`).

| Endpoint | Use |
|---|---|
| `POST /msg` | Send one message (body = one JSON object below). 400 if invalid. |
| `GET /events` | Server-Sent Events stream of every message the hub accepts or creates. On connect it replays the latest of each type plus all log entries. |
| `GET /snapshot` | Same replay as one JSON object, for clients that can't use SSE (poll it). |
| `GET /` | Dashboard. |

CORS is open (`*`) so the glasses app (phone WebView) and dashboard can call it from any origin.

## Common fields (every message)

| Field | Type | Notes |
|---|---|---|
| `type` | string | One of the six types below. |
| `ts` | number | Sender clock, Unix milliseconds. |
| `src` | string | `band`, `fake`, `glasses`, `hub`, `dashboard`. |

The hub adds `t` (seconds since the hub started the session) to everything it rebroadcasts, so all clients share one clock.

## Types

**`trigger`** (Person 1 → hub, glasses): is the wrist near the patient anchor?
`{"near": true, "rssi": -58}`

**`compression`** (Person 1 → hub, glasses): one per detected compression.
`{"count": 42, "rate_cpm": 112, "depth_cm": 5.3, "quality": "good", "confidence": 0.86}`
- `quality`: `good` | `harder` | `softer` | `faster` | `slower`
- `depth_cm` may be `null` if not estimated.
- `confidence` 0–1. **Below 0.5 the glasses must show LOW SIGNAL, not the numbers.**
- **No compression for 2 s while in `compress` = SENSOR LOST on the glasses.** (Glasses check this from the `t` of the last one.)

**`vitals`** (Person 1 → hub, dashboard): `{"hr_bpm": 128}`

**`state`** (hub → glasses; glasses may also send it on a ring tap to change phase):
`{"phase": "check"}` — `check` | `call` | `position` | `compress` | `aed`

**`voice_event`** (glasses mic → hub): `{"text": "AED arrived, pads on"}`
Text is already transcribed. The hub turns it into a proposed `log_entry`.

**`log_entry`** (hub → glasses, dashboard; glasses → hub to confirm):
`{"id": "a1b2c3", "status": "proposed", "confirmed": false, "event": "AED arrived", "detail": "Pads applied", "llm": true, "said": "AED arrived, pads on", "at": 84.2}`
- `at`: session seconds when the note was spoken. `confirmed` stays `false` until the rescuer confirms.
- `llm`: `false` means the LLM was unavailable and `event` is the raw text.
- Hub creates it as `proposed`. Glasses show it; rescuer taps the ring.
- Glasses reply `{"type": "log_entry", "id": "a1b2c3", "status": "confirmed"}` (or `rejected`). Only `id` and `status` are needed.
- Dashboard shows confirmed entries in the timeline.

## Rules

- Live cues (`compression`, `trigger`, `state`) never go through the LLM. Only `voice_event` → `log_entry` does.
- If the LLM is unavailable, the hub still proposes a `log_entry` with the raw text as `event`.
- Training tool only. Not a medical device.
