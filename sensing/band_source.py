"""Where samples come from: the band (real or pretend), or a recorded CSV file.

Every source has: poll() -> list of Sample, connected, reconnecting, battery_percent,
finished, chest (an Arduino input that belongs to the source, or None), set_led(), close().
"""
import sys
import time
from collections import deque

from . import config, sim_script
from .chest_input import FakeChestInput
from .recorder import Sample, read_rows


class BandSource:
    """The band. The band number always comes from the caller (the command line)."""

    def __init__(self, number, sim=False, sim_chest=False):
        from . import kit
        kit.use()
        from vexo_open.sync import Band, VexoError
        self._VexoError = VexoError
        self._inbox = deque(maxlen=20000)       # filled by the motion handler, emptied by poll()
        self.events = deque(maxlen=100)         # taps and link news, for the main loop
        self.battery_percent = None
        self.finished = False
        self.sim = sim
        self.chest = FakeChestInput() if (sim and sim_chest) else None
        self._first_t = None
        self._led = None
        if sim:
            from vexo_open.transports.sim import SimTransport
            self.band = Band.connect(number, transport=SimTransport(number, auto_tap=False))
            self.band.transport.play_motion(sim_script.motion)      # plays until the program ends
        else:
            self.band = Band.connect(number, auto_reconnect=True)
        band = self.band
        # 8 g so hard pushes do not clip at the default 2 g
        band.set_motion(rate=config.MOTION_RATE_HZ, sensors="both", accel_range=config.ACCEL_RANGE_G,
                        gyro_range=config.GYRO_RANGE_DPS)
        # Handlers run on the library's background thread: only store, never compute.
        band.on("motion", lambda m: self._inbox.append((time.monotonic(), m)))
        band.on("battery", self._on_battery)
        band.on("tap", lambda e: self.events.append("tap"))
        band.on("double-tap", lambda e: self.events.append("double-tap"))
        band.on("reconnecting", lambda e: self.events.append("reconnecting"))
        band.on("reconnected", lambda e: self.events.append("reconnected"))
        band.on("disconnect", self._on_disconnect)
        band.configure(motion=config.MOTION_RATE_HZ, events=True, battery=True)

    def _on_battery(self, e):
        self.battery_percent = e.percent

    def _on_disconnect(self, e):
        self.events.append("disconnect")
        self.finished = True

    name = property(lambda self: self.band.name)
    connected = property(lambda self: bool(self.band.connected))
    reconnecting = property(lambda self: bool(self.band.reconnecting))
    dropped_events = property(lambda self: self.band.dropped_events)

    def poll(self):
        out = []
        while self._inbox:
            host, m = self._inbox.popleft()
            if m.ax is None or m.t is None:
                continue
            out.append(Sample(m.t, m.ax, m.ay, m.az, m.gx, m.gy, m.gz, m.n, host))
            if self.chest is not None:              # the pretend Arduino follows the pretend band
                if self._first_t is None:
                    self._first_t = m.t
                self.chest.push(sim_script.distance_cm((m.t - self._first_t) / 1000.0), host)
        return out

    def set_led(self, colour, **options):
        """Optional feedback. Never stops the program: the LED is refused while the
        microphone is on, and every command fails while the link is coming back."""
        if (colour, tuple(sorted(options.items()))) == self._led:
            return False
        try:
            self.band.set_led(colour, **options)
            self._led = (colour, tuple(sorted(options.items())))
            return True
        except Exception:
            return False

    def close(self):
        try:
            self.band.disconnect()
        except Exception:
            pass


class FileSource:
    """Replays a recorded CSV at real speed (speed=2 is twice as fast), so the whole
    pipeline runs with no band and no Arduino."""

    def __init__(self, path, speed=1.0):
        self.rows = [(kind, item) for kind, item, _ in read_rows(path)]
        if not any(kind == "band" for kind, _ in self.rows):
            raise SystemExit("%s holds no band samples." % path)
        self.chest = FakeChestInput() if any(kind == "chest" for kind, _ in self.rows) else None
        self.events = deque()
        self.speed = speed
        self.battery_percent = None
        self.connected = True
        self.reconnecting = False
        self.sim = False
        self.name = "recording %s" % path
        self._index = 0
        self._start = None
        self._first_host = self._host(self.rows[0])

    @staticmethod
    def _host(row):
        kind, item = row
        if kind == "chest":
            return item[1]
        return item.host if item.host is not None else item.t / 1000.0

    @property
    def finished(self):
        return self._index >= len(self.rows)

    def poll(self):
        if self._start is None:
            self._start = time.monotonic()
        due = self._first_host + (time.monotonic() - self._start) * self.speed
        out = []
        while self._index < len(self.rows) and self._host(self.rows[self._index]) <= due:
            kind, item = self.rows[self._index]
            self._index += 1
            if kind == "chest":
                self.chest.push(*item)
            else:
                out.append(item if item.host is not None else item._replace(host=item.t / 1000.0))
        return out

    def set_led(self, colour, **options):
        return False

    def close(self):
        pass


def connect_band(number, sim=False, sim_chest=False):
    """BandSource, with a band problem shown as one sentence."""
    from . import kit
    kit.use()
    from vexo_open.sync import VexoError
    if not sim:
        print("Connecting to band %d. Close the kit's dashboard tab and double-tap the band first." % number,
              file=sys.stderr)
    try:
        return BandSource(number, sim=sim, sim_chest=sim_chest)
    except VexoError as e:
        raise SystemExit("Problem (%s): %s" % (e.code, e)) from None
