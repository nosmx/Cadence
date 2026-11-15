/**
 * CPR Coach glasses app: phase state machine + render loop.
 *
 * Flow: splash -> setup (body positioning, 3 pages) -> align (Arduino hand tracking,
 *       advances by itself) -> ready -> compress (pace circle + beep + live bracelet feedback)
 *       -> summary.
 *
 * Control is by voice so the rescuer never lifts their hands:
 *   "READY" = next / start, "BACK" = previous, "STOP" = end compressions.
 * Taps still work as a fallback (shown on screen only when voice is unavailable).
 *
 * Rules:
 * - A sensor never blocks CPR: if hand tracking is lost you can continue anyway.
 * - Stale or low-confidence data is shown as "--" with a warning, never as a number.
 */
import { band, directionText, evaluateCompressions, evaluatePlacement, LIMITS, type PlacementView } from './coach';
import type { Display, Page } from './display/types';
import { SETUP_PAGES, TARGETS } from './guidance';
import type { CompressionMsg, InboundMsg, OutboundMsg, PlacementMsg } from './protocol';
import {
  alignScreen,
  compressScreen,
  BEAT_OFF,
  BEAT_ON,
  FIGURE_DOWN,
  FIGURE_UP,
  readyScreen,
  setupScreen,
  splashScreen,
  summaryScreen,
  type Summary,
} from './screens';
import type { Metronome } from './beeper';
import type { MessageSource } from './sources/types';
import type { Command, VoiceStatus } from './voice/commands';

export type Phase = 'splash' | 'setup' | 'align' | 'ready' | 'compress' | 'summary';
/** Touchpad / ring gestures (fallback controls). */
export type Input = 'tap' | 'double' | 'up' | 'down';
type Action = 'next' | 'back' | 'end';

/** Off target this long while on the ready screen => go back to aligning. */
const READY_DRIFT_MS = 1000;
/** Fraction of each beat the circle is lit. */
const BEAT_ON_FRACTION = 0.4;

export class CoachApp {
  phase: Phase = 'splash';
  voiceStatus: VoiceStatus = 'off';
  private setupIndex = 0;

  private placement?: PlacementMsg;
  private placementAt?: number;
  private prevDistance?: number | null;
  private onTargetSince?: number;
  private offTargetSince?: number;

  private compressions: CompressionMsg[] = [];
  private compressionAt?: number;
  private count = 0;
  /** Last running count the bracelet reported, and its value when this session started. */
  private bandCount?: number;
  private bandCountAtStart?: number;
  private startedAt = 0;
  private stats = { confident: 0, rateOk: 0, depthOk: 0 };
  private summary?: Summary;
  private beatTimer?: ReturnType<typeof setInterval>;
  private metronome?: Metronome;

  private layout = '';
  private listeners: ((phase: Phase) => void)[] = [];

  constructor(
    private display: Display,
    private source: MessageSource,
    private now: () => number = Date.now,
  ) {}

  start(): void {
    this.source.onMessage((m) => this.onMessage(m));
    this.source.onStatus(() => this.render());
    setInterval(() => this.tick(), 250);
    this.render();
  }

  onPhaseChange(cb: (phase: Phase) => void): void {
    this.listeners.push(cb);
  }

  /** Audible beat (phone beep) that follows the same clock as the pace circle. */
  setMetronome(m: Metronome): void {
    this.metronome = m;
  }

  setVoiceStatus(s: VoiceStatus): void {
    this.voiceStatus = s;
    this.render();
  }

  /** A recognized voice command (from speech recognition or the mock panel). */
  command(cmd: Command, heard: string = cmd): void {
    this.send({ type: 'voice_event', ts: this.now(), source: 'glasses', phrase: heard });
    this.act(cmd === 'ready' ? 'next' : cmd === 'back' ? 'back' : 'end');
  }

  /** Touchpad / ring fallback. */
  handleInput(input: Input): void {
    if (input === 'tap' || input === 'down') this.act('next');
    else if (input === 'up') this.act('back');
    else this.act('end');
  }

  // ---------------------------------------------------------------------------

  private act(action: Action): void {
    switch (this.phase) {
      case 'splash':
        if (action === 'next') this.go('setup');
        break;
      case 'setup':
        if (action === 'next') {
          if (this.setupIndex < SETUP_PAGES.length - 1) this.setupIndex++;
          else this.go('align');
        } else if (action === 'back') {
          if (this.setupIndex > 0) this.setupIndex--;
          else this.go('splash');
        }
        break;
      case 'align':
        // Alignment completes by itself. "READY" confirms early when on target,
        // or continues without tracking when the Arduino isn't giving a position.
        if (action === 'next' && this.placementView().status !== 'off_target') this.confirmHands();
        else if (action === 'back') this.go('setup', SETUP_PAGES.length - 1);
        break;
      case 'ready':
        if (action === 'next') this.startCompressions();
        else if (action === 'back') this.go('align');
        break;
      case 'compress':
        if (action === 'end') this.endSession();
        break;
      case 'summary':
        if (action === 'next') this.go('align');
        else if (action === 'back') this.go('splash');
        break;
    }
    this.render();
  }

  private go(phase: Phase, setupIndex = 0): void {
    if (phase === 'setup') this.setupIndex = setupIndex;
    if (phase === 'align') this.onTargetSince = undefined;
    if (phase === 'compress') this.startBeat();
    else this.stopBeat();
    this.phase = phase;
    for (const cb of this.listeners) cb(phase);
  }

  private send(msg: OutboundMsg): void {
    this.source.send(msg);
  }

  private confirmHands(): void {
    this.send({ type: 'confirm', ts: this.now(), source: 'glasses', what: 'hands_placed' });
    this.offTargetSince = undefined;
    this.go('ready');
  }

  private startCompressions(): void {
    this.compressions = [];
    this.compressionAt = undefined;
    this.count = 0;
    this.bandCountAtStart = this.bandCount;
    this.stats = { confident: 0, rateOk: 0, depthOk: 0 };
    this.startedAt = this.now();
    this.send({ type: 'confirm', ts: this.now(), source: 'glasses', what: 'start_compressions' });
    this.go('compress');
  }

  private endSession(): void {
    this.send({ type: 'confirm', ts: this.now(), source: 'glasses', what: 'end_session' });
    this.summary = { count: this.count, durationS: (this.now() - this.startedAt) / 1000, ...this.stats };
    this.go('summary');
  }

  // --- Pace circle, figure and phone beep --------------------------------------

  /** Is the circle lit right now? Derived from the clock, so it never drifts. */
  private beatOn(): boolean {
    const beatMs = 60000 / TARGETS.metronomeBpm;
    return ((this.now() - this.startedAt) % beatMs) / beatMs < BEAT_ON_FRACTION;
  }

  private startBeat(): void {
    this.stopBeat();
    this.metronome?.start(this.startedAt, TARGETS.metronomeBpm);
    let last: boolean | undefined;
    // Poll fast but only send when the state flips (~2 updates per beat).
    this.beatTimer = setInterval(() => {
      const on = this.beatOn();
      if (on === last) return;
      last = on;
      // Circle first (timing cue), then the figure. Image updates are slower than
      // text; if the link can't keep up, frames are dropped, not delayed.
      void this.display.setImage('beat', on ? BEAT_ON : BEAT_OFF);
      void this.display.setImage('figure', on ? FIGURE_DOWN : FIGURE_UP);
    }, 20);
  }

  private stopBeat(): void {
    this.metronome?.stop();
    clearInterval(this.beatTimer);
    this.beatTimer = undefined;
  }

  // --- Sensor data --------------------------------------------------------------

  private onMessage(m: InboundMsg): void {
    const now = this.now();
    if (m.type === 'heartbeat') {
      if (m.count !== null) this.bandCount = m.count;
      return;
    }
    if (m.type === 'placement') {
      this.prevDistance = this.placement?.distance_cm;
      this.placement = m;
      this.placementAt = now;
    } else if (m.type === 'compression' && this.phase === 'compress') {
      this.compressions.push(m);
      if (this.compressions.length > 20) this.compressions.shift();
      this.compressionAt = now;
      if (m.count !== undefined) {
        // Use the bracelet's own count (it confirms the first pushes of a run together),
        // relative to where it stood when this session started.
        this.bandCountAtStart ??= Math.max(0, m.count - 1);
        this.count = Math.max(this.count, m.count - this.bandCountAtStart);
        this.bandCount = m.count;
      } else {
        this.count++;
      }
      if (m.confidence >= LIMITS.minConfidence) {
        this.stats.confident++;
        if (band(m.rate_cpm, TARGETS.rateMinCpm, TARGETS.rateMaxCpm) === 'ok') this.stats.rateOk++;
        if (band(m.depth_cm, TARGETS.depthMinCm, TARGETS.depthMaxCm) === 'ok') this.stats.depthOk++;
      }
    }
    this.tick();
  }

  private placementView(): PlacementView {
    return evaluatePlacement(this.placement, this.prevDistance, this.placementAt, this.now());
  }

  /** Time-based transitions, then render. */
  private tick(): void {
    const now = this.now();
    const v = this.placementView();
    const onTarget = this.source.status === 'connected' && v.status === 'on_target';
    const offTarget = this.source.status === 'connected' && v.status === 'off_target';

    if (onTarget) this.onTargetSince ??= now;
    else this.onTargetSince = undefined;
    if (offTarget) this.offTargetSince ??= now;
    else this.offTargetSince = undefined;

    if (this.phase === 'align' && this.onTargetSince !== undefined && now - this.onTargetSince >= LIMITS.holdOnTargetMs) {
      this.confirmHands();
    } else if (this.phase === 'ready' && this.offTargetSince !== undefined && now - this.offTargetSince >= READY_DRIFT_MS) {
      this.go('align');
    }
    this.render();
  }

  private page(): Page {
    const now = this.now();
    const src = this.source.status;
    const voice = this.voiceStatus;
    switch (this.phase) {
      case 'splash':
        return splashScreen(voice);
      case 'setup':
        return setupScreen(this.setupIndex, voice);
      case 'align':
        return alignScreen(this.placementView(), this.onTargetSince ? now - this.onTargetSince : 0, src, voice);
      case 'ready':
        return readyScreen(this.placementView(), src, voice);
      case 'compress': {
        const pv = this.placementView();
        return compressScreen({
          view: evaluateCompressions(this.compressions, this.compressionAt, now),
          count: this.count,
          elapsedS: (now - this.startedAt) / 1000,
          src,
          voice,
          beatOn: this.beatOn(),
          handsDrift: pv.status === 'off_target' ? directionText(pv.msg?.direction ?? null) : undefined,
        });
      }
      case 'summary':
        return summaryScreen(this.summary!, voice);
    }
  }

  private render(): void {
    const page = this.page();
    if (page.layout !== this.layout) {
      this.layout = page.layout;
      void this.display.show(page);
    } else {
      for (const b of page.boxes) void this.display.update(b.name, b.content);
      // On the compression screen the beat timer drives the images; elsewhere
      // (set-up pictures) follow the page.
      if (page.layout !== 'compress') for (const im of page.images ?? []) void this.display.setImage(im.name, im.frame);
    }
  }
}
