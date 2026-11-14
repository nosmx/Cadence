"""Check what the Arduino sends over USB before running the pipeline.

    python -m sensing.arduino_check /dev/cu.usbmodem12653166792        (Mac)
    python -m sensing.arduino_check COM5                               (Windows)
    python -m sensing.arduino_check COM5 9600                          (only this speed)

Listens at each common speed (baud rate) in turn, prints the raw lines and the distance
the pipeline would read from them, then says which speed to use or what is wrong.
Close the Arduino IDE's Serial Monitor first: only one program can open the port.
"""
import sys
import time

from .chest_input import SERIAL_BAUD, parse_line

SPEEDS = (SERIAL_BAUD, 9600, 57600, 38400, 19200, 230400)
LISTEN_S = 4.0          # opening the port restarts many Arduinos; they need ~2 s to boot
SHOW_LINES = 6


def listen(port, baud, seconds=LISTEN_S, opener=None):
    """-> (lines, readable distances, examples) heard at this speed."""
    import serial
    opener = opener or (lambda: serial.Serial(port, baud, timeout=0.2))
    lines, readable, examples = 0, [], []
    with opener() as link:
        end = time.monotonic() + seconds
        while time.monotonic() < end:
            raw = link.readline()
            if not raw:
                continue
            lines += 1
            distance = parse_line(raw)
            if distance is not None:
                readable.append(distance)
            if len(examples) < SHOW_LINES:
                examples.append((raw, distance))
    return lines, readable, examples


def verdict(results):
    """results: {baud: (lines, readable, examples)} -> (best baud or None, advice)."""
    heard = {b: r for b, r in results.items() if r[0]}
    if not heard:
        return None, ("The Arduino sent nothing at any speed. Check that the sketch is uploaded, that it calls "
                      "Serial.begin(...) and Serial.println(distance) in loop(), and that the cable carries data.")
    best = max(heard, key=lambda b: (len(heard[b][1]) / heard[b][0], len(heard[b][1])))
    lines, readable, _ = heard[best]
    if len(readable) < lines * 0.8:
        return None, ("Lines arrive, but most hold no distance the pipeline can read. Make the sketch print one "
                      "number per line, e.g. Serial.println(distance_cm);  (\"18.4\", \"18.4 cm\" and "
                      "{\"distance_cm\":18.4} all work).")
    spread = max(readable) - min(readable)
    still = " The distance did not change: press the manikin while checking." if spread < 0.2 else ""
    return best, ("Use speed %d: %d of %d lines readable, distances %.1f to %.1f cm.%s"
                  % (best, len(readable), lines, min(readable), max(readable), still))


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    if not argv:
        raise SystemExit(__doc__)
    port = argv[0]
    speeds = (int(argv[1]),) if len(argv) > 1 else SPEEDS
    results = {}
    for baud in speeds:
        print("Listening on %s at %d for %.0f s..." % (port, baud, LISTEN_S))
        try:
            results[baud] = listen(port, baud)
        except Exception as e:
            raise SystemExit("Could not open %s: %s" % (port, e))
        lines, readable, examples = results[baud]
        print("  %d lines, %d with a readable distance" % (lines, len(readable)))
        for raw, distance in examples:
            print("    %-40r -> %s" % (raw[:40], "%.2f cm" % distance if distance is not None else "not readable"))
        if lines and len(readable) == lines:
            break                       # clean at the first speed tried: no need to go on
    best, advice = verdict(results)
    print()
    print(advice)
    if best is not None:
        suffix = "" if best == SERIAL_BAUD else ":%d" % best
        print("Run:  python -m sensing.run 27 --arduino serial:%s%s --pretty" % (port, suffix))


if __name__ == "__main__":
    main()
