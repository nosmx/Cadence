"""Guided calibration. Results go to sensing/calibration.json.

    python -m sensing.calibrate 27 depth          only needed without the Arduino
        Do 20 compressions to a depth you measured with a ruler, then type the centimetres.
    python -m sensing.calibrate 27 force          optional
        Push to a known force a few times (for example a scale under the pillow) and type
        the kilograms. Fits force = k * depth; messages then carry force_kg_est, an ESTIMATE.

Add --sim to try it with the pretend band, --arduino ... as in sensing.run.
"""
import argparse
import sys
import time
from statistics import median

from . import calibration, chest_input, config
from .pipeline import Pipeline
from .run import ClockMap, band_number


def say(text):
    print(text, file=sys.stderr, flush=True)


def collect(source, pipeline, chest, want, until_pause=False, timeout_s=120.0):
    """Feed the pipeline until `want` compressions with a depth were seen (or, with
    until_pause, until the hands come off after at least `want`). Returns their
    (band raw depth, reported depth) pairs."""
    clock = ClockMap()
    got = []
    start = time.monotonic()
    while not source.finished and time.monotonic() - start < timeout_s:
        samples = source.poll()
        for s in samples:
            clock.see(s.t / 1000.0, s.host)
        if chest is not None:
            for distance, host in chest.drain():
                t_band = clock.to_band(host)
                if t_band is not None:
                    pipeline.add_chest(t_band, distance)
        for s in samples:
            for message in pipeline.add_sample(s.t, s.ax, s.ay, s.az, s.n, gyro_dps=s.gyro_dps):
                raw = pipeline.last_event.depth_raw_cm
                if raw is not None:
                    got.append((raw, message["depth_cm"]))
                    say("  %d" % len(got))
        if len(got) >= want and (not until_pause or pipeline.tracker.paused):
            return got
        time.sleep(config.LOOP_SLEEP_S)
    return got


def ask_number(question, given=None):
    if given is not None:
        return given
    while True:
        try:
            value = float(input(question).replace(",", "."))
            if value > 0:
                return value
        except ValueError:
            pass
        say("Type a number above 0.")


def depth(source, chest, count, cm=None):
    say("Depth calibration. Do %d compressions to ONE depth you measured with a ruler." % count)
    pairs = collect(source, Pipeline(calib={}, learn_scale=False), chest, count)
    if len(pairs) < count:
        raise SystemExit("Only %d compressions were seen. Nothing was saved." % len(pairs))
    raw = median(r for r, _ in pairs)
    cm = ask_number("How deep were they, in centimetres? ", cm)
    scale = cm / raw
    if not config.SCALE_MIN <= scale <= config.SCALE_MAX:
        raise SystemExit("The band saw %.1f cm and you typed %.1f cm: that is too far apart (scale %.2f). "
                         "Nothing was saved." % (raw, cm, scale))
    calibration.save({calibration.DEPTH_SCALE: round(scale, 4)})
    say("Band alone saw %.2f cm, you measured %.2f cm: scale %.3f saved to %s" % (raw, cm, scale, calibration.PATH))


def force(source, chest, pushes, kg=None):
    say("Force calibration (an estimate, not a measurement of pressure).")
    pipeline = Pipeline(learn_scale=True)
    pairs = []
    for i in range(pushes):
        say("Round %d of %d: do 5 or more compressions to the same force, watch the scale, then lift your hands." % (i + 1, pushes))
        got = collect(source, pipeline, chest, 5, until_pause=True)
        depths = [d for _, d in got if d is not None]
        if len(depths) < 3:
            raise SystemExit("Too few compressions were seen. Nothing was saved.")
        d = median(depths)
        pairs.append((d, ask_number("Depth was %.1f cm. What did the scale show, in kg? " % d, kg and kg[i])))
    k = calibration.fit_force(pairs)
    if not k:
        raise SystemExit("Could not fit a force factor. Nothing was saved.")
    calibration.save({calibration.FORCE_K: round(k, 3)})
    say("force_kg_est = %.2f kg per cm of depth, saved to %s" % (k, calibration.PATH))


def main(argv=None):
    p = argparse.ArgumentParser(prog="python -m sensing.calibrate", description=__doc__.split("\n")[0])
    p.add_argument("number", type=band_number, help="your band number (on the bag)")
    p.add_argument("mode", choices=("depth", "force"))
    p.add_argument("--sim", action="store_true")
    p.add_argument("--arduino", metavar="HOW")
    p.add_argument("--count", type=int, default=20, help="compressions for the depth calibration")
    p.add_argument("--pushes", type=int, default=3, help="rounds for the force calibration")
    p.add_argument("--cm", type=float, help="the measured depth (skips the question)")
    p.add_argument("--kg", type=float, nargs="+", help="the forces (skips the questions)")
    args = p.parse_args(argv)
    if args.kg and len(args.kg) != args.pushes:
        p.error("--kg needs one number for each of the %d rounds" % args.pushes)
    from .band_source import connect_band
    chest, _ = (None, False) if args.arduino == "sim" else chest_input.from_spec(args.arduino)
    source = connect_band(args.number, sim=args.sim, sim_chest=args.arduino == "sim")
    chest = source.chest or chest
    try:
        if args.mode == "depth":
            depth(source, chest, args.count, args.cm)
        else:
            force(source, chest, args.pushes, args.kg)
    except KeyboardInterrupt:
        say("Stopped. Nothing was saved.")
    finally:
        source.close()
        if chest is not None:
            chest.close()


if __name__ == "__main__":
    main()
