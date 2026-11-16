"""Every tunable number in one place. Each says whether it was MEASURED or GUESSED.

Nothing here has been measured on the real band or the real Arduino yet.
"""

# ---- band -----------------------------------------------------------------
MOTION_RATE_HZ = 100            # spec: use 100 samples per second over Bluetooth
ACCEL_RANGE_G = 8               # spec: 8 g so hard pushes do not clip at the default 2 g
GYRO_RANGE_DPS = 500            # spec
CLIP_FRACTION = 0.98            # GUESSED: |axis| >= 98 % of the range counts as clipped

# ---- detector -------------------------------------------------------------
GRAVITY_TAU_S = 2.0             # GUESSED: time constant of the slow gravity low-pass
SMOOTH_CUTOFF_HZ = 10.0         # GUESSED: light smoothing before zero-crossing detection
MIN_PEAK_G = 0.08               # GUESSED (spec start value): minimum peak for a compression
CONFIRM_FRACTION = 0.5          # GUESSED: signal must rise to +50 % of MIN_PEAK_G after the crossing
ARM_TIMEOUT_S = 0.75            # GUESSED: a downward peak older than this no longer arms a crossing
REFRACTORY_S = 0.25             # spec: minimum time between two compressions
RATE_INTERVALS = 5              # spec: rate = 60 / median of the last 5 intervals
MAX_CYCLE_S = 1.5               # GUESSED: a cycle longer than this (40/min) gets no depth
# Rhythm lock (against counting other arm movements). All GUESSED; tune from real recordings.
LOCK_CROSSINGS = 4              # evenly spaced pushes in a row before anything is counted
LOCK_TOLERANCE = 0.40           # TUNED on a real band-27 recording (was 0.25): ... whose intervals differ by at most 40 %
LOCK_MIN_DEPTH_CM = 0.5         # TUNED (was 1.0): ... each at least this deep (band estimate, before calibration)
MIN_INTERVAL_S = 0.30           # 200 per minute
MAX_INTERVAL_S = 1.20           # 50 per minute
LOCKED_TOLERANCE = 0.35         # once locked: an interval this far from the usual one is odd
UNLOCK_AFTER_ODD = 2            # two odd ones in a row end the rhythm
GYRO_MAX_DPS = 500.0            # TUNED (was 250; real pushes measured 100-450): mean wrist turning above this is not a compression
PAUSE_S = 2.0                   # spec: no compression for 2 s = hands off
SWAP_S = 120.0                  # spec: 2-minute rescuer swap timer
SWAP_RESET_PAUSE_S = 3.0        # GUESSED: once the timer is at 0, a pause this long restarts it
G_MS2 = 9.80665                 # physical constant

# ---- fusion (Arduino under the body) ---------------------------------------
CHEST_FRESH_S = 0.5             # spec: Arduino data older than this is not used
CHEST_MIN_READINGS = 4          # GUESSED: readings needed inside one cycle to trust its peak-to-peak
CHEST_COMPRESSED_IS_SMALLER = True   # GUESSED: pushing down makes the measured distance smaller
RECOIL_TOLERANCE_CM = 0.5       # GUESSED ("a few millimetres"): release must come this close to rest
SPOT_PRESS_CM = 0.5             # GUESSED: chest pressed this far below rest at the Arduino = hands on the spot
SPOT_HOLD_S = 1.5               # GUESSED: stay "on spot" this long after the last press (between pushes)
SPOT_REST_WINDOW_S = 10.0       # the rest level is the least-pressed reading in this window
PLACEMENT_HZ = 5                # placement messages per second (the glasses call it lost after 1.5 s)
REST_MIN_READINGS = 5           # GUESSED: readings needed (while hands are off) to learn the rest distance
REST_WINDOW = 25                # GUESSED: the rest distance is learnt from this many readings that hold still
SCALE_WINDOW = 15               # GUESSED: running median over this many compressions (slow)
SCALE_MIN_SAMPLES = 3           # GUESSED: ratios needed before the band scale is updated
SCALE_MIN, SCALE_MAX = 0.2, 5.0  # GUESSED: sanity limits of the band depth scale
DEFAULT_DEPTH_SCALE = 1.0       # GUESSED: uncalibrated band depth = plain double integration

# ---- quality --------------------------------------------------------------
RATE_MIN_CPM, RATE_MAX_CPM = 100.0, 120.0   # spec
DEPTH_MIN_CM, DEPTH_MAX_CM = 5.0, 6.0       # spec
LABEL_DEPTH_WINDOW = 3          # GUESSED: label uses the median depth of the last 3 compressions
LOW_CONFIDENCE_BELOW = 0.5      # spec
# Confidence penalties, all GUESSED:
PEN_FEW_INTERVALS = 0.3         # fewer than 3 intervals
PEN_IRREGULAR = 0.3             # full penalty when interval variation reaches IRREGULAR_CV_FULL
IRREGULAR_CV_OK = 0.10          # variation (std/mean) below this costs nothing
IRREGULAR_CV_FULL = 0.35
PEN_CLIPPED = 0.3
PEN_DROPPED = 0.2
PEN_UNCALIBRATED = 0.3          # band-only depth with no calibration
PEN_RECONNECTING = 0.6
PEN_NO_DEPTH = 0.3              # no depth available for this compression
# Fatigue
FATIGUE_WINDOW_S = 20.0         # spec: last 20 s against the first 20 s
FATIGUE_DEPTH_DROP = 0.15       # spec: depth fallen by 15 % or more
# Push intensity
INTENSITY_DEFAULT_RANGE_G = (0.15, 0.80)   # GUESSED: used until enough good compressions were seen
INTENSITY_MIN_GOOD = 5          # GUESSED: good compressions needed before their own range is used
INTENSITY_HISTORY = 50          # GUESSED

# ---- output ---------------------------------------------------------------
WS_HOST, WS_PORT = "0.0.0.0", 8765          # spec
HEARTBEAT_S = 1.0               # spec: 1 Hz heartbeat
CLIENT_QUEUE = 100              # GUESSED: messages kept for a slow WebSocket client before the oldest go
POST_QUEUE = 100                # GUESSED
POST_TIMEOUT_S = 1.0            # GUESSED
LOOP_SLEEP_S = 0.01             # GUESSED: main loop period

# ---- voice ----------------------------------------------------------------
VOICE_MIN_GAP_S = 4.0           # GUESSED: at most one spoken correction every 4 s
VOICE_REPEAT_S = 10.0           # GUESSED: the same correction again only after 10 s
