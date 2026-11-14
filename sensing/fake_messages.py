"""Realistic made-up messages with NO band and NO Arduino, for teammates to build against.

    python -m sensing.fake_messages                 WebSocket on ws://<this laptop>:8765 + JSON lines
    python -m sensing.fake_messages --quiet         WebSocket only
    python -m sensing.fake_messages --post URL      also HTTP POST every message

It cycles through: slow, good, fast, shallow, not releasing, paused. Same format as the
real pipeline (sensing/messages.py). The numbers are invented, not measured.
"""
import argparse
import random
import time

from . import config, messages
from .publisher import Publisher

# name, seconds, rate per minute (None = hands off), depth cm, recoil ok, expected label
SCENARIOS = (
    ("slow",          8, 85,   5.5, True,  "faster"),
    ("good",         10, 110,  5.5, True,  "good"),
    ("fast",          8, 138,  5.4, True,  "slower"),
    ("shallow",       8, 110,  3.6, True,  "harder"),
    ("not releasing", 8, 110,  5.5, False, "release fully"),
    ("paused",        5, None, None, None, None),
)


def run(publisher, seconds=None, speed=1.0, seed=1, sleep=time.sleep, arduino=True):
    """Emit messages until `seconds` have passed (None = for ever)."""
    rng = random.Random(seed)
    state = messages.empty_state()
    status = dict(connected=True, reconnecting=False, paused=True, arduino_ok=arduino, battery_percent=87)
    t_ms = 1000.0                       # pretend band clock
    session_start = None
    hands_off = 0.0
    last_heartbeat = 0.0
    last_status = None
    started = t_ms

    def tick(dt):
        nonlocal t_ms, last_heartbeat, last_status
        end = t_ms + dt * 1000.0
        while True:
            next_beat = last_heartbeat + config.HEARTBEAT_S * 1000.0
            if next_beat > end:
                break
            sleep(max(0.0, (next_beat - t_ms) / 1000.0 / speed))
            t_ms = next_beat
            last_heartbeat = next_beat
            _refresh()
            publisher.publish(messages.heartbeat(t_ms, state, status))
        sleep(max(0.0, (end - t_ms) / 1000.0 / speed))
        t_ms = end

    def _refresh():
        if session_start is not None:
            state["session_s"] = (t_ms - session_start) / 1000.0
            state["swap_in_s"] = max(0.0, config.SWAP_S - state["session_s"] % config.SWAP_S)
            state["hands_off_s"] = hands_off

    def send_status():
        nonlocal last_status
        key = tuple(sorted(status.items()))
        if key != last_status:
            last_status = key
            publisher.publish(messages.status(t_ms, status))

    send_status()
    while True:
        for name, length, rate, depth, recoil, label in SCENARIOS:
            scenario_end = t_ms + length * 1000.0
            if rate is None:                        # hands off
                tick(config.PAUSE_S)
                status["paused"] = True
                hands_off += config.PAUSE_S
                send_status()
                while t_ms < scenario_end:
                    tick(0.5)
                    hands_off += 0.5
                    if seconds is not None and t_ms - started >= seconds * 1000.0:
                        return
                continue
            while t_ms < scenario_end:
                tick(60.0 / (rate * rng.uniform(0.97, 1.03)))
                if session_start is None:
                    session_start = t_ms
                if status["paused"]:
                    status["paused"] = False
                    send_status()
                d = depth + rng.uniform(-0.2, 0.2)
                g = 0.09 * d + rng.uniform(-0.03, 0.03)
                state.update(
                    count=state["count"] + 1, rate_cpm=rate * rng.uniform(0.98, 1.02), depth_cm=d,
                    depth_source="arduino" if arduino else "band", push_intensity_g=g,
                    push_intensity=min(1.0, max(0.0, (g - 0.3) / 0.3)), quality=label, quality_base="good",
                    confidence=rng.uniform(0.8, 0.98) if arduino else rng.uniform(0.55, 0.7),
                    recoil_ok=recoil if arduino else None, fatigue=False)
                state["low_confidence"] = state["confidence"] < config.LOW_CONFIDENCE_BELOW
                _refresh()
                publisher.publish(messages.compression(t_ms, state))
                if seconds is not None and t_ms - started >= seconds * 1000.0:
                    return


def main(argv=None):
    parser = argparse.ArgumentParser(description="Fake CPR Coach messages (no band, no Arduino).")
    parser.add_argument("--port", type=int, default=config.WS_PORT, help="WebSocket port (default %(default)s)")
    parser.add_argument("--no-ws", action="store_true", help="no WebSocket server")
    parser.add_argument("--quiet", action="store_true", help="no JSON lines on the screen")
    parser.add_argument("--post", metavar="URL", help="also HTTP POST each message to this address")
    parser.add_argument("--serial-out", metavar="PORT", help="also write each message as a JSON line to a serial port")
    parser.add_argument("--no-arduino", action="store_true", help="pretend there is no Arduino (band-only depth)")
    parser.add_argument("--seconds", type=float, help="stop after this many seconds")
    args = parser.parse_args(argv)
    publisher = Publisher(stdout=not args.quiet, ws=not args.no_ws, ws_port=args.port, post_url=args.post,
                          serial_out=args.serial_out)
    if not args.no_ws:
        import sys
        print("Fake messages on ws://localhost:%d (other laptops: ws://<this laptop's IP>:%d). Stop with Ctrl+C."
              % (args.port, args.port), file=sys.stderr)
    try:
        run(publisher, seconds=args.seconds, arduino=not args.no_arduino)
    except KeyboardInterrupt:
        pass
    finally:
        publisher.close()


if __name__ == "__main__":
    main()
