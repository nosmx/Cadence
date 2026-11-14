"""The story the pretend band plays with --sim: compressions at known rates and depths.
The same function gives the true chest position, so a pretend Arduino can go with it."""
import math

from . import config

# name, seconds, rate per minute (None = hands off), depth cm, lean cm (chest not fully released)
SEGMENTS = (
    ("good",          12, 110,  5.5, 0.0),
    ("slow",           8, 85,   5.5, 0.0),
    ("shallow",        8, 110,  3.5, 0.0),
    ("paused",         4, None, 0.0, 0.0),
    ("fast",           8, 140,  5.0, 0.0),
    ("not releasing",  8, 110,  5.5, 1.2),
)
TOTAL_S = float(sum(segment[1] for segment in SEGMENTS))
GRAVITY = (0.20, 0.10, 0.97)            # a slightly tilted wrist
REST_DISTANCE_CM = 20.0                 # pretend Arduino: distance at rest


def _at(s):
    """-> (upward acceleration in g, chest position in cm; 0 = rest, negative = pushed down)"""
    s = s % TOTAL_S
    for _, seconds, rate, depth, lean in SEGMENTS:
        if s >= seconds:
            s -= seconds
            continue
        if rate is None:
            return 0.0, 0.0
        period = 60.0 / rate
        if s >= int(seconds / period) * period:     # the rest of the segment after whole cycles
            return 0.0, 0.0
        omega = 2 * math.pi / period
        half = depth / 2.0
        position = -lean - half * (1 - math.cos(omega * s))
        accel = -(half / 100.0) * omega * omega * math.cos(omega * s) / config.G_MS2
        return accel, position
    return 0.0, 0.0


def motion(s):
    """For SimTransport.play_motion: seconds since the start -> dict(ax, ay, az) in g."""
    accel, _ = _at(s)
    norm = math.sqrt(sum(c * c for c in GRAVITY))
    return dict(zip(("ax", "ay", "az"), ((1.0 + accel) * c / norm for c in GRAVITY)))


def distance_cm(s):
    """What an Arduino under the body would measure at that moment."""
    return REST_DISTANCE_CM + _at(s)[1]
