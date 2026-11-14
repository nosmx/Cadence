"""run.py with the pretend band, watched by a WebSocket client like a teammate's."""
import json
import os
import socket
import subprocess
import sys
import time
from pathlib import Path

import pytest

from sensing import kit, messages
from sensing.recorder import read_rows

ROOT = Path(__file__).resolve().parents[2]
BAND = "27"                 # our team's band number (the pretend band reports the same number)
pytestmark = pytest.mark.skipif(kit.find() is None, reason="vexo-open-kit not found")


def free_port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def collect(arguments, seconds):
    from websockets.sync.client import connect
    port = free_port()
    process = subprocess.Popen([sys.executable, "-m", "sensing.run", BAND, "--sim", "--ws", "--ws-port", str(port),
                                "--quiet", "--seconds", str(seconds)] + arguments, cwd=ROOT, stderr=subprocess.PIPE,
                               env=dict(os.environ, PYTHONIOENCODING="utf-8"))
    got = []
    try:
        client = None
        deadline = time.time() + 15
        while client is None:
            try:
                client = connect("ws://127.0.0.1:%d" % port)
            except OSError:
                if time.time() > deadline or process.poll() is not None:
                    raise AssertionError("run.py did not start: %s" % process.stderr.read().decode())
                time.sleep(0.1)
        with client:
            while True:
                try:
                    got.append(json.loads(client.recv(timeout=3)))
                except Exception:
                    break
    finally:
        try:
            process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            process.kill()
    return got, process.stderr.read().decode()


def test_sim_band_alone(tmp_path):
    recording = tmp_path / "e2e.csv"
    got, log = collect(["--record", str(recording), "--label", "good"], 16)
    comps = [m for m in got if m["type"] == "compression"]
    assert len(comps) >= 20, log
    counts = [m["count"] for m in comps]
    assert counts == list(range(counts[0], counts[0] + len(comps)))
    for m in got:
        assert m["source"] == "band" and m["src"] == "band" and isinstance(m["ts"], int) and "t_band_ms" in m
    for m in comps:
        for field in messages.COMPRESSION_FIELDS:
            assert field in m
        assert "force_kg_est" not in m
    good = [m for m in comps if 6 <= m["count"] <= 20]            # the story starts with 110/min, 5.5 cm
    assert good
    for m in good:
        assert abs(m["rate_cpm"] - 110) <= 3
        assert abs(m["depth_cm"] - 5.5) <= 0.5
        assert m["depth_source"] == "band" and m["recoil_ok"] is None
        assert m["quality"] == "good"
    assert any(m["quality"] == "faster" for m in comps)           # then 85/min
    beats = [m for m in got if m["type"] == "heartbeat"]
    assert len(beats) >= 10
    statuses = [m for m in got if m["type"] == "status"]
    assert statuses and statuses[-1]["connected"] and statuses[-1]["arduino_ok"] is False
    assert any(s["battery_percent"] is not None for s in statuses + beats)
    rows = list(read_rows(recording))
    assert len(rows) > 1000 and rows[0][2] == "good" and all(kind == "band" for kind, _, _ in rows)


def test_sim_band_with_pretend_arduino():
    got, log = collect(["--arduino", "sim"], 10)
    comps = [m for m in got if m["type"] == "compression"]
    assert len(comps) >= 12, log
    for m in comps[3:]:
        assert m["depth_source"] == "arduino"
        assert abs(m["depth_cm"] - 5.5) <= 0.3
        assert m["recoil_ok"] is True
    assert any(m["type"] in ("status", "heartbeat") and m["arduino_ok"] for m in got)
