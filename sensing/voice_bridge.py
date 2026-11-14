"""--voice: spoken corrections through the team's voice.py (Deepgram text-to-speech with
cached WAV files). This file only decides WHEN to speak; voice.py does the speaking.

voice.py is looked for in sensing/ and in the repo root. It must offer one of:
say(text), speak(text) or play(text). Speaking runs on its own thread so that a slow
network never holds up sensing.
"""
import importlib
import queue
import sys
import threading

from . import config
from .kit import REPO_ROOT

PHRASES = {
    "faster": "Push faster",
    "slower": "Slow down",
    "harder": "Push harder",
    "lighter": "A little lighter",
    "release fully": "Release fully",
    "good": "Good, keep going",
    "swap": "Swap rescuers now",
}


def _find_speaker():
    for name in ("sensing.voice", "voice"):
        try:
            if name == "voice" and str(REPO_ROOT) not in sys.path:
                sys.path.insert(0, str(REPO_ROOT))
            module = importlib.import_module(name)
        except ImportError:
            continue
        for function in ("say", "speak", "play"):
            if callable(getattr(module, function, None)):
                return getattr(module, function)
    return None


class Voice:
    def __init__(self, speaker=None):
        self._speak = speaker or _find_speaker()
        self.available = self._speak is not None
        if not self.available:
            print("--voice: voice.py was not found (looked in sensing/ and the repo root), or it has no "
                  "say(text) function. Running without voice.", file=sys.stderr)
        self._queue = queue.Queue(maxsize=1)
        self._last_time = None
        self._last_label = None
        self._last_label_time = None
        self._good_streak = 0
        self._swap_said = False
        if self.available:
            threading.Thread(target=self._run, name="voice", daemon=True).start()

    def _run(self):
        while True:
            text = self._queue.get()
            try:
                self._speak(text)
            except Exception as e:
                print("voice: could not speak (%s). Sensing goes on." % e, file=sys.stderr)

    def _say(self, key, now_s):
        try:
            self._queue.put_nowait(PHRASES[key])
        except queue.Full:
            return
        self._last_time = now_s
        self._last_label, self._last_label_time = key, now_s

    def on_compression(self, state, now_s):
        """state: the fields of a compression message. now_s: any steady clock."""
        if not self.available:
            return
        swap_in = state.get("swap_in_s")
        if swap_in is not None and swap_in <= 0 and not self._swap_said:
            self._swap_said = True
            self._say("swap", now_s)
            return
        if swap_in:
            self._swap_said = False
        label = state.get("quality")
        if label is None or state.get("low_confidence"):
            return                                  # never speak a correction we do not trust
        self._good_streak = self._good_streak + 1 if label == "good" else 0
        if self._last_time is not None and now_s - self._last_time < config.VOICE_MIN_GAP_S:
            return
        if label == "good":
            if self._last_label not in (None, "good") and self._good_streak >= 5:
                self._say("good", now_s)            # praise once, after a correction was fixed
            return
        if label == self._last_label and now_s - self._last_label_time < config.VOICE_REPEAT_S:
            return
        self._say(label, now_s)
