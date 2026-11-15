# CPR Coach — demo runbook

Bracelet → UNO Q (sensing program) → glasses. Training tool on a manikin or pillow, never a person.

## The day before

- [ ] Charge the band, the glasses and the phone.
- [ ] Glasses app **0.1.5** (or newer) installed on the phone from the Even Hub beta.
- [ ] Sensing code is on the board: in `Cadence/`, `adb push sensing vexo-open-kit /home/arduino/cadence/`.
- [ ] Network test (below) passes on the network you'll demo on.
- [ ] Practise the 60-second script once with the real band.

## Network test (do this first, at the venue)

The phone must reach the board on port 8765. The venue Wi-Fi may block device-to-device traffic.

1. Start the sensing program on the board (step 2 below).
2. On the phone, open CPR Coach. Under **Arduino connection**, enter `ws://<board-ip>:8765`, press **Use Arduino**.
3. The **Source** line must say `connected`. If it stays on `connecting`: put the phone and the board on the phone's hotspot (`sudo nmcli dev wifi connect "HOTSPOT" password "PASS"` in `adb shell`), get the board's new IP (`ip -4 addr show wlan0`), add `ws://<new-ip>:8765` to `glasses-app/app.json`'s whitelist, re-pack and upload, and enter the new address on the phone.

## Start-up (5 minutes before)

1. **Band:** make sure the Mac is *not* connected to it (no `sensing.run` or dashboard on the Mac). Double-tap the band: blue blink.
2. **Board** (Terminal on the Mac, in `Cadence/`):
   ```bash
   adb shell 'pkill -f sensing.run; true'
   adb shell -t 'cd /home/arduino/cadence && python3 -m sensing.run 27 --ws --pretty'
   ```
   Wait for `Sensing from Vexo-HACK-27`. Leave this window open. (The `pkill` clears an old copy; two copies cannot share port 8765.)
3. **Phone:** open CPR Coach. Source = `connected`. Tap the phone screen once (allows the beep), press **Test beep**, phone not on silent.
4. **Glasses:** put them on. The first screen says `Say "READY" to begin` (if it says `VOICE OFF`, the speech model is missing: taps still work).

## Showing the computer next to the glasses

The glasses show the **same numbers and advice as the latest line** in the board's terminal (`--pretty`):
rate, depth, push in g, and the label (`faster` → FASTER, `harder` → PUSH HARDER, ...). Differences you will see, and why:

- The terminal prints every compression; the glasses show only the newest. Compare with the **last** line.
- Nothing appears until the band has seen 4 even pushes (about 2 s); the glasses say START PUSHING meanwhile.
- The glasses can trail the terminal by a fraction of a second (Bluetooth to the glasses).
- **Count:** the terminal counts since the program started; the glasses count this session. Restart the board program right before the demo and they match.
- If the phone's **Source** line says `mock`, the glasses show made-up numbers: switch to **Use Arduino**.

## The 60-second script

| Say / do | Glasses show | Point to make |
|---|---|---|
| "READY" ×4 | Start, then KNEEL / HANDS / BODY with pictures | Hands-free set-up by voice |
| (align screen) "READY" | `WAITING FOR HAND TRACKING`, then ready | Without a chest sensor we continue; with one it locks on by itself |
| "READY" | Circle flashes, figure pushes, phone beeps | Pace guide at 110/min |
| Push steadily with the circle | `GOOD - keep going`, rate ~110 | Live rate from the wrist band |
| Push slowly | `FASTER - match the circle` | One instruction at a time |
| Push fast | `SLOWER - match the circle` | |
| Stop for 3 s | `HANDS OFF - resume with the circle` | Knows the difference between a pause and a lost sensor |
| Resume, then "STOP" | Summary: count, time, % in target | Session review |

Say clearly: **depth from the wrist alone is an estimate** (accurate depth needs the chest sensor), and push strength is not pressure.

## If something goes wrong

| Problem | Fix |
|---|---|
| Source stays `connecting` | Network: use the hotspot (above). Last resort: **Use mock data** on the phone and drive it from the panel (presets: too slow / good / too fast / shallow). |
| Board says the band was not found | Mac still connected to the band? Double-tap again. Still nothing: press the band's RESET once, double-tap. |
| `address already in use` on the board | `adb shell 'pkill -f sensing.run; true'`, start again. |
| Voice not heard | Speak closer and louder, or tap the glasses touchpad (tap = READY, swipe up = BACK, double tap = STOP). |
| No beep | Tap the phone screen once, un-mute, **Test beep**. The circle still shows the pace. |
| Everything fails | Play `glasses-app/docs/demo.mp4`. |

## Verified so far

- In the cloud: the sensing program streaming into the glasses app over WebSocket, the full flow with and without a chest sensor, the package builds, 674 glasses tests and 57 sensing tests pass.
- By the team: the app on the glasses (voice works), the band connected to the UNO Q and counting compressions.
- **Not yet verified:** the phone reaching the board over the network, the Even app allowing `ws://` to the board, how smoothly the circle and figure animate on the glasses, the beep inside the Even app.
