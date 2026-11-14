"""arduino_check and the serial diagnostics, against a fake Arduino on a pseudo-terminal."""
import os
import sys
import threading
import time

import pytest

pytest.importorskip("serial")
if not hasattr(os, "openpty"):
    pytest.skip("needs a pseudo-terminal (Mac/Linux)", allow_module_level=True)

import serial  # noqa: E402

from sensing import arduino_check  # noqa: E402
from sensing.chest_input import SerialChestInput  # noqa: E402


def fake_arduino(lines, seconds=1.5):
    """A pseudo-terminal that 'prints' the given lines over and over -> its device path."""
    master, slave = os.openpty()
    path = os.ttyname(slave)

    def talk():
        end = time.monotonic() + seconds
        while time.monotonic() < end:
            for line in lines:
                os.write(master, line)
                time.sleep(0.02)

    if lines:
        threading.Thread(target=talk, daemon=True).start()
    return path


def opener(path):
    return lambda: serial.Serial(path, 115200, timeout=0.1)


def test_clean_numbers_give_the_speed_to_use():
    path = fake_arduino([b"18.4\r\n", b"17.2\r\n", b"15.9 cm\r\n"])
    result = arduino_check.listen(path, 115200, seconds=0.8, opener=opener(path))
    best, advice = arduino_check.verdict({115200: result})
    assert best == 115200 and "Use speed 115200" in advice


def test_unreadable_lines_are_explained():
    path = fake_arduino([b"Ultrasonic ready\r\n", b"echo ok\r\n"])
    result = arduino_check.listen(path, 115200, seconds=0.8, opener=opener(path))
    best, advice = arduino_check.verdict({115200: result})
    assert best is None and "no distance" in advice


def test_silence_is_explained():
    path = fake_arduino([])
    best, advice = arduino_check.verdict({115200: arduino_check.listen(path, 115200, seconds=0.5, opener=opener(path))})
    assert best is None and "sent nothing" in advice


def test_pipeline_input_says_why_there_were_no_readings():
    path = fake_arduino([b"hello\r\n"], seconds=0.6)
    chest = SerialChestInput(path, opener=opener(path))
    time.sleep(0.8)
    chest.close()
    assert chest.count == 0 and chest.lines > 0
    assert "none held a distance" in chest.diagnosis()

    path = fake_arduino([b"20.0\r\n", b"19.5\r\n"], seconds=0.6)
    chest = SerialChestInput(path, opener=opener(path))
    time.sleep(0.8)
    chest.close()
    assert chest.count > 0 and chest.diagnosis() is None
