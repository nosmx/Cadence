"""CPR Coach wrist sensing: the entry point.

    python -m sensing.run 27 --ws --voice              the real band (27 = the number on its bag)
    python -m sensing.run 27 --sim --ws                a pretend band that plays compressions
    python -m sensing.run 27 --sim --arduino sim       ... with a pretend Arduino under the body
    python -m sensing.run --replay recordings/x.csv    a recording, at real speed, no band
    python -m sensing.run 27 --record good1 --label good
    python -m sensing.run 27 --arduino serial:COM5     Arduino on USB (one number or JSON per line)
    python -m sensing.run 27 --ws --arduino ws         Arduino sends {"type":"chest","distance_cm":..} to the WebSocket
    python -m sensing.run 27 --post http://HUB/path    HTTP POST every message to the hub

A training tool for a hackathon. Not a medical device.
"""
import argparse
import sys
import time

from . import chest_input, config, messages
from .pipeline import Pipeline
from .publisher import Publisher
from .recorder import LABELS, Recorder

LED = {"good": "#00ff00", None: "#0000ff"}      # anything else: amber
LED_OTHER = "#ff8800"


class ClockMap:
    """Laptop time -> band time, from the arrival of the band's samples. Samples arrive in
    small bursts, so the least-delayed sample seen so far gives the best match."""

    def __init__(self):
        self.offset = None

    def see(self, t_band_s, host_s):
        offset = t_band_s - host_s
        if self.offset is None or offset > self.offset or offset < self.offset - 5.0:
            self.offset = offset

    def to_band(self, host_s):
        return None if self.offset is None else host_s + self.offset


def band_number(text):
    if not (text.isascii() and text.isdigit() and 1 <= int(text) <= 999):
        raise argparse.ArgumentTypeError('"%s" is not a band number. Type the number on your band\'s bag (1 to 999).' % text)
    return int(text)


def parse(argv=None):
    p = argparse.ArgumentParser(prog="python -m sensing.run", description="CPR Coach wrist sensing (training tool, not a medical device).")
    p.add_argument("number", nargs="?", type=band_number, help="your band number (on the bag)")
    p.add_argument("--sim", action="store_true", help="the kit's pretend band, playing compressions")
    p.add_argument("--replay", metavar="FILE", help="replay a recorded CSV instead of a band")
    p.add_argument("--speed", type=float, default=1.0, help="replay speed (default 1 = real time)")
    p.add_argument("--ws", action="store_true", help="WebSocket server on ws://0.0.0.0:%d" % config.WS_PORT)
    p.add_argument("--ws-port", type=int, default=config.WS_PORT)
    p.add_argument("--post", metavar="URL", help="HTTP POST each compression message to the hub, "
                   "for example http://HUB-IP:8000/msg")
    p.add_argument("--post-all", action="store_true", help="POST status and heartbeat messages too "
                   "(the team hub rejects those)")
    p.add_argument("--serial-out", metavar="PORT", help='write each message as a JSON line to a serial port; '
                   '"arduino" = the port of --arduino serial:...')
    p.add_argument("--quiet", action="store_true", help="no JSON lines on the screen")
    p.add_argument("--pretty", action="store_true", help="one readable line per compression instead of JSON on the screen")
    p.add_argument("--arduino", metavar="HOW", help="serial:COM5 | ws | http | poll:http://ADDRESS/PATH | sim (with --sim)")
    p.add_argument("--record", metavar="NAME", help="save raw samples to recordings/NAME.csv")
    p.add_argument("--label", choices=LABELS, help="label written into the recording")
    p.add_argument("--voice", action="store_true", help="spoken corrections (voice.py)")
    p.add_argument("--no-led", action="store_true", help="leave the band's light alone")
    p.add_argument("--seconds", type=float, help="stop after this many seconds")
    args = p.parse_args(argv)
    if not args.replay and args.number is None:
        p.error("give your band number (the number on the band's bag), also with --sim. Example: python -m sensing.run 27 --sim")
    if args.arduino == "sim" and not args.sim:
        p.error("--arduino sim only goes with --sim")
    if args.arduino == "ws" and not args.ws:
        p.error("--arduino ws needs --ws (the Arduino sends its messages to that WebSocket)")
    return args


def pretty(m):
    """A compression message as one line for a person."""
    def num(value, form):
        return "  - " if value is None else form % value
    return "#%-3d rate %s/min   depth %s cm (%s)   push %s g   -> %-13s confidence %.2f%s%s" % (
        m["count"], num(m["rate_cpm"], "%5.1f"), num(m["depth_cm"], "%4.1f"), m["depth_source"],
        num(m["push_intensity_g"], "%.2f"), m["quality_full"], m["confidence"],
        "  LOW CONFIDENCE" if m["low_confidence"] else "",
        "" if m["recoil_ok"] is None else "  release ok" if m["recoil_ok"] else "  NOT RELEASED")


def loop(source, pipeline, publisher, chest=None, recorder=None, voice=None, seconds=None, led=True, show=False):
    """The main loop: everything is processed here, never in a band handler."""
    clock = ClockMap()
    started = time.monotonic()
    next_beat = started
    samples_seen = 0
    while not source.finished:
        now = time.monotonic()
        if seconds is not None and now - started >= seconds:
            break
        samples = source.poll()
        for s in samples:
            clock.see(s.t / 1000.0, s.host)
        if chest is not None:
            for distance, host in chest.drain():
                if recorder:
                    recorder.chest(host, distance)
                t_band = clock.to_band(host)
                if t_band is not None:
                    pipeline.add_chest(t_band, distance)
        reconnecting = source.reconnecting
        for s in samples:
            samples_seen += 1
            if recorder:
                recorder.band(s)
            for message in pipeline.add_sample(s.t, s.ax, s.ay, s.az, s.n, reconnecting=reconnecting,
                                               gyro_dps=s.gyro_dps):
                publisher.publish(message)
                if show:
                    print(pretty(message), flush=True)
                if voice:
                    voice.on_compression(pipeline.state, now)
                if led:
                    quality = None if message["low_confidence"] else message["quality_full"]
                    source.set_led(LED.get(quality, LED_OTHER))
        message = pipeline.update_status(source.connected, reconnecting, source.battery_percent)
        if message:
            publisher.publish(message)
        if now >= next_beat:
            next_beat = max(next_beat + config.HEARTBEAT_S, now)
            publisher.publish(pipeline.heartbeat())
        time.sleep(config.LOOP_SLEEP_S)
    return samples_seen


def main(argv=None):
    args = parse(argv)
    from .band_source import FileSource, connect_band

    chest, wants_ws_messages = (None, False) if args.arduino == "sim" else chest_input.from_spec(args.arduino)
    serial_out = args.serial_out
    if serial_out == "arduino":
        if not isinstance(chest, chest_input.SerialChestInput):
            raise SystemExit("--serial-out arduino needs --arduino serial:PORT")
        serial_out = chest
    publisher = Publisher(stdout=not (args.quiet or args.pretty), ws=args.ws, ws_port=args.ws_port, post_url=args.post, post_all=args.post_all,
                          serial_out=serial_out, on_message=chest.feed if wants_ws_messages else None)
    if args.replay:
        source = FileSource(args.replay, speed=args.speed)
    else:
        source = connect_band(args.number, sim=args.sim, sim_chest=args.arduino == "sim")
    if source.chest is not None:
        chest = source.chest
    print("Sensing from %s%s. Stop with Ctrl+C." % (source.name, " (PRETEND band: proves nothing about the real one)"
                                                     if source.sim else ""), file=sys.stderr)
    pipeline = Pipeline()
    recorder = Recorder(args.record, args.label) if args.record else None
    voice = None
    if args.voice:
        from .voice_bridge import Voice
        voice = Voice()
    samples = 0
    lost = False
    try:
        samples = loop(source, pipeline, publisher, chest, recorder, voice, args.seconds, led=not args.no_led, show=args.pretty)
    except KeyboardInterrupt:
        pass
    finally:
        lost = source.finished and not args.replay      # the band went away by itself
        source.close()
        if recorder:
            recorder.close()
            print("Saved %d rows to %s" % (recorder.rows, recorder.path), file=sys.stderr)
        if chest is not None:
            chest.close()
        time.sleep(0.2)                 # let the last messages leave
        publisher.close()
    d = pipeline.detector
    if d.gyro_seen:
        turning = sorted(d.gyro_seen)
        print("Wrist turning in counted compressions: typical %.0f, highest %.0f degrees/second (limit %.0f). "
              "Movements not counted: %d." % (turning[len(turning) // 2], turning[-1], config.GYRO_MAX_DPS,
                                              d.rejected), file=sys.stderr)
    print("Done: %d compressions, %d samples, %d lost, %d clipped%s." % (
        d.count, samples, d.total_dropped, d.total_clipped,
        ", %d Arduino readings" % chest.count if chest is not None else ", no Arduino"), file=sys.stderr)
    if lost:
        print("The band disconnected. Double-tap it and start again.", file=sys.stderr)


if __name__ == "__main__":
    main()
