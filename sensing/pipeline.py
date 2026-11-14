"""Samples and Arduino readings in, messages out. No band and no network here, so the
whole chain can be tested and replayed from a file."""
from . import calibration, config, messages, quality
from .detector import Detector, SessionTracker
from .fusion import Fusion


class Pipeline:
    def __init__(self, calib=None, learn_scale=True, accel_range_g=config.ACCEL_RANGE_G):
        calib = calibration.load() if calib is None else calib
        scale = calib.get(calibration.DEPTH_SCALE)
        self.force_k = calib.get(calibration.FORCE_K)
        self.detector = Detector(accel_range_g=accel_range_g)
        self.tracker = SessionTracker()
        self.fusion = Fusion(scale=scale or config.DEFAULT_DEPTH_SCALE, calibrated=bool(scale), learn=learn_scale)
        self.smoother = quality.DepthSmoother()
        self.fatigue = quality.Fatigue()
        self.push = quality.PushIntensity()
        self.state = messages.empty_state()
        self.status = dict(connected=False, reconnecting=False, paused=True, arduino_ok=False, battery_percent=None)
        self._sent_status = None
        self.t_ms = None                    # latest band time
        self.last_event = None              # detector.Compression of the latest compression
        self.last_fused = None

    # ---- inputs ----
    def add_chest(self, t_band_s, distance_cm):
        self.fusion.add_chest(t_band_s, distance_cm)

    def add_sample(self, t_ms, ax, ay, az, n=None, reconnecting=False, gyro_dps=None):
        """One band sample. Returns the messages it caused (usually none)."""
        self.t_ms = t_ms
        out = []
        event = self.detector.add(t_ms, ax, ay, az, n, gyro_dps)
        if event is not None:
            out.append(self._on_compression(event, reconnecting))
        if self.tracker.update(t_ms / 1000.0):          # a pause begins
            self.detector.reset_timing()
            self.smoother.clear()
            self.fusion.set_paused(True)
        return out

    def _on_compression(self, event, reconnecting):
        now_s = self.t_ms / 1000.0
        t_s = event.t_ms / 1000.0
        if event.run_start_ms is not None:              # the run began before it was confirmed
            self.tracker.on_compression(event.run_start_ms / 1000.0)
        self.tracker.on_compression(t_s)
        self.fusion.set_paused(False)
        fused = self.fusion.fuse(event, now_s)
        self.last_event, self.last_fused = event, fused
        depth_for_label = self.smoother.add(fused.depth_cm)
        label = quality.label(event.rate_cpm, depth_for_label, fused.recoil_ok)
        base = quality.label(event.rate_cpm, depth_for_label, None)     # the label without the release rule
        conf = quality.confidence(
            n_intervals=event.n_intervals, interval_cv=event.interval_cv, clipped=event.clipped,
            dropped=event.dropped, samples=event.samples, depth_source=fused.depth_source,
            calibrated=fused.calibrated, reconnecting=reconnecting, has_depth=fused.depth_cm is not None)
        session_s = self.tracker.session_s(t_s)
        self.state.update(
            count=event.count, rate_cpm=event.rate_cpm, depth_cm=fused.depth_cm,
            depth_source=fused.depth_source, push_intensity_g=event.peak_down_g,
            push_intensity=self.push.score(event.peak_down_g), quality=label, quality_base=base,
            confidence=conf,
            low_confidence=conf < config.LOW_CONFIDENCE_BELOW, recoil_ok=fused.recoil_ok,
            fatigue=self.fatigue.add(session_s, fused.depth_cm, event.rate_cpm))
        self.push.learn(event.peak_down_g, label)
        if self.force_k and fused.depth_cm is not None:
            self.state["force_kg_est"] = self.force_k * fused.depth_cm
        else:
            self.state.pop("force_kg_est", None)
        self._refresh_times(t_s)
        return messages.compression(event.t_ms, self.state)

    def _refresh_times(self, t_s):
        self.state["session_s"] = self.tracker.session_s(t_s)
        self.state["hands_off_s"] = self.tracker.hands_off_s(t_s)
        self.state["swap_in_s"] = self.tracker.swap_in(t_s)

    # ---- outputs on a clock ----
    def update_status(self, connected, reconnecting, battery_percent):
        """Returns a status message when something changed, else None."""
        now_s = (self.t_ms or 0.0) / 1000.0
        self.status.update(connected=bool(connected), reconnecting=bool(reconnecting),
                           paused=self.tracker.paused, arduino_ok=self.fusion.arduino_ok(now_s),
                           battery_percent=battery_percent)
        key = tuple(self.status[name] for name in messages.STATUS_FIELDS)
        if key == self._sent_status:
            return None
        self._sent_status = key
        return messages.status(self.t_ms, self.status)

    def heartbeat(self):
        if self.t_ms is not None:
            self._refresh_times(self.t_ms / 1000.0)
        return messages.heartbeat(self.t_ms, self.state, self.status)
