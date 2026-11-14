import io
import json
import socket
import time

from sensing import fake_messages, messages
from sensing.publisher import Publisher


def free_port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def receive_all(client, quiet=0.5):
    got = []
    while True:
        try:
            got.append(json.loads(client.recv(timeout=quiet)))
        except TimeoutError:
            return got


def check_common(msg):
    assert msg["source"] == "band" and msg["src"] == "band"
    assert isinstance(msg["ts"], int) and msg["ts"] > 1_600_000_000_000        # Unix ms, as the hub asks
    assert msg["ts_iso"].endswith("Z") and "T" in msg["ts_iso"]
    assert "t_band_ms" in msg


def test_compression_message_fields():
    state = messages.empty_state()
    state.update(count=3, rate_cpm=110.04, depth_cm=5.512, quality="good", confidence=0.9, low_confidence=False)
    msg = messages.compression(1234.7, state)
    check_common(msg)
    assert msg["type"] == "compression"
    for field in messages.COMPRESSION_FIELDS:
        assert field in msg
    assert "force_kg_est" not in msg                  # omitted without a force calibration
    assert msg["rate_cpm"] == 110.0 and msg["depth_cm"] == 5.51 and msg["t_band_ms"] == 1234
    state["force_kg_est"] = 41.26
    assert messages.compression(1, state)["force_kg_est"] == 41.3
    json.dumps(msg)


def test_status_and_heartbeat_fields():
    status = dict(connected=True, reconnecting=False, paused=True, arduino_ok=False, battery_percent=87)
    msg = messages.status(5, status)
    check_common(msg)
    assert msg["type"] == "status"
    for field in messages.STATUS_FIELDS:
        assert field in msg
    beat = messages.heartbeat(5, messages.empty_state(), status)
    for field in messages.COMPRESSION_FIELDS + messages.STATUS_FIELDS:
        assert field in beat


def test_fake_messages_over_websocket():
    from websockets.sync.client import connect
    port = free_port()
    publisher = Publisher(stdout=False, ws=True, ws_port=port)
    try:
        with connect("ws://127.0.0.1:%d" % port) as client:
            deadline = time.time() + 2
            while publisher.ws.client_count == 0 and time.time() < deadline:
                time.sleep(0.01)
            fake_messages.run(publisher, seconds=20, sleep=lambda s: None)
            got = receive_all(client)
    finally:
        publisher.close()
    kinds = {m["type"] for m in got}
    assert kinds == {"compression", "status", "heartbeat"}
    for m in got:
        check_common(m)
    comps = [m for m in got if m["type"] == "compression"]
    assert [m["count"] for m in comps] == list(range(1, len(comps) + 1))
    assert {m["quality"] for m in comps} >= {"faster", "good"}
    assert all(m["quality"] in messages.HUB_QUALITIES for m in comps)
    assert all(m["quality_full"] in messages.QUALITY_LABELS for m in comps)


def test_fake_cycles_through_every_scenario():
    out = io.StringIO()
    fake_messages.run(Publisher(stdout=True, stream=out), seconds=50, sleep=lambda s: None)
    got = [json.loads(line) for line in out.getvalue().splitlines()]
    labels = {m["quality_full"] for m in got if m["type"] == "compression"}
    assert labels == {"faster", "good", "slower", "harder", "release fully"}
    assert {m["quality"] for m in got if m["type"] == "compression"} <= set(messages.HUB_QUALITIES)
    assert any(m["type"] == "status" and m["paused"] for m in got[1:])
    assert any(m["type"] == "compression" and m["recoil_ok"] is False for m in got)


def test_dead_and_slow_clients_do_not_block():
    from websockets.sync.client import connect
    port = free_port()
    publisher = Publisher(stdout=False, ws=True, ws_port=port)
    try:
        slow = connect("ws://127.0.0.1:%d" % port)          # never reads
        dead = connect("ws://127.0.0.1:%d" % port)
        dead.socket.close()                                  # vanishes without a goodbye
        time.sleep(0.1)
        start = time.time()
        for i in range(5000):
            publisher.publish({"type": "status", "i": i, "pad": "x" * 200})
        assert time.time() - start < 2.0
        slow.close()
    finally:
        publisher.close()


def test_matches_the_hub_protocol():
    """PROTOCOL.md (Person 3): what hub.py's validate() checks for a compression."""
    state = messages.empty_state()
    for full, base, expected in (("good", "good", "good"), ("lighter", "lighter", "softer"),
                                 ("release fully", "slower", "slower"), ("release fully", "good", "good"),
                                 ("harder", "harder", "harder"), ("faster", "faster", "faster")):
        state.update(count=7, rate_cpm=110.0, depth_cm=5.4, quality=full, quality_base=base, confidence=0.8,
                     push_intensity=0.6)
        m = messages.compression(1, state)
        assert isinstance(m["count"], int) and isinstance(m["rate_cpm"], float)
        assert m["quality"] == expected and m["quality"] in ("good", "harder", "softer", "faster", "slower")
        assert m["quality_full"] == full
        assert 0 <= m["confidence"] <= 1
        assert m["src"] == "band" and isinstance(m["ts"], int)
        assert m["pressure"] == 0.6                      # what the glasses app reads


def test_post_sends_only_compressions_by_default():
    from sensing.publisher import HttpPostOutput
    sent = []
    out = HttpPostOutput("http://127.0.0.1:9/msg")
    out._worker.put = sent.append
    out.send("a", "compression")
    out.send("b", "status")
    out.send("c", "heartbeat")
    assert sent == ["a"]
