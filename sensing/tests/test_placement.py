"""Arduino distance -> hands on the spot, and the placement message the hub accepts."""
import sys
from pathlib import Path

from sensing import chest_input, config, messages

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "hub"))


def test_spot_on_while_pushing_off_after_hold():
    spot = chest_input.SpotDetector()
    for i in range(10):                       # resting chest, 10 cm away
        spot.add(10.0, i * 0.1)
    assert not spot.on_target(0.9) and spot.press_cm() == 0
    spot.add(9.8, 1.0)                        # 2 mm wobble: not a push
    assert not spot.on_target(1.0)
    spot.add(10.0 - config.SPOT_PRESS_CM - 0.1, 1.1)   # pushed
    assert spot.on_target(1.1)
    spot.add(10.0, 1.4)                       # released between pushes: still on
    assert spot.on_target(1.4)
    assert not spot.on_target(1.1 + config.SPOT_HOLD_S + 0.01)
    assert spot.fresh(1.4) and not spot.fresh(1.4 + config.CHEST_FRESH_S)


def test_placement_message_is_valid_for_the_hub():
    import pytest
    hub = pytest.importorskip("hub")
    m = messages.placement(True, 1.234)
    assert m["on_target"] is True and m["distance_cm"] is None and m["press_cm"] == 1.23
    assert m["source"] == "arduino"
    assert hub.validate(m) is None, hub.validate(m)
