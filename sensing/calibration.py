"""calibration.json: the band's depth scale and the optional force factor."""
import json
from pathlib import Path

PATH = Path(__file__).resolve().parent / "calibration.json"
DEPTH_SCALE = "depth_scale"                 # band depth (cm) = raw double integration * this
FORCE_K = "force_kg_per_cm"                 # force_kg_est = this * depth_cm (an ESTIMATE)


def load(path=None):
    path = Path(path or PATH)
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def save(values, path=None):
    path = Path(path or PATH)
    data = load(path)
    data.update(values)
    path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    return data


def fit_force(pairs):
    """pairs of (depth_cm, force_kg) -> k of force = k * depth (least squares through zero)."""
    den = sum(d * d for d, _ in pairs)
    return sum(d * f for d, f in pairs) / den if den > 0 else None
