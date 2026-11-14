"""Compression detection from wrist acceleration. Pure Python: no band, no network.

Feed samples one by one (t in ms, ax ay az in g). Each detected compression is returned
as a Compression. Timing always comes from the sample's own `t`.
"""
import math
from collections import deque
from dataclasses import dataclass
from statistics import median

from . import config


@dataclass
class Compression:
    count: int
    t_ms: float                 # time of the upward zero crossing (band clock)
    interval_s: float = None    # time since the previous compression (None after a pause)
    rate_cpm: float = None      # 60 / median of the last intervals (None with no interval yet)
    n_intervals: int = 0        # intervals the rate is based on
    interval_cv: float = None   # std / mean of those intervals (irregularity)
    depth_raw_cm: float = None  # band depth before the calibration scale (None = no full cycle)
    peak_down_g: float = None   # largest downward acceleration in the cycle, in g (positive number)
    cycle_start_ms: float = None
    clipped: int = 0            # samples in the cycle that hit the sensor's range
    dropped: int = 0            # samples lost in the cycle (from the sample numbers)
    samples: int = 0
    gyro_dps: float = None      # mean turning speed of the wrist in the cycle
    run_start_ms: float = None  # set on the compression that confirms a rhythm: when that run began


def cycle_depth_cm(times_s, accel_g):
    """Peak-to-peak travel of one cycle in cm: remove the mean acceleration, integrate to
    velocity, remove the mean velocity, integrate to position. Starting from zero in every
    cycle is what keeps drift out."""
    n = len(times_s)
    if n < 4:
        return None
    total = times_s[-1] - times_s[0]
    if total <= 0:
        return None

    def integral(values):               # trapezoid, with the real time steps
        out = [0.0] * n
        for i in range(1, n):
            out[i] = out[i - 1] + 0.5 * (values[i] + values[i - 1]) * (times_s[i] - times_s[i - 1])
        return out

    a_mean = integral(accel_g)[-1] / total
    velocity = integral([a - a_mean for a in accel_g])
    v_mean = integral(velocity)[-1] / total
    position = integral([v - v_mean for v in velocity])
    return (max(position) - min(position)) * config.G_MS2 * 100.0


class Detector:
    def __init__(self, accel_range_g=config.ACCEL_RANGE_G, min_peak_g=config.MIN_PEAK_G,
                 refractory_s=config.REFRACTORY_S):
        self.min_peak = min_peak_g
        self.refractory = refractory_s
        self.clip_level = accel_range_g * config.CLIP_FRACTION
        self.count = 0
        self.total_dropped = 0
        self.total_clipped = 0
        self.vertical_g = 0.0           # latest vertical acceleration (up is positive, gravity removed)
        self._gravity = None
        self._warm = 0.0                # seconds of data in the gravity estimate
        self._last_t = None
        self._last_n = None
        self._smooth = 0.0
        self._prev_smooth = 0.0
        self._prev_t = None
        self._armed_at = None           # time the signal was last below -min_peak
        self._pending = None            # crossing time waiting for confirmation
        self._last_cross = None
        self._intervals = deque(maxlen=config.RATE_INTERVALS)
        self._cycle_t = []              # samples since the last counted crossing
        self._cycle_a = []
        self._cycle_clipped = 0
        self._cycle_dropped = 0
        self._cycle_valid = False
        self._cycle_gyro = 0.0
        self._cycle_gyro_n = 0
        # Rhythm lock: nothing is counted until a few evenly spaced pushes in a row were
        # seen, so putting the band on or waving the arm is not counted.
        self.locked = False
        self.rejected = 0               # crossings that were not counted
        self.gyro_seen = []             # mean turning speed of counted cycles (for tuning)
        self._streak = 0                # candidate crossings in a row
        self._streak_start = None
        self._cand_interval = None
        self._bad = 0

    # ---- gravity and vertical acceleration ----
    def _vertical(self, t_s, ax, ay, az, dt):
        if self._gravity is None:
            self._gravity = [ax, ay, az]
        else:
            self._warm += dt
            # running mean while warming up, then a slow low-pass
            tau = min(config.GRAVITY_TAU_S, max(self._warm, dt))
            alpha = min(1.0, dt / (tau + dt)) if tau > 0 else 1.0
            g = self._gravity
            g[0] += alpha * (ax - g[0])
            g[1] += alpha * (ay - g[1])
            g[2] += alpha * (az - g[2])
        gx, gy, gz = self._gravity
        norm = math.sqrt(gx * gx + gy * gy + gz * gz)
        if norm < 1e-6:
            return 0.0
        return (ax * gx + ay * gy + az * gz) / norm - norm

    def reset_timing(self):
        """Forget the rhythm (after a pause or a reconnect). The count stays."""
        self._intervals.clear()
        self._last_cross = None
        self._armed_at = None
        self._pending = None
        self._cycle_t, self._cycle_a = [], []
        self._cycle_clipped = self._cycle_dropped = 0
        self._cycle_valid = False
        self._cycle_gyro, self._cycle_gyro_n = 0.0, 0
        if not self.locked:
            self.rejected += self._streak
        self.locked = False
        self._streak = 0
        self._cand_interval = None
        self._bad = 0

    def add(self, t_ms, ax, ay, az, n=None, gyro_dps=None):
        """One sample in; a Compression out when one was detected, else None."""
        t_s = t_ms / 1000.0
        if self._last_t is not None and t_s <= self._last_t:
            if self._last_t - t_s > 1.0:        # the band restarted: its clock began again
                self.reset_timing()
                self._last_t = None
                self._prev_t = None
            else:
                return None
        dt = (t_s - self._last_t) if self._last_t is not None else 1.0 / config.MOTION_RATE_HZ
        if dt > config.PAUSE_S:                 # a hole in the data (link drop)
            self.reset_timing()
            dt = 1.0 / config.MOTION_RATE_HZ
        self._last_t = t_s

        dropped = 0
        if n is not None and self._last_n is not None and n > self._last_n + 1:
            dropped = n - self._last_n - 1
            self.total_dropped += dropped
        if n is not None:
            self._last_n = n
        clipped = 1 if max(abs(ax), abs(ay), abs(az)) >= self.clip_level else 0
        self.total_clipped += clipped

        a = self._vertical(t_s, ax, ay, az, dt)
        self.vertical_g = a
        alpha = min(1.0, dt / (dt + 1.0 / (2 * math.pi * config.SMOOTH_CUTOFF_HZ)))
        self._prev_smooth = self._smooth
        self._smooth += alpha * (a - self._smooth)
        prev_t, self._prev_t = self._prev_t, t_s

        self._cycle_t.append(t_s)
        self._cycle_a.append(a)
        self._cycle_clipped += clipped
        self._cycle_dropped += dropped
        if gyro_dps is not None:
            self._cycle_gyro += gyro_dps
            self._cycle_gyro_n += 1
        if len(self._cycle_t) > 4 * config.MOTION_RATE_HZ * config.MAX_CYCLE_S:   # hands off: do not grow
            self._cycle_t, self._cycle_a = self._cycle_t[-2:], self._cycle_a[-2:]
            self._cycle_clipped = self._cycle_dropped = 0
            self._cycle_gyro, self._cycle_gyro_n = 0.0, 0
            self._cycle_valid = False

        s, p = self._smooth, self._prev_smooth
        if s <= -self.min_peak:
            self._armed_at = t_s
            self._pending = None
        elif self._armed_at is not None and t_s - self._armed_at > config.ARM_TIMEOUT_S:
            self._armed_at = None
            self._pending = None
        if self._armed_at is not None and self._pending is None and p < 0.0 <= s and prev_t is not None:
            # where between the two samples the signal crossed zero
            self._pending = prev_t + (t_s - prev_t) * (-p / (s - p)) if s != p else t_s
        if self._pending is not None and s >= self.min_peak * config.CONFIRM_FRACTION:
            cross = self._pending
            self._pending = None
            self._armed_at = None
            if self._last_cross is None or cross - self._last_cross >= self.refractory:
                return self._count(cross)
        return None

    def _count(self, cross_s):
        event = Compression(count=0, t_ms=cross_s * 1000.0)
        # the cycle that just ended: samples up to the crossing
        split = len(self._cycle_t)
        while split > 0 and self._cycle_t[split - 1] > cross_s:
            split -= 1
        times, accel = self._cycle_t[:split], self._cycle_a[:split]
        rest_t, rest_a = self._cycle_t[split:], self._cycle_a[split:]
        if times and rest_t and times[-1] < cross_s < rest_t[0]:
            # put a point exactly at the crossing, so every cycle runs from crossing to
            # crossing even when samples around it were lost
            f = (cross_s - times[-1]) / (rest_t[0] - times[-1])
            a_cross = accel[-1] + f * (rest_a[0] - accel[-1])
            times, accel = times + [cross_s], accel + [a_cross]
            rest_t, rest_a = [cross_s] + rest_t, [a_cross] + rest_a
        if self._last_cross is not None:
            interval = cross_s - self._last_cross
            event.interval_s = interval
            event.cycle_start_ms = self._last_cross * 1000.0
            if self._cycle_valid and interval <= config.MAX_CYCLE_S and accel:
                event.depth_raw_cm = cycle_depth_cm(times, accel)
                event.peak_down_g = max(0.0, -min(accel))
            event.clipped = self._cycle_clipped
            event.dropped = self._cycle_dropped
            event.samples = len(times)
            if self._cycle_gyro_n:
                event.gyro_dps = self._cycle_gyro / self._cycle_gyro_n
        self._last_cross = cross_s
        self._cycle_t, self._cycle_a = rest_t, rest_a
        self._cycle_clipped = self._cycle_dropped = 0
        self._cycle_gyro, self._cycle_gyro_n = 0.0, 0
        self._cycle_valid = True
        if not self._accept(event, cross_s):
            return None
        if event.interval_s is not None:
            self._intervals.append(event.interval_s)
        if event.gyro_dps is not None:
            self.gyro_seen.append(event.gyro_dps)
        if self._intervals:
            values = list(self._intervals)
            event.rate_cpm = 60.0 / median(values)
            event.n_intervals = len(values)
            if len(values) >= 2:
                mean = sum(values) / len(values)
                var = sum((v - mean) ** 2 for v in values) / len(values)
                event.interval_cv = math.sqrt(var) / mean if mean > 0 else None
        return event

    def _accept(self, event, cross_s):
        """Rhythm lock. Returns True when this crossing counts as a compression."""
        interval = event.interval_s
        calm = event.gyro_dps is None or event.gyro_dps <= config.GYRO_MAX_DPS
        in_range = interval is not None and config.MIN_INTERVAL_S <= interval <= config.MAX_INTERVAL_S
        if self.locked:
            usual = median(self._intervals) if self._intervals else interval
            odd = not (in_range and calm) or abs(interval - usual) > config.LOCKED_TOLERANCE * usual
            if not odd:
                self._bad = 0
            else:
                self._bad += 1
                if self._bad >= config.UNLOCK_AFTER_ODD:      # the rhythm is gone: not CPR any more
                    self.locked = False
                    self._intervals.clear()
                    self._streak, self._streak_start, self._cand_interval = 1, cross_s, None
                    self.rejected += 1
                    return False
            self.count += 1
            event.count = self.count
            return True
        deep = event.depth_raw_cm is not None and event.depth_raw_cm >= config.LOCK_MIN_DEPTH_CM
        even = self._cand_interval is None or (
            interval is not None and abs(interval - self._cand_interval) <= config.LOCK_TOLERANCE * self._cand_interval)
        if self._streak >= 1 and in_range and calm and deep and even:
            self._streak += 1
            self._cand_interval = interval
            if self._streak >= config.LOCK_CROSSINGS:
                self.locked = True
                self._bad = 0
                self.count += self._streak              # the pushes that proved the rhythm count too
                event.count = self.count
                event.run_start_ms = self._streak_start * 1000.0
                return True
            self._intervals.append(interval)
            return False
        self.rejected += self._streak
        self._streak, self._streak_start, self._cand_interval = 1, cross_s, None
        self._intervals.clear()
        return False


class SessionTracker:
    """Session time, hands-off time, pause state and the 2-minute swap timer. Times in
    seconds on the band clock."""

    def __init__(self):
        self.start = None
        self.last_compression = None
        self.paused = True              # hands are off until the first compression
        self.hands_off_closed = 0.0     # pauses that are over
        self._swap_start = None
        self._pause_began = None

    def on_compression(self, t_s):
        """Returns True when this compression ends a pause (the rhythm starts afresh)."""
        resumed = False
        if self.start is None:
            self.start = t_s
            self._swap_start = t_s
            resumed = True
        elif self.paused and self.last_compression is not None:
            gap = t_s - self.last_compression
            self.hands_off_closed += gap
            if self.swap_in(self.last_compression + config.PAUSE_S) <= 0 and gap >= config.SWAP_RESET_PAUSE_S:
                self._swap_start = t_s          # the rescuers swapped: start the 2 minutes again
            resumed = True
        self.paused = False
        self.last_compression = t_s
        return resumed

    def update(self, t_s):
        """Call with the current band time. Returns True when a pause begins now."""
        if not self.paused and self.last_compression is not None and t_s - self.last_compression >= config.PAUSE_S:
            self.paused = True
            return True
        return False

    def session_s(self, t_s):
        return 0.0 if self.start is None else max(0.0, t_s - self.start)

    def hands_off_s(self, t_s):
        open_pause = (t_s - self.last_compression) if (self.paused and self.last_compression is not None) else 0.0
        return self.hands_off_closed + max(0.0, open_pause)

    def swap_in(self, t_s):
        if self._swap_start is None:
            return None
        return max(0.0, config.SWAP_S - (t_s - self._swap_start))
