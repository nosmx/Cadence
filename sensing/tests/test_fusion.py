import json
import time

import pytest

from sensing import chest_input, config
from sensing.chest_input import FakeChestInput
from sensing.pipeline import Pipeline
from sensing.tests import synth

REST = 20.0


def drive(samples, position, chest_until_ms=None, lean_cm=0.0, band_gain=1.0, chest_every=2, calib=None,
          chest_from_ms=0.0):
    """Run the pipeline over a synthetic signal. A fake Arduino reports the true chest
    position (every `chest_every`-th sample) until chest_until_ms. band_gain scales what
    the band feels, as if the wrist moved more or less than the chest. lean_cm: the chest
    never comes back that last bit while compressions run."""
    pipeline = Pipeline(calib=calib or {})
    chest = FakeChestInput()
    out = []
    first = next(i for i, x in enumerate(position) if x < 0) if any(x < 0 for x in position) else 0
    last = max((i for i, x in enumerate(position) if x < 0), default=0)
    for i, ((t, ax, ay, az, n), x) in enumerate(zip(samples, position)):
        if n % chest_every == 0 and t >= chest_from_ms and (chest_until_ms is None or t < chest_until_ms):
            leaning = lean_cm if first <= i <= last else 0.0
            chest.push(REST + min(x, -leaning), t / 1000.0)
        for distance, stamp in chest.drain():
            pipeline.add_chest(stamp, distance)
        az = 1.0 + (az - 1.0) * band_gain
        out.extend(pipeline.add_sample(t, ax, ay, az, n))
    return pipeline, out


def test_arduino_present_is_the_depth():
    samples, position = synth.compressions(110, 5.5, count=30)
    pipeline, out = drive(samples, position, band_gain=0.6)       # the band alone would say 3.3 cm
    assert out[-1]["count"] == 30
    for m in out[3:]:
        assert m["depth_source"] == "arduino"
        assert abs(m["depth_cm"] - 5.5) <= 0.2
        assert m["recoil_ok"] is True
        assert m["quality"] == "good"
        assert not m["low_confidence"]
    assert pipeline.fusion.scale == pytest.approx(1 / 0.6, rel=0.05)     # the band learnt its scale


def test_arduino_drops_out_mid_session():
    samples, position = synth.compressions(110, 5.5, count=40)
    cut = samples[0][0] + 3000 + 20 * (60000 / 110)               # after 20 compressions
    pipeline, out = drive(samples, position, chest_until_ms=cut, band_gain=0.6)
    assert out[-1]["count"] == 40
    sources = [m["depth_source"] for m in out]
    assert sources[5] == "arduino" and sources[-1] == "band"
    switch = sources.index("band")
    assert 19 <= out[switch]["count"] <= 23
    assert all(s == "band" for s in sources[switch:])
    for m in out[switch + 1:]:
        assert abs(m["depth_cm"] - 5.5) <= 0.5                    # calibration carried over
        assert m["recoil_ok"] is None                             # no Arduino: no guess
        assert not m["low_confidence"]
    pipeline.update_status(True, False, 80)
    assert pipeline.status["arduino_ok"] is False


def test_no_arduino_at_all():
    samples, position = synth.compressions(110, 5.5, count=30)
    pipeline, out = drive(samples, position, chest_until_ms=0)
    assert out[-1]["count"] == 30
    for m in out[3:]:
        assert m["depth_source"] == "band"
        assert m["recoil_ok"] is None
        assert abs(m["depth_cm"] - 5.5) <= 0.5
        assert m["confidence"] < 1.0                              # uncalibrated band depth
    assert "force_kg_est" not in out[-1]


def test_band_calibration_file_is_used():
    samples, position = synth.compressions(110, 5.5, count=20)
    _, out = drive(samples, position, chest_until_ms=0, band_gain=0.5,
                   calib={"depth_scale": 2.0, "force_kg_per_cm": 8.0})
    m = out[-1]
    assert abs(m["depth_cm"] - 5.5) <= 0.5
    assert m["confidence"] == 1.0
    assert m["force_kg_est"] == pytest.approx(8.0 * m["depth_cm"], abs=0.1)


def test_incomplete_release():
    samples, position = synth.compressions(110, 6.5, count=30)
    _, out = drive(samples, position, lean_cm=1.0)                # never comes back the last centimetre
    assert out[-1]["count"] == 30
    for m in out[3:]:
        assert m["recoil_ok"] is False
        assert abs(m["depth_cm"] - 5.5) <= 0.2                    # the travel that is left
        assert m["quality_full"] == "release fully" and m["quality"] == "good"
    samples, position = synth.compressions(110, 5.5, count=30)
    _, shallow = drive(samples, position, lean_cm=1.0)            # 4.5 cm travel: "harder" comes first
    assert all(m["recoil_ok"] is False and m["quality"] == "harder" for m in shallow[3:])
    samples, position = synth.compressions(110, 5.5, count=30)
    _, ok = drive(samples, position, lean_cm=0.2)                 # 2 mm short: within tolerance
    assert all(m["recoil_ok"] is True for m in ok[3:])


def test_arduino_starts_mid_compressions():
    samples, position = synth.compressions(110, 5.5, count=30)
    start = samples[0][0] + 3000 + 10 * (60000 / 110)
    _, out = drive(samples, position, chest_from_ms=start)
    assert out[5]["depth_source"] == "band" and out[5]["recoil_ok"] is None
    assert out[-1]["depth_source"] == "arduino" and out[-1]["recoil_ok"] is True


def test_stale_arduino_is_not_used():
    samples, position = synth.compressions(110, 5.5, count=12)
    cut = samples[0][0] + 3000 + 6 * (60000 / 110)
    _, out = drive(samples, position, chest_until_ms=cut)
    late = [m for m in out if m["t_band_ms"] > cut + config.CHEST_FRESH_S * 1000 + 100]
    assert late and all(m["depth_source"] == "band" for m in late)


# ---- the adapters ----

@pytest.mark.parametrize("line,expected", [
    ("12.5", 12.5), (b"12.5\r\n", 12.5), ("distance: 9.25 cm", 9.25), ('{"type":"chest","distance_cm":7.5}', 7.5),
    ('{"distance_mm": 120}', 12.0), ('{"d": 4}', 4.0), ("", None), ("hello", None),
    ('{"type":"other","distance_cm":7}', None), ("{broken", None),
])
def test_parse_line(line, expected):
    assert chest_input.parse_line(line) == expected


def test_message_adapter_and_latest():
    chest = chest_input.MessageChestInput()
    assert chest.latest() is None
    chest.feed({"type": "compression", "distance_cm": 3})        # not a chest message
    chest.feed({"type": "chest", "distance_cm": 11.5})
    distance, stamp = chest.latest()
    assert distance == 11.5 and stamp > 0
    assert chest.drain() == [(11.5, stamp)] and chest.drain() == []


def test_serial_adapter_reads_lines_and_writes():
    class Port:
        def __init__(self):
            self.lines = [b"10.0\n", b"garbage\n", b'{"distance_cm": 9.5}\n']
            self.written = []

        def readline(self):
            time.sleep(0.005)
            return self.lines.pop(0) if self.lines else b""

        def write(self, data):
            self.written.append(data)

        def close(self):
            pass

    port = Port()
    chest = chest_input.SerialChestInput("COMx", opener=lambda: port)
    deadline = time.time() + 2
    while chest.count < 2 and time.time() < deadline:
        time.sleep(0.01)
    chest.write(b"hi\n")
    chest.close()
    assert [d for d, _ in chest.drain()] == [10.0, 9.5]
    assert port.written == [b"hi\n"]


def test_http_listener():
    import socket
    import urllib.request
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
    chest = chest_input.HttpChestListener(port)
    try:
        body = json.dumps({"type": "chest", "distance_cm": 8.25}).encode()
        request = urllib.request.Request("http://127.0.0.1:%d/" % port, data=body, method="POST")
        urllib.request.urlopen(request, timeout=2).read()
        time.sleep(0.05)
        assert chest.latest()[0] == 8.25
    finally:
        chest.close()
