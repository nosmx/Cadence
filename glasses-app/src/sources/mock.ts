import type { CompressionMsg, InboundMsg, OutboundMsg, PlacementMsg } from '../protocol';
import { Emitter, type MessageSource, type SourceStatus } from './types';

/** Knobs the phone-side control panel can turn. */
export interface MockSettings {
  arduinoOnline: boolean;
  /** 'auto' = hands drift toward the spot by themselves; 'manual' = panel sets the reading. */
  placementMode: 'auto' | 'manual';
  manual: { on_target: boolean; direction: PlacementMsg['direction']; distance_cm: number };
  braceletOnline: boolean;
  rate: number;
  depth: number;
  pressure: number;
  confidence: number;
  /** Judges demo: cycle through DEMO_SCRIPT by itself once compressions start. */
  autoDemo: boolean;
}

/**
 * Judges demo, played in a loop while compressing: each step's numbers make the glasses
 * give that advice (rate is checked before depth, so "too shallow" keeps a good rate).
 */
export const DEMO_SCRIPT: { name: string; seconds: number; rate: number; depth: number; pressure: number }[] = [
  { name: 'too fast -> SLOWER', seconds: 10, rate: 134, depth: 5.5, pressure: 0.8 },
  { name: 'too shallow -> PUSH HARDER', seconds: 10, rate: 110, depth: 3.8, pressure: 0.45 },
  { name: 'good -> GOOD', seconds: 10, rate: 110, depth: 5.5, pressure: 0.8 },
];
const DEMO_TOTAL_S = DEMO_SCRIPT.reduce((t, s) => t + s.seconds, 0);

/** Which demo step is playing `seconds` after compressions started. */
export function demoStepAt(seconds: number): (typeof DEMO_SCRIPT)[number] {
  let t = ((seconds % DEMO_TOTAL_S) + DEMO_TOTAL_S) % DEMO_TOTAL_S;
  for (const step of DEMO_SCRIPT) {
    if (t < step.seconds) return step;
    t -= step.seconds;
  }
  return DEMO_SCRIPT[DEMO_SCRIPT.length - 1];
}

export const DEFAULT_MOCK: MockSettings = {
  arduinoOnline: true,
  placementMode: 'auto',
  manual: { on_target: false, direction: 'head', distance_cm: 6 },
  braceletOnline: true,
  rate: 134,
  depth: 5.5,
  pressure: 0.8,
  confidence: 0.9,
  autoDemo: true,
};

const jitter = (amount: number) => (Math.random() * 2 - 1) * amount;

/**
 * Fake Arduino server. Emits `placement` at 5 Hz and, once the app reports that
 * compressions started, one `compression` message per simulated compression.
 */
export class MockSource implements MessageSource {
  readonly name = 'mock';
  status: SourceStatus = 'connected';
  settings: MockSettings = structuredClone(DEFAULT_MOCK);

  private messages = new Emitter<InboundMsg>();
  private statuses = new Emitter<SourceStatus>();
  /** Outbound messages, so the panel can show what the glasses sent. */
  readonly sent = new Emitter<OutboundMsg>();

  // Auto-placement: hand offset from the spot in cm (x = head(+)/feet(-), y = left(+)/right(-)).
  private offset = { x: 9, y: -6 };
  private compressing = false;
  private compressionTimer: ReturnType<typeof setTimeout> | undefined;
  private compressingSince = 0;
  /** The demo step playing now (for the panel), or undefined when not in auto demo. */
  demoStep: string | undefined;

  onMessage(cb: (msg: InboundMsg) => void): void {
    this.messages.on(cb);
  }
  onStatus(cb: (status: SourceStatus) => void): void {
    this.statuses.on(cb);
  }

  start(): void {
    setInterval(() => this.tickPlacement(), 200);
  }

  send(msg: OutboundMsg): void {
    this.sent.emit(msg);
    if (msg.type === 'confirm' && msg.what === 'start_compressions') this.setCompressing(true);
    if (msg.type === 'confirm' && msg.what === 'end_session') {
      this.setCompressing(false);
      this.displaceHands();
    }
  }

  /** Called by the app when the session ends or restarts. */
  setCompressing(on: boolean): void {
    this.compressing = on;
    this.compressingSince = Date.now();
    clearTimeout(this.compressionTimer);
    if (on) this.scheduleCompression();
  }

  /** In auto demo, set rate/depth/pressure from the script for the current moment. */
  private applyDemo(): void {
    if (!this.settings.autoDemo || !this.compressing) {
      this.demoStep = undefined;
      return;
    }
    const step = demoStepAt((Date.now() - this.compressingSince) / 1000);
    Object.assign(this.settings, { rate: step.rate, depth: step.depth, pressure: step.pressure, confidence: 0.9 });
    this.demoStep = step.name;
  }

  /** Knock the hands off the spot again (auto mode). */
  displaceHands(): void {
    const sign = () => (Math.random() < 0.5 ? -1 : 1);
    this.offset = { x: sign() * (5 + Math.random() * 5), y: sign() * (3 + Math.random() * 4) };
  }

  private tickPlacement(): void {
    if (!this.settings.arduinoOnline) return;
    let msg: PlacementMsg;
    if (this.settings.placementMode === 'manual') {
      const m = this.settings.manual;
      msg = {
        type: 'placement', ts: Date.now(), source: 'mock',
        on_target: m.on_target,
        distance_cm: m.on_target ? 0 : m.distance_cm,
        direction: m.on_target ? null : m.direction,
        signal: 0.85,
      };
    } else {
      // Move ~0.4 cm per tick toward the spot, with a little wobble.
      const step = (v: number) => (Math.abs(v) < 0.4 ? v * 0.5 : v - Math.sign(v) * 0.4) + jitter(0.1);
      this.offset = { x: step(this.offset.x), y: step(this.offset.y) };
      const { x, y } = this.offset;
      const dist = Math.hypot(x, y);
      const onTarget = dist < 1.2;
      const direction: PlacementMsg['direction'] = onTarget
        ? null
        : Math.abs(x) >= Math.abs(y)
          ? x > 0 ? 'feet' : 'head'
          : y > 0 ? 'right' : 'left';
      msg = {
        type: 'placement', ts: Date.now(), source: 'mock',
        on_target: onTarget,
        distance_cm: Math.round(dist * 10) / 10,
        direction,
        signal: 0.8 + jitter(0.05),
      };
    }
    this.messages.emit(msg);
  }

  private scheduleCompression(): void {
    this.applyDemo();
    const s = this.settings;
    const interval = (60000 / Math.max(30, s.rate)) * (1 + jitter(0.04));
    this.compressionTimer = setTimeout(() => {
      if (!this.compressing) return;
      if (s.braceletOnline) {
        const msg: CompressionMsg = {
          type: 'compression', ts: Date.now(), source: 'mock',
          rate_cpm: Math.round(s.rate + jitter(3)),
          depth_cm: Math.round((s.depth + jitter(0.3)) * 10) / 10,
          pressure: Math.min(1, Math.max(0, s.pressure + jitter(0.05))),
          quality: s.depth < 5 ? 'shallow' : s.rate < 100 ? 'slow' : s.rate > 120 ? 'fast' : 'good',
          confidence: Math.min(1, Math.max(0, s.confidence + jitter(0.03))),
        };
        this.messages.emit(msg);
      }
      this.scheduleCompression();
    }, interval);
  }
}
