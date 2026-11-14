"""The message format. ALL field names live in this one file.

Every message is a plain dict with: type, ts (Unix milliseconds, as PROTOCOL.md of the
hub asks), ts_iso (ISO 8601 UTC), t_band_ms, and the sender as both src="band" (hub) and
source="band" (glasses app).

The hub (PROTOCOL.md, Person 3) accepts only these quality words: good, harder, softer,
faster, slower. So `quality` uses exactly those, and `quality_full` carries our own
label, which can also be "lighter" (= softer) or "release fully".

  compression  one per detected compression
  heartbeat    once a second: the latest compression fields again, plus the status fields
  status       sent when connected / reconnecting / paused / arduino_ok / battery changes
  placement    5/s while the Arduino is fresh: are the hands pressing on the spot above it
"""
import time
from datetime import datetime, timezone

SOURCE = "band"
TYPE_COMPRESSION = "compression"
TYPE_STATUS = "status"
TYPE_HEARTBEAT = "heartbeat"
TYPE_PLACEMENT = "placement"

QUALITY_LABELS = ("good", "faster", "slower", "harder", "lighter", "release fully")    # quality_full
HUB_QUALITIES = ("good", "harder", "softer", "faster", "slower")                       # quality
TO_HUB = {"lighter": "softer"}
DEPTH_SOURCES = ("arduino", "band")

# Order matters only for readability of the JSON.
COMPRESSION_FIELDS = (
    "count", "rate_cpm", "depth_cm", "depth_source", "push_intensity_g", "push_intensity", "pressure",
    "quality", "quality_full", "confidence", "low_confidence", "recoil_ok", "session_s", "hands_off_s",
    "swap_in_s", "fatigue",
)
OPTIONAL_FIELDS = ("force_kg_est",)      # only present after a force calibration; an ESTIMATE
STATUS_FIELDS = ("connected", "reconnecting", "paused", "arduino_ok", "battery_percent")


def now_iso():
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def _round(value, digits):
    return None if value is None else round(float(value), digits)


def _base(kind, t_band_ms):
    return {"type": kind, "ts": int(time.time() * 1000), "ts_iso": now_iso(),
            "t_band_ms": None if t_band_ms is None else int(t_band_ms), "src": SOURCE, "source": SOURCE}


def hub_quality(full, without_recoil=None):
    """Our label -> one of the hub's five words (or None before the first compression).
    "release fully" has no hub word: the label that would apply without it is sent."""
    if full is None:
        return None
    if full == "release fully":
        full = without_recoil or "good"
    return TO_HUB.get(full, full)


def empty_state():
    """The compression fields before the first compression."""
    return dict(count=0, rate_cpm=None, depth_cm=None, depth_source="band", push_intensity_g=None,
                push_intensity=None, quality=None, quality_base=None, confidence=0.0, low_confidence=True, recoil_ok=None,
                session_s=0.0, hands_off_s=0.0, swap_in_s=None, fatigue=False)


def _compression_fields(state):
    out = {
        "count": int(state["count"]),
        "rate_cpm": _round(state.get("rate_cpm"), 1),
        "depth_cm": _round(state.get("depth_cm"), 2),
        "depth_source": state.get("depth_source", "band"),
        "push_intensity_g": _round(state.get("push_intensity_g"), 3),
        "push_intensity": _round(state.get("push_intensity"), 2),
        # the glasses app reads "pressure" (0..1). It is the push intensity score: how sharply
        # the wrist accelerates. The band has no pressure sensor.
        "pressure": _round(state.get("push_intensity"), 2),
    }
    if state.get("force_kg_est") is not None:      # omitted unless a force calibration exists
        out["force_kg_est"] = _round(state["force_kg_est"], 1)
    out.update({
        "quality": hub_quality(state.get("quality"), state.get("quality_base")),
        "quality_full": state.get("quality"),
        "confidence": _round(state.get("confidence", 0.0), 2),
        "low_confidence": bool(state.get("low_confidence", True)),
        "recoil_ok": state.get("recoil_ok"),               # true / false / null (null = no Arduino)
        "session_s": _round(state.get("session_s", 0.0), 1),
        "hands_off_s": _round(state.get("hands_off_s", 0.0), 1),
        "swap_in_s": _round(state.get("swap_in_s"), 1),
        "fatigue": bool(state.get("fatigue", False)),
    })
    return out


def _status_fields(status):
    battery = status.get("battery_percent")
    return {
        "connected": bool(status.get("connected", False)),
        "reconnecting": bool(status.get("reconnecting", False)),
        "paused": bool(status.get("paused", False)),
        "arduino_ok": bool(status.get("arduino_ok", False)),
        "battery_percent": None if battery is None else int(battery),
    }


def compression(t_band_ms, state):
    msg = _base(TYPE_COMPRESSION, t_band_ms)
    msg.update(_compression_fields(state))
    return msg


def status(t_band_ms, status_state):
    msg = _base(TYPE_STATUS, t_band_ms)
    msg.update(_status_fields(status_state))
    return msg


def heartbeat(t_band_ms, state, status_state):
    msg = _base(TYPE_HEARTBEAT, t_band_ms)
    msg.update(_compression_fields(state))
    msg.update(_status_fields(status_state))
    return msg


def placement(on_target, press_cm):
    """Hands on the spot = the Arduino under the chest sees it pressed (chest_input.SpotDetector).
    The Arduino cannot tell how far or which way the hands are, so those are null."""
    msg = _base(TYPE_PLACEMENT, None)
    msg.update({"on_target": bool(on_target), "distance_cm": None, "direction": None, "signal": 1.0,
                "trend": None, "press_cm": _round(press_cm, 2), "src": "arduino", "source": "arduino"})
    return msg
