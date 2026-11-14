# CPR Coach — G2 glasses app (mock)

Even Realities G2 glasses UI for CPR Coach. **Training tool, not a medical device. Practice on a manikin or pillow only.**

The app currently runs against a **mock Arduino server** (hand position + bracelet compression data), driven from a control panel on the phone / simulator / browser screen.

## Flow

![Screens (browser preview)](docs/screens.png)

1. **Splash** — disclaimer. Tap to begin.
2. **Set up (3 pages)** — how to kneel, where to put your hands, how to hold your body. Tap = next, swipe up = back.
3. **Align hands** — Arduino says which way to move (toward head / feet / left / right), how far away, and CLOSER / FARTHER. Holding on the spot for 1.5 s locks in (or tap while on the spot). If hand tracking is lost you can tap to continue — a sensor never blocks CPR.
4. **Ready** — say **"READY"** (or tap) to start. If your hands drift off the spot for 1 s you go back to aligning.
5. **Compress** — live bracelet data: advice (FASTER / SLOWER / GOOD RATE, PUSH HARDER / LESS DEEP / GOOD DEPTH), rate, depth, pressure, count, 2-minute swap timer. Stale or low-confidence data shows `--` and a warning instead of a number. Double tap = end.
6. **Summary** — count, time, % of compressions in the target rate and depth.

## Run it on your computer

Requires **Node.js 20.17+ or 22.13+**.

```bash
cd glasses-app
npm install
npm run dev
```

This serves the app at http://localhost:5173 (and on your LAN IP, printed in the terminal).

### Option A — quick look in a browser

Open http://localhost:5173. You get an **approximate** glasses display (fonts and wrapping differ from the real G2) plus the mock control panel.

Keys: `Enter` = tap, `D` = double tap, `↑`/`↓` = swipe, `R` = say "ready". Or use the buttons.

### Option B — official Even Hub simulator (recommended for layout)

Keep `npm run dev` running, then in a second terminal:

```bash
cd glasses-app
npm run sim
```

(`npm run sim` = `evenhub-simulator http://localhost:5173`; the simulator is installed as a dev dependency.)

- The simulator window shows the glasses display; the WebView part shows the mock control panel — use it to move the hands, change rate/depth, drop sensors, and "say READY".
- Use the simulator's own touchpad controls for tap / double tap / swipe.
- **Linux only:** the simulator needs WebKitGTK 4.1 and libsoup 3, e.g. on Ubuntu/Debian:
  ```bash
  sudo apt install libwebkit2gtk-4.1-0 libsoup-3.0-0
  ```
- The simulator is not the hardware: check timing and legibility on real glasses before trusting it.

### Option C — real G2 glasses

Phone and computer on the same Wi-Fi, `npm run dev` running, then:

```bash
npm run qr
```

Scan the QR code from the Even app's developer (sideload) mode. The phone screen shows the mock control panel; the glasses show the UI.

## Connecting the real Arduino

Load the app with `?ws=` pointing at the Arduino's WebSocket server, e.g. `http://localhost:5173/?ws=ws://192.168.4.1:81`. Then the mock panel hides and messages come from the Arduino.

The Arduino sends one JSON object per WebSocket text frame (draft schema — see `src/protocol.ts`):

```json
{"type":"placement","ts":1731600000000,"source":"arduino","on_target":false,"distance_cm":4.2,"direction":"head","signal":0.8}
{"type":"compression","ts":1731600000000,"source":"bracelet","rate_cpm":108,"depth_cm":5.3,"pressure":0.72,"quality":"good","confidence":0.9}
```

- `direction`: `head` | `feet` | `left` | `right` | `null` (patient-relative).
- `compression`: one message per compression.
- The glasses send back `{"type":"voice_event","phrase":"ready",...}` and `{"type":"confirm","what":"hands_placed" | "start_compressions" | "end_session",...}`.

Before packaging, put the Arduino's address in `app.json` → `permissions[network].whitelist`.

## Scripts

| Command | What it does |
|---|---|
| `npm run dev` | Dev server on port 5173 (LAN-visible) |
| `npm run sim` | Open the Even Hub simulator on the dev server |
| `npm test` | Unit tests (coach logic + full screen flow) |
| `npm run typecheck` | TypeScript check |
| `npm run pack` | Build and package `cpr-coach.ehpk` |
| `npm run qr` | QR code for sideloading onto real glasses |

## Code map

| File | Purpose |
|---|---|
| `src/app.ts` | Phase state machine, input handling, render loop |
| `src/screens.ts` | Each screen's layout (≤ 8 text boxes, 576×288) |
| `src/coach.ts` | Rate/depth advice, staleness + confidence checks, gauges (plain code, no LLM) |
| `src/guidance.ts` | CPR copy + targets — **verify against AHA/Red Cross before demo** |
| `src/protocol.ts` | Message types + validation of incoming JSON |
| `src/sources/mock.ts` | Mock Arduino + bracelet |
| `src/sources/websocket.ts` | Real Arduino WebSocket client (auto-reconnect) |
| `src/display/even.ts` | G2 rendering via Even Hub SDK (deduped, coalesced text updates) |
| `src/display/browser.ts` | Approximate browser preview / phone mirror |
| `src/panel.ts`, `index.html` | Mock control panel |

## Open items / unverified

- **CPR copy and targets** (100–120/min, 5–6 cm, 2-min swap, set-up steps) were written from memory — check them against AHA/Red Cross and record the source in `src/guidance.ts`.
- **"READY" voice command:** mocked with a button / `R` key. Real speech-to-text isn't chosen yet — the glasses mic gives raw 16 kHz PCM, so recognition has to run somewhere (phone or server). Tap also starts compressions as a fallback.
- **Display refresh speed on hardware** (go/no-go #1): not measured yet. All live values use text containers; no images are used.
- **Arduino reachability** (go/no-go #3): not tested — whether the Even app WebView can open a plain `ws://` connection to a LAN device, and the whitelist format for it.
- **Text gauges** (`..[=#]..`) assume roughly even character widths; check on the simulator / glasses.
- **Click events:** a click is assumed to arrive with `eventType` 0 or missing (protobuf default). Confirm on hardware.
