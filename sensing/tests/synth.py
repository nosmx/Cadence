"""Synthetic compression signals for the tests."""
import math
import random

G = 9.80665


def compressions(rate_cpm, depth_cm, count, fs=100.0, t0_ms=1000.0, lead_s=3.0, tail_s=1.0,
                 gravity=(0.0, 0.0, 1.0), noise_g=0.0, seed=7):
    """Samples (t_ms, ax, ay, az, n) of `count` sine compressions: the chest goes down by
    depth_cm and comes back, along the gravity direction. Also returns the true chest
    position (cm, 0 = rest, negative = pushed down) for each sample."""
    rng = random.Random(seed)
    period = 60.0 / rate_cpm
    omega = 2 * math.pi / period
    half = depth_cm / 100.0 / 2.0
    norm = math.sqrt(sum(c * c for c in gravity))
    up = [c / norm for c in gravity]
    samples, position = [], []
    total = lead_s + count * period + tail_s
    for i in range(int(round(total * fs))):
        s = i / fs
        tau = s - lead_s
        if 0.0 <= tau < count * period:
            x = -half * (1 - math.cos(omega * tau))                 # metres
            a_up = -half * omega * omega * math.cos(omega * tau) / G   # g
        else:
            x, a_up = 0.0, 0.0
        acc = [(1.0 + a_up) * c + (rng.gauss(0, noise_g) if noise_g else 0.0) for c in up]
        samples.append((t0_ms + s * 1000.0, acc[0], acc[1], acc[2], i))
        position.append(x * 100.0)
    return samples, position


def join(*parts):
    """Concatenate signals in time, renumbering the samples."""
    out, positions = [], []
    t_offset, n = 0.0, 0
    for samples, position in parts:
        first = samples[0][0]
        for (t, ax, ay, az, _), x in zip(samples, position):
            out.append((t - first + t_offset, ax, ay, az, n))
            positions.append(x)
            n += 1
        t_offset = out[-1][0] + 10.0
    return out, positions
