from statistics import median

import pytest

from sensing import config, quality
from sensing.detector import Detector, SessionTracker
from sensing.tests import synth


def run(samples, **kw):
    detector = Detector(**kw)
    events = [e for e in (detector.add(*s) for s in samples) if e]
    return detector, events


def settled(events):
    """Skip the first compressions: the first has no full cycle yet."""
    return events[3:]


@pytest.mark.parametrize("rate,depth", [(80, 3.5), (110, 5.5), (140, 4.5)])
def test_rate_depth_count(rate, depth):
    samples, _ = synth.compressions(rate, depth, count=30)
    _, events = run(samples)
    assert events[-1].count == 30
    for e in settled(events):
        assert abs(e.rate_cpm - rate) <= 3
        assert abs(e.depth_raw_cm - depth) <= 0.5
    assert abs(median(e.depth_raw_cm for e in settled(events)) - depth) <= 0.2


@pytest.mark.parametrize("gravity", [(1, 0, 0), (0, -1, 0), (0.6, 0.5, 0.62), (-0.3, 0.8, -0.5)])
def test_tilted_wrist(gravity):
    samples, _ = synth.compressions(110, 5.5, count=30, gravity=gravity)
    _, events = run(samples)
    assert events[-1].count == 30          # exact count (the first pushes are confirmed together)
    for e in settled(events):
        assert abs(e.rate_cpm - 110) <= 3
        assert abs(e.depth_raw_cm - 5.5) <= 0.5


@pytest.mark.parametrize("rate,depth", [(80, 3.5), (110, 5.5), (140, 4.5)])
def test_noise(rate, depth):
    # 0.01 g of white noise on every axis: about five times this sensor's own noise.
    # (At 0.02 g single cycles are off by up to 0.55 cm: double integration amplifies noise.)
    samples, _ = synth.compressions(rate, depth, count=30, noise_g=0.01)
    _, events = run(samples)
    assert events[-1].count == 30          # exact count (the first pushes are confirmed together)
    for e in settled(events):
        assert abs(e.rate_cpm - rate) <= 3
        assert abs(e.depth_raw_cm - depth) <= 0.5


def test_pause_three_seconds():
    samples, _ = synth.join(synth.compressions(110, 5.5, count=15, tail_s=3.0),
                            synth.compressions(110, 5.5, count=15, lead_s=0.0))
    detector = Detector()
    tracker = SessionTracker()
    events, pauses = [], 0
    for s in samples:
        e = detector.add(*s)
        if e:
            if e.run_start_ms is not None:
                tracker.on_compression(e.run_start_ms / 1000.0)
            tracker.on_compression(e.t_ms / 1000.0)
            events.append(e)
        if tracker.update(s[0] / 1000.0):
            pauses += 1
            detector.reset_timing()
    assert events[-1].count == 30
    assert pauses == 1                                   # the 3 s gap
    before = [e for e in events if e.count <= 15]
    after = [e for e in events if e.count > 15]
    assert before[-1].count == 15 and after[0].count == 19      # 16 to 19 confirmed together
    assert after[0].run_start_ms is not None
    for e in after[2:]:
        assert abs(e.rate_cpm - 110) <= 3
        assert abs(e.depth_raw_cm - 5.5) <= 0.5
    end = samples[-1][0] / 1000.0
    gap = after[0].run_start_ms / 1000.0 - before[-1].t_ms / 1000.0
    assert 3.0 < gap < 4.2
    assert tracker.hands_off_s(after[3].t_ms / 1000.0) == pytest.approx(gap)
    assert tracker.session_s(end) == pytest.approx(end - events[0].run_start_ms / 1000.0)


def test_dropped_samples():
    samples, _ = synth.compressions(110, 5.5, count=30)
    kept = [s for s in samples if not (s[4] % 97 in (0, 1, 2, 3))]       # bursts of 4 lost samples
    detector, events = run(kept)
    assert events[-1].count == 30          # exact count (the first pushes are confirmed together)
    assert detector.total_dropped == len(samples) - len(kept) - 4      # the first 4 were lost before the first sample
    assert sum(e.dropped for e in events) > 0
    for e in settled(events):
        assert abs(e.rate_cpm - 110) <= 3
        assert abs(e.depth_raw_cm - 5.5) <= 0.5


def test_clipping_is_flagged():
    samples, _ = synth.compressions(120, 6.0, count=10)
    detector, events = run(samples, accel_range_g=1.2)       # a range the signal exceeds
    assert detector.total_clipped > 0
    assert any(e.clipped for e in events)


def test_still_band_counts_nothing():
    samples, _ = synth.compressions(110, 5.5, count=0, lead_s=10, noise_g=0.02)
    _, events = run(samples)
    assert events == []


def test_push_intensity_peak():
    samples, _ = synth.compressions(110, 5.5, count=20)
    _, events = run(samples)
    expected = 0.0275 * (2 * 3.14159265 * 110 / 60) ** 2 / 9.80665
    for e in settled(events):
        assert e.peak_down_g == pytest.approx(expected, rel=0.08)


# ---- quality ----

def test_label_priority():
    assert quality.label(110, 5.5, True) == "good"
    assert quality.label(110, 5.5, None) == "good"
    assert quality.label(90, 3.0, False) == "faster"            # faster wins over everything
    assert quality.label(130, 3.0, False) == "harder"           # harder before release and slower
    assert quality.label(130, 7.0, False) == "release fully"
    assert quality.label(130, 7.0, True) == "slower"
    assert quality.label(110, 7.0, True) == "lighter"
    assert quality.label(None, None, None) == "good"


def test_confidence_rules():
    full = quality.confidence(n_intervals=5, interval_cv=0.02, depth_source="arduino", samples=55)
    assert full == 1.0
    assert quality.confidence(n_intervals=2, depth_source="arduino") < full
    assert quality.confidence(n_intervals=5, interval_cv=0.4, depth_source="arduino") < full
    assert quality.confidence(n_intervals=5, clipped=3, depth_source="arduino") < full
    assert quality.confidence(n_intervals=5, dropped=4, samples=50, depth_source="arduino") < full
    assert quality.confidence(n_intervals=5, depth_source="band", calibrated=False) < full
    assert quality.confidence(n_intervals=5, depth_source="band", calibrated=True) == full
    assert quality.confidence(n_intervals=5, depth_source="arduino", reconnecting=True) < config.LOW_CONFIDENCE_BELOW
    assert quality.confidence(n_intervals=1, depth_source="band", calibrated=False) < config.LOW_CONFIDENCE_BELOW


def test_fatigue_flag():
    tired, steady = quality.Fatigue(), quality.Fatigue()
    for i in range(110):
        s = i * 0.55
        tired.add(s, 5.5 if s < 25 else 4.4, 110)        # 20 % shallower later
        steady.add(s, 5.5 if s < 25 else 5.2, 110)       # 5 % shallower: not fatigue
    assert tired.fatigued and tired.depth_drop == pytest.approx(0.2)
    assert not steady.fatigued
    early = quality.Fatigue()
    for i in range(30):
        early.add(i * 0.55, 5.5 - i * 0.05, 110)         # under 40 s: never flagged
    assert not early.fatigued


def test_push_intensity_score():
    push = quality.PushIntensity()
    low, high = config.INTENSITY_DEFAULT_RANGE_G
    assert push.score(low) == 0.0 and push.score(high) == 1.0
    for g in (0.30, 0.32, 0.34, 0.36, 0.40):
        push.learn(g, "good")
    push.learn(0.9, "harder")                            # not a good compression: ignored
    assert push.score(0.35) == pytest.approx(0.5)
    assert push.score(1.0) == 1.0 and push.score(0.1) == 0.0
    assert push.score(None) is None


def test_swap_timer():
    tracker = SessionTracker()
    tracker.on_compression(10.0)
    assert tracker.swap_in(10.0) == config.SWAP_S
    assert tracker.swap_in(70.0) == 60.0
    assert tracker.swap_in(200.0) == 0.0
    tracker.on_compression(131.0)
    tracker.update(134.0)
    assert tracker.paused
    tracker.on_compression(136.0)                        # back after a 5 s swap pause
    assert tracker.swap_in(136.0) == config.SWAP_S


# ---- movements that are not compressions ----

def test_random_arm_movement_is_not_counted():
    import math
    import random
    rng = random.Random(3)
    detector = Detector()
    t, n, counted = 1000.0, 0, 0
    for burst in range(40):                              # single jerks at uneven moments
        for i in range(int(rng.uniform(40, 260))):       # still for 0.4 to 2.6 s
            counted += detector.add(t, 0.0, 0.0, 1.0, n) is not None
            t, n = t + 10, n + 1
        length = rng.choice((12, 20, 45, 70))
        size = rng.uniform(0.2, 0.7)
        for i in range(length):
            a = size * math.sin(2 * math.pi * i / length)
            counted += detector.add(t, 0.0, 0.0, 1.0 - a, n) is not None
            t, n = t + 10, n + 1
    assert detector.count == 0, detector.count
    assert detector.rejected > 0


def test_turning_the_wrist_is_not_counted():
    """Putting the band on: rhythmic acceleration, but the wrist turns fast."""
    samples, _ = synth.compressions(110, 5.5, count=20)
    detector = Detector()
    events = [e for e in (detector.add(*s, gyro_dps=400.0) for s in samples) if e]
    assert events == [] and detector.count == 0
    detector = Detector()
    events = [e for e in (detector.add(*s, gyro_dps=40.0) for s in samples) if e]
    assert events[-1].count == 20


def test_rhythm_lost_stops_counting():
    samples, _ = synth.join(synth.compressions(110, 5.5, count=10, tail_s=0.0),
                            synth.compressions(190, 1.2, count=3, lead_s=0.0, tail_s=0.3),
                            synth.compressions(55, 3.0, count=2, lead_s=0.0, tail_s=1.0))
    detector = Detector()
    events = [e for e in (detector.add(*s) for s in samples) if e]
    assert 10 <= events[-1].count <= 12                  # the mess afterwards adds at most a couple
