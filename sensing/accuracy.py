"""How good is the band alone? Over recordings that hold band AND Arduino data:
band-only depth against the Arduino's, plus rate and count. Real numbers only.

    python -m sensing.accuracy                    every file in recordings/
    python -m sensing.accuracy recordings/a.csv   chosen files
"""
import sys
from pathlib import Path
from statistics import mean, median

from . import config
from .pipeline import Pipeline
from .recorder import DIRECTORY, read_rows
from .run import ClockMap


def chest_cycles(readings):
    """Count pushes in the Arduino's distance alone: crossings of the middle, with a
    margin so noise is not counted. -> (count, rate per minute or None)"""
    if len(readings) < 10:
        return 0, None
    values = [d for _, d in readings]
    low, high = min(values), max(values)
    if high - low < 1.0:
        return 0, None
    middle, margin = (low + high) / 2.0, (high - low) * 0.15
    times, down = [], False
    for t, d in readings:
        pressed = (d < middle - margin) if config.CHEST_COMPRESSED_IS_SMALLER else (d > middle + margin)
        released = (d > middle + margin) if config.CHEST_COMPRESSED_IS_SMALLER else (d < middle - margin)
        if pressed and not down:
            down = True
            times.append(t)
        elif released:
            down = False
    gaps = [b - a for a, b in zip(times, times[1:]) if b - a < config.PAUSE_S]
    return len(times), (60.0 / median(gaps) if gaps else None)


def analyse(path):
    """One recording -> dict of results. The band's scale is NOT allowed to learn from
    the Arduino here: this measures the band alone, with calibration.json as it is."""
    pipeline = Pipeline(learn_scale=False)
    clock = ClockMap()
    pending, chest, pairs, rates = [], [], [], []
    label = None
    for kind, item, row_label in read_rows(path):
        label = label or row_label
        if kind == "chest":
            pending.append(item)
            continue
        clock.see(item.t / 1000.0, item.host if item.host is not None else item.t / 1000.0)
        for distance, host in pending:
            t_band = clock.to_band(host)
            pipeline.add_chest(t_band, distance)
            chest.append((t_band, distance))
        pending = []
        for message in pipeline.add_sample(item.t, item.ax, item.ay, item.az, item.n, gyro_dps=item.gyro_dps):
            fused = pipeline.last_fused
            if message["rate_cpm"] is not None:
                rates.append(message["rate_cpm"])
            if fused.band_depth_cm is not None and fused.arduino_depth_cm is not None:
                pairs.append((fused.band_depth_cm, fused.arduino_depth_cm))
    chest_count, chest_rate = chest_cycles(chest)
    result = dict(path=str(path), label=label, count=pipeline.detector.count, rate=median(rates) if rates else None,
                  chest_readings=len(chest), chest_count=chest_count, chest_rate=chest_rate, pairs=len(pairs),
                  lost=pipeline.detector.total_dropped, clipped=pipeline.detector.total_clipped,
                  scale=pipeline.fusion.scale, calibrated=pipeline.fusion.calibrated)
    if pairs:
        errors = [b - a for b, a in pairs]
        ratios = [a / b for b, a in pairs if b > 0.5]
        best = median(ratios) if ratios else None
        result.update(
            arduino_depth=median(a for _, a in pairs), band_depth=median(b for b, _ in pairs),
            bias=mean(errors), mae=mean(abs(e) for e in errors), worst=max(abs(e) for e in errors),
            best_scale=best,
            mae_best=mean(abs(b * best - a) for b, a in pairs) if best else None)
    return result


def report(results, out=sys.stdout):
    w = out.write
    for r in results:
        w("\n%s%s\n" % (r["path"], "  [%s]" % r["label"] if r["label"] else ""))
        w("  band:    %d compressions, median rate %s per minute, %d samples lost, %d clipped\n"
          % (r["count"], "%.1f" % r["rate"] if r["rate"] else "-", r["lost"], r["clipped"]))
        if not r["chest_readings"]:
            w("  Arduino: no readings in this file, so there is nothing to compare the depth with.\n")
            continue
        w("  Arduino: %d readings, %d pushes counted, rate %s per minute\n"
          % (r["chest_readings"], r["chest_count"], "%.1f" % r["chest_rate"] if r["chest_rate"] else "-"))
        w("  count difference (band - Arduino): %+d   (the Arduino count is a rough check: it misses pushes much "
          "shallower than the deepest in the file)\n" % (r["count"] - r["chest_count"]))
        if not r["pairs"]:
            w("  depth: no compression had both a band and an Arduino depth.\n")
            continue
        w("  depth over %d compressions: Arduino median %.2f cm, band-only median %.2f cm (scale %.3f, %s)\n"
          % (r["pairs"], r["arduino_depth"], r["band_depth"], r["scale"],
             "from calibration.json" if r["calibrated"] else "UNCALIBRATED"))
        w("  band-only error: mean %+.2f cm, mean absolute %.2f cm, worst %.2f cm\n" % (r["bias"], r["mae"], r["worst"]))
        if r["best_scale"]:
            w("  with the best single scale for this file (%.3f): mean absolute error %.2f cm\n"
              % (r["best_scale"], r["mae_best"]))
    with_depth = [r for r in results if r.get("pairs")]
    if len(with_depth) > 1:
        total = sum(r["pairs"] for r in with_depth)
        w("\nAll %d files with both: mean absolute band-only depth error %.2f cm over %d compressions\n"
          % (len(with_depth), sum(r["mae"] * r["pairs"] for r in with_depth) / total, total))


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    paths = [Path(a) for a in argv] or sorted(DIRECTORY.glob("*.csv"))
    if not paths:
        print("There are no recordings yet (%s is empty or missing), so there are no accuracy numbers.\n"
              "Record some with:  python -m sensing.run <band number> --arduino ... --record NAME --label good"
              % DIRECTORY)
        return
    report([analyse(path) for path in paths])


if __name__ == "__main__":
    main()
