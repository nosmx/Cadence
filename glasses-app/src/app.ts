/**
 * CPR Coach glasses app: phase state machine + render loop.
 *
 * Flow: splash -> setup (body positioning, 3 pages) -> align (Arduino hand tracking)
 *       -> ready (say "READY" or tap) -> compress (live bracelet feedback) -> summary.
 *
 * Rules:
 * - A sensor never blocks CPR: if hand tracking is lost you can tap past it.
 * - Stale or low-confidence data is shown as "--" with a warning, never as a number.
 */
import { band, evaluateCompressions, evaluatePlacement, LIMITS, type PlacementView } from './coach';
import type { Display, Page } from './display/types';
import { SETUP_PAGES, TARGETS } from './guidance';
import type { CompressionMsg, InboundMsg, OutboundMsg, PlacementMsg } from './protocol';
import {
  alignScreen,
  compressScreen,
  readyScreen,
  setupScreen,
  splashScreen,
  summaryScreen,
  type Summary,
} from './screens';
import type { MessageSource } from './sources/types';

export type Phase = 'splash' | 'setup' | 'align' | 'ready' | 'compress' | 'summary';
export type Input = 'tap' | 'double' | 'up' | 'down';

/** Off target this long while on the ready screen => go back to aligning. */
const READY_DRIFT_MS = 1000;

export class CoachApp {
  phase: Phase = 'splash';
  private setupIndex = 0;

  private placement?: PlacementMsg;
  private placementAt?: number;
  private prevDistance?: number | null;
  private onTargetSince?: number;
  private offTargetSince?: number;

  private compressions: CompressionMsg[] = [];
  private compressionAt?: number;
  private count = 0;
  private startedAt = 0;
  private stats = { confident: 0, rateOk: 0, depthOk: 0 };
  private summary?: Summary;

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

  handleInput(input: Input): void {
    switch (this.phase) {
      case 'splash':
        if (input === 'tap') this.go('setup');
        break;
      case 'setup':
        if (input === 'tap' || input === 'down') {
          if (this.setupIndex < SETUP_PAGES.length - 1) this.setupIndex++;
          else if (input === 'tap') this.go('align');
        } else if (input === 'up') {
          if (this.setupIndex > 0) this.setupIndex--;
          else this.go('splash');
        } else if (input === 'double') this.go('splash');
        break;
      case 'align': {
        const v = this.placementView();
        // Tap confirms when on target, or skips when tracking is unavailable.
        if (input === 'tap' && v.status !== 'off_target') this.confirmHands();
        else if (input === 'up' || input === 'double') this.go('setup', SETUP_PAGES.length - 1);
        break;
      }
      case 'ready':
        if (input === 'tap') this.startCompressions('tap');
        else if (input === 'up' || input === 'double') this.go('align');
        break;
      case 'compress':
        if (input === 'double') this.endSession();
        break;
      case 'summary':
        if (input === 'tap') this.go('align');
        else if (input === 'double') this.go('splash');
        break;
    }
    this.render();
  }

  /** A recognized spoken phrase (from speech-to-text, or the mock panel). */
  voice(phrase: string): void {
    const p = phrase.trim().toLowerCase();
    this.send({ type: 'voice_event', ts: this.now(), source: 'glasses', phrase: p });
    if (this.phase === 'ready' && /\bready\b/.test(p)) this.startCompressions('voice');
    this.render();
  }

  // ---------------------------------------------------------------------------

  private go(phase: Phase, setupIndex = 0): void {
    if (phase === 'setup') this.setupIndex = setupIndex;
    if (phase === 'align') {
      this.onTargetSince = undefined;
    }
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

  private startCompressions(via: 'voice' | 'tap'): void {
    this.compressions = [];
    this.compressionAt = undefined;
    this.count = 0;
    this.stats = { confident: 0, rateOk: 0, depthOk: 0 };
    this.startedAt = this.now();
    this.send({ type: 'confirm', ts: this.now(), source: 'glasses', what: 'start_compressions' });
    console.log(`[app] compressions started via ${via}`);
    this.go('compress');
  }

  private endSession(): void {
    this.send({ type: 'confirm', ts: this.now(), source: 'glasses', what: 'end_session' });
    this.summary = {
      count: this.count,
      durationS: (this.now() - this.startedAt) / 1000,
      ...this.stats,
    };
    this.go('summary');
  }

  private onMessage(m: InboundMsg): void {
    const now = this.now();
    if (m.type === 'placement') {
      this.prevDistance = this.placement?.distance_cm;
      this.placement = m;
      this.placementAt = now;
    } else if (m.type === 'compression' && this.phase === 'compress') {
      this.compressions.push(m);
      if (this.compressions.length > 20) this.compressions.shift();
      this.compressionAt = now;
      this.count++;
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
    switch (this.phase) {
      case 'splash':
        return splashScreen();
      case 'setup':
        return setupScreen(this.setupIndex);
      case 'align':
        return alignScreen(this.placementView(), this.onTargetSince ? now - this.onTargetSince : 0, src);
      case 'ready':
        return readyScreen(this.placementView(), src);
      case 'compress': {
        const pv = this.placementView();
        const drift = pv.status === 'off_target' && pv.msg?.direction ? `move toward ${pv.msg.direction}` : undefined;
        return compressScreen({
          view: evaluateCompressions(this.compressions, this.compressionAt, now),
          count: this.count,
          elapsedS: (now - this.startedAt) / 1000,
          src,
          handsDrift: drift,
        });
      }
      case 'summary':
        return summaryScreen(this.summary!);
    }
  }

  private render(): void {
    const page = this.page();
    if (page.layout !== this.layout) {
      this.layout = page.layout;
      void this.display.show(page);
    } else {
      for (const b of page.boxes) void this.display.update(b.name, b.content);
    }
  }
}
