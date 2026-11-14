"""Rule-based quality label, confidence, fatigue and push intensity. Pure Python."""
from collections import deque
from statistics import median

from . import config

# Priority when several apply: faster, harder, release fully, slower, lighter.


def label(rate_cpm, depth_cm, recoil_ok):
    if rate_cpm is not None and rate_cpm < config.RATE_MIN_CPM:
        return "faster"
    if depth_cm is not None and depth_cm < config.DEPTH_MIN_CM:
        return "harder"
    if recoil_ok is False:
        return "release fully"
    if rate_cpm is not None and rate_cpm > config.RATE_MAX_CPM:
        return "slower"
    if depth_cm is not None and depth_cm > config.DEPTH_MAX_CM:
        return "lighter"
    return "good"


def confidence(n_intervals=0, interval_cv=None, clipped=0, dropped=0, samples=0, depth_source="band",
               calibrated=False, reconnecting=False, has_depth=True):
    """0..1. Lower for: irregular intervals, clipped samples, dropped samples, fewer than
    3 intervals, band-only depth without calibration, a reconnecting band."""
    c = 1.0
    if n_intervals < 3:
        c -= config.PEN_FEW_INTERVALS
    if interval_cv is not None and interval_cv > config.IRREGULAR_CV_OK:
        span = config.IRREGULAR_CV_FULL - config.IRREGULAR_CV_OK
        c -= config.PEN_IRREGULAR * min(1.0, (interval_cv - config.IRREGULAR_CV_OK) / span)
    if clipped:
        c -= config.PEN_CLIPPED
    if dropped:
        lost = dropped / float(dropped + samples) if (dropped + samples) else 1.0
        c -= config.PEN_DROPPED * min(1.0, 0.5 + 5.0 * lost)
    if not has_depth:
        c -= config.PEN_NO_DEPTH
    elif depth_source == "band" and not calibrated:
        c -= config.PEN_UNCALIBRATED
    if reconnecting:
        c -= config.PEN_RECONNECTING
    return max(0.0, min(1.0, c))


class DepthSmoother:
    """Median of the last few depths, so one odd compression does not flip the label."""

    def __init__(self):
        self._recent = deque(maxlen=config.LABEL_DEPTH_WINDOW)

    def add(self, depth_cm):
        if depth_cm is not None:
            self._recent.append(depth_cm)
        return median(self._recent) if self._recent else None

    def clear(self):
        self._recent.clear()


class Fatigue:
    """Median depth and rate of the last 20 s against the first 20 s of the session."""

    def __init__(self):
        self._first = []                    # (depth, rate) in the first window
        self._recent = deque()              # (session_s, depth, rate)
        self.depth_drop = None              # fraction, e.g. 0.2 = 20 % shallower
        self.rate_change = None
        self.fatigued = False

    def add(self, session_s, depth_cm, rate_cpm):
        if depth_cm is None:
            return self.fatigued
        if session_s <= config.FATIGUE_WINDOW_S:
            self._first.append((depth_cm, rate_cpm))
        self._recent.append((session_s, depth_cm, rate_cpm))
        while self._recent and self._recent[0][0] < session_s - config.FATIGUE_WINDOW_S:
            self._recent.popleft()
        if session_s < 2 * config.FATIGUE_WINDOW_S or len(self._first) < 3 or len(self._recent) < 3:
            return self.fatigued
        first_depth = median(d for d, _ in self._first)
        last_depth = median(d for _, d, _ in self._recent)
        if first_depth > 0:
            self.depth_drop = (first_depth - last_depth) / first_depth
            self.fatigued = self.depth_drop >= config.FATIGUE_DEPTH_DROP
        first_rates = [r for _, r in self._first if r is not None]
        last_rates = [r for _, _, r in self._recent if r is not None]
        if first_rates and last_rates:
            self.rate_change = median(last_rates) - median(first_rates)
        return self.fatigued


class PushIntensity:
    """Peak downward acceleration (g) scored 0..1 against the range seen in good
    compressions. This is NOT pressure: the band has no pressure or force sensor."""

    def __init__(self):
        self._good = deque(maxlen=config.INTENSITY_HISTORY)

    def score(self, peak_g):
        if peak_g is None:
            return None
        low, high = config.INTENSITY_DEFAULT_RANGE_G
        if len(self._good) >= config.INTENSITY_MIN_GOOD:
            low, high = min(self._good), max(self._good)
        if high - low < 1e-6:
            return 0.5
        return max(0.0, min(1.0, (peak_g - low) / (high - low)))

    def learn(self, peak_g, quality_label):
        if peak_g is not None and quality_label == "good":
            self._good.append(peak_g)
