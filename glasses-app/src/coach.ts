/**
 * Live compression feedback. Plain, deterministic code - never an LLM.
 */
import type { CompressionMsg, PlacementMsg } from './protocol';
import { TARGETS } from './guidance';

export const LIMITS = {
  /** No compression message for this long => treat bracelet data as lost. */
  compressionStaleMs: 1500,
  /** No placement message for this long => treat Arduino location as lost. */
  placementStaleMs: 1500,
  /** Below this confidence, never show numbers as if they were solid. */
  minConfidence: 0.6,
  /** Window of recent compressions used to smooth the advice. */
  windowMs: 4000,
  windowMax: 5,
  /** Hands must stay on target this long before alignment is accepted. */
  holdOnTargetMs: 1500,
};

export type Band = 'low' | 'ok' | 'high';

export function band(v: number, min: number, max: number): Band {
  if (v < min) return 'low';
  if (v > max) return 'high';
  return 'ok';
}

function median(xs: number[]): number {
  const s = [...xs].sort((a, b) => a - b);
  const mid = s.length >> 1;
  return s.length % 2 ? s[mid] : (s[mid - 1] + s[mid]) / 2;
}

export type CompressionStatus = 'waiting' | 'lost' | 'low_confidence' | 'ok';

export interface CompressionView {
  status: CompressionStatus;
  /** Only set when status === 'ok'. */
  rate?: number;
  depth?: number;
  pressure?: number;
  rateBand?: Band;
  depthBand?: Band;
  confidence?: number;
  /** The sensing program's own label, when it sent one (shown as is). */
  label?: string;
  /** Push strength in g, when the sender measures it. */
  pushG?: number;
}

/**
 * Turn the recent compression history into what the screen should show.
 * `recent` is newest-last; `receivedAt` is the local time the newest one arrived.
 */
export function evaluateCompressions(
  recent: CompressionMsg[],
  receivedAt: number | undefined,
  now: number,
): CompressionView {
  if (recent.length === 0 || receivedAt === undefined) return { status: 'waiting' };
  if (now - receivedAt > LIMITS.compressionStaleMs) return { status: 'lost' };

  const last = recent[recent.length - 1];
  // The sensing program decides confidence itself (low_confidence below 0.5); otherwise use ours.
  const low = last.low_confidence ?? last.confidence < LIMITS.minConfidence;
  if (low) return { status: 'low_confidence', confidence: last.confidence };

  if (last.quality_full !== undefined) {
    // From the sensing program: it already smooths the rate and picks the label, so show
    // its numbers unchanged - the glasses then match its output line for line.
    return {
      status: 'ok',
      rate: last.rate_cpm,
      depth: last.depth_cm,
      pressure: last.pressure,
      pushG: last.push_g,
      confidence: last.confidence,
      label: last.quality_full,
      rateBand: band(last.rate_cpm, TARGETS.rateMinCpm, TARGETS.rateMaxCpm),
      depthBand: band(last.depth_cm, TARGETS.depthMinCm, TARGETS.depthMaxCm),
    };
  }

  // Smooth over recent confident samples so the advice doesn't flicker.
  const window = recent
    .filter((m) => m.confidence >= LIMITS.minConfidence && last.ts - m.ts <= LIMITS.windowMs)
    .slice(-LIMITS.windowMax);
  const rate = median(window.map((m) => m.rate_cpm));
  const depth = median(window.map((m) => m.depth_cm));
  return {
    status: 'ok',
    rate,
    depth,
    pressure: last.pressure,
    confidence: last.confidence,
    rateBand: band(rate, TARGETS.rateMinCpm, TARGETS.rateMaxCpm),
    depthBand: band(depth, TARGETS.depthMinCm, TARGETS.depthMaxCm),
  };
}

export function rateAdvice(b: Band | undefined): string {
  return b === 'low' ? 'FASTER' : b === 'high' ? 'SLOWER' : b === 'ok' ? 'GOOD RATE' : '';
}

export function depthAdvice(b: Band | undefined): string {
  return b === 'low' ? 'PUSH HARDER' : b === 'high' ? 'LESS DEEP' : b === 'ok' ? 'GOOD DEPTH' : '';
}

export type PlacementStatus = 'waiting' | 'lost' | 'off_target' | 'on_target';

export interface PlacementView {
  status: PlacementStatus;
  msg?: PlacementMsg;
  /** 'closer' / 'farther' compared to the previous reading, when known. */
  trend?: 'closer' | 'farther' | 'steady';
}

export function evaluatePlacement(
  msg: PlacementMsg | undefined,
  prevDistance: number | null | undefined,
  receivedAt: number | undefined,
  now: number,
): PlacementView {
  if (!msg || receivedAt === undefined) return { status: 'waiting' };
  if (now - receivedAt > LIMITS.placementStaleMs) return { status: 'lost' };
  let trend: PlacementView['trend'] = msg.trend ?? undefined;
  if (msg.distance_cm !== null && prevDistance !== null && prevDistance !== undefined) {
    const d = msg.distance_cm - prevDistance;
    trend = d < -0.3 ? 'closer' : d > 0.3 ? 'farther' : 'steady';
  }
  return { status: msg.on_target ? 'on_target' : 'off_target', msg, trend };
}

export function directionText(d: PlacementMsg['direction']): string {
  switch (d) {
    case 'head': return 'MOVE TOWARD HEAD';
    case 'feet': return 'MOVE TOWARD FEET';
    case 'left': return "MOVE TO PATIENT'S LEFT";
    case 'right': return "MOVE TO PATIENT'S RIGHT";
    default: return 'ADJUST HANDS';
  }
}

export function mmss(totalSeconds: number): string {
  const s = Math.max(0, Math.ceil(totalSeconds));
  return `${Math.floor(s / 60)}:${String(s % 60).padStart(2, '0')}`;
}
