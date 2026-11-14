"""--record NAME: raw band samples and Arduino readings to recordings/NAME.csv.

One row per band sample (kind "band") or Arduino reading (kind "chest"). host_s is the
laptop's clock (time.monotonic) when the row arrived; t_ms is the band's own clock.
"""
import csv
from pathlib import Path
from typing import NamedTuple

from .kit import REPO_ROOT

DIRECTORY = REPO_ROOT / "recordings"
LABELS = ("good", "shallow", "fast", "slow")
COLUMNS = ("kind", "host_s", "t_ms", "n", "ax", "ay", "az", "gx", "gy", "gz", "distance_cm", "label")


class Sample(NamedTuple):
    t: float            # band clock, ms
    ax: float
    ay: float
    az: float
    gx: float = None
    gy: float = None
    gz: float = None
    n: int = None       # sample number: a jump means lost samples
    host: float = None  # laptop clock at arrival, seconds

    @property
    def gyro_dps(self):
        """Turning speed of the wrist (all axes together), or None without the gyro."""
        if self.gx is None or self.gy is None or self.gz is None:
            return None
        return (self.gx * self.gx + self.gy * self.gy + self.gz * self.gz) ** 0.5


def path_for(name):
    name = str(name)
    if name.endswith(".csv") or "/" in name or "\\" in name:
        return Path(name)
    return DIRECTORY / (name + ".csv")


class Recorder:
    def __init__(self, name, label=None):
        self.path = path_for(name)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.label = label or ""
        self._file = open(self.path, "w", newline="", encoding="utf-8")
        self._writer = csv.writer(self._file)
        self._writer.writerow(COLUMNS)
        self.rows = 0

    def band(self, s):
        self._writer.writerow(("band", _f(s.host), _f(s.t), "" if s.n is None else s.n, _f(s.ax), _f(s.ay), _f(s.az),
                               _f(s.gx), _f(s.gy), _f(s.gz), "", self.label))
        self._count()

    def chest(self, host_s, distance_cm):
        self._writer.writerow(("chest", _f(host_s), "", "", "", "", "", "", "", "", _f(distance_cm), self.label))
        self._count()

    def _count(self):
        self.rows += 1
        if self.rows % 200 == 0:
            self._file.flush()

    def close(self):
        self._file.close()


def _f(value):
    return "" if value is None else "%.6g" % value if abs(value) < 1e5 else "%.3f" % value


def _num(text):
    return None if text in ("", None) else float(text)


def read_rows(path):
    """Yields ("band", Sample) and ("chest", (distance_cm, host_s)) in file order, and the
    label of the file as the third item."""
    with open(path, newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            label = row.get("label") or None
            if row.get("kind") == "chest":
                distance, host = _num(row.get("distance_cm")), _num(row.get("host_s"))
                if distance is not None and host is not None:
                    yield "chest", (distance, host), label
            elif row.get("kind") == "band":
                t = _num(row.get("t_ms"))
                if t is None:
                    continue
                n = _num(row.get("n"))
                yield "band", Sample(t, _num(row["ax"]), _num(row["ay"]), _num(row["az"]), _num(row.get("gx")),
                                     _num(row.get("gy")), _num(row.get("gz")), None if n is None else int(n),
                                     _num(row.get("host_s"))), label
