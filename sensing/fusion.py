"""Combine the band with the Arduino under the body. Pure Python.

Rules:
  - rate, timing and count always come from the band (detector.py)
  - depth: the Arduino's peak-to-peak distance change in the cycle when its data is fresh
    (under 0.5 s old), else the band's own estimate. depth_source says which.
  - while both are there, the band's calibration scale follows the Arduino (slow running
    median), so the band alone stays accurate when the Arduino drops out
  - recoil: with the Arduino, did the distance come back to its resting value between
    pushes? Without the Arduino: None. Never a guess.
All times are seconds on one clock (the band's).
"""
from collections import deque
from dataclasses import dataclass
from statistics import median

from . import config


@dataclass
class Fused:
    depth_cm: float = None
    depth_source: str = "band"
    recoil_ok: bool = None
    band_depth_cm: float = None         # band estimate with the scale in use
    arduino_depth_cm: float = None
    calibrated: bool = False            # was the band scale calibrated (file or Arduino)?


class Fusion:
    def __init__(self, scale=config.DEFAULT_DEPTH_SCALE, calibrated=False, learn=True):
        self.scale = scale
        self.calibrated = calibrated
        self.learn = learn
        self.paused = True                  # set by the pipeline: hands off (rest is learnt then)
        self.rest_cm = None
        self._readings = deque(maxlen=4000)     # (t_s, distance_cm)
        self._quiet = deque(maxlen=config.REST_WINDOW)   # readings while the hands are off
        self._ratios = deque(maxlen=config.SCALE_WINDOW)
        self._releases = deque(maxlen=10)       # release-side extreme of recent cycles

    def add_chest(self, t_s, distance_cm):
        self._readings.append((t_s, distance_cm))
        while self._readings and self._readings[0][0] < t_s - 10.0:
            self._readings.popleft()
        if self.paused:
            self._quiet.append(distance_cm)
            # only a distance that holds still is a resting distance (the first pushes of a
            # run arrive before the band has confirmed them)
            if len(self._quiet) >= config.REST_MIN_READINGS and \
                    max(self._quiet) - min(self._quiet) <= config.RECOIL_TOLERANCE_CM:
                self.rest_cm = median(self._quiet)

    def arduino_ok(self, now_s):
        return bool(self._readings) and now_s - self._readings[-1][0] < config.CHEST_FRESH_S

    def set_paused(self, paused):
        if paused and not self.paused:
            self._quiet.clear()             # learn the rest distance afresh in every pause
        self.paused = paused

    def fuse(self, event, now_s):
        """event: detector.Compression. now_s: band time now."""
        out = Fused()
        if event.depth_raw_cm is not None:
            out.band_depth_cm = event.depth_raw_cm * self.scale

        fresh = self.arduino_ok(now_s)
        window = None
        if fresh and event.cycle_start_ms is not None and event.interval_s is not None \
                and event.interval_s <= config.MAX_CYCLE_S:
            start, end = event.cycle_start_ms / 1000.0, event.t_ms / 1000.0
            window = [d for t, d in self._readings if start <= t <= end]
            if len(window) < config.CHEST_MIN_READINGS:
                window = None
        if window:
            out.arduino_depth_cm = max(window) - min(window)
            release = max(window) if config.CHEST_COMPRESSED_IS_SMALLER else min(window)
            out.recoil_ok = self._recoil(release)
            if self.learn and event.depth_raw_cm and event.depth_raw_cm > 0.5 and out.arduino_depth_cm > 0.5:
                ratio = out.arduino_depth_cm / event.depth_raw_cm
                if config.SCALE_MIN <= ratio <= config.SCALE_MAX:
                    self._ratios.append(ratio)
                    if len(self._ratios) >= config.SCALE_MIN_SAMPLES:
                        self.scale = median(self._ratios)
                        self.calibrated = True

        if fresh:
            # The Arduino is the truth while it is there. No full cycle of its data yet
            # (first push after a pause): no depth for this one, not a guess.
            out.depth_source = "arduino"
            out.depth_cm = out.arduino_depth_cm
        else:
            out.depth_source = "band"
            out.depth_cm = out.band_depth_cm
        out.calibrated = self.calibrated
        return out

    def _recoil(self, release):
        rest = self.rest_cm
        if rest is None:
            # no quiet moment seen yet: compare with the best release of the last cycles
            self._releases.append(release)
            if len(self._releases) < 3:
                return None
            rest = max(self._releases) if config.CHEST_COMPRESSED_IS_SMALLER else min(self._releases)
        short = (rest - release) if config.CHEST_COMPRESSED_IS_SMALLER else (release - rest)
        return short <= config.RECOIL_TOLERANCE_CM
