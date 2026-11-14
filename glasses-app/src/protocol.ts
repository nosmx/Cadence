/**
 * Message format between the Arduino server and the glasses app.
 *
 * DRAFT: the Arduino server (which relays the bracelet's data) owns the final
 * schema. Keep every assumption about field names in this file and in
 * `parseMessage`, so changing the format later touches one place.
 */

export type Source = 'arduino' | 'bracelet' | 'glasses' | 'mock';

interface Base {
  /** Sender clock, ms since epoch. */
  ts: number;
  source: Source;
}

/** Arduino -> glasses: where the rescuer's hands are relative to the target spot. */
export interface PlacementMsg extends Base {
  type: 'placement';
  /** True when the hands are on the compression spot. */
  on_target: boolean;
  /** Distance from the hands to the spot, or null if the Arduino can't tell. */
  distance_cm: number | null;
  /** Which way to move, relative to the patient. null when on target or unknown. */
  direction: 'head' | 'feet' | 'left' | 'right' | null;
  /** Signal quality 0..1. */
  signal: number;
}

/** Bracelet (relayed by Arduino) -> glasses: one message per detected compression. */
export interface CompressionMsg extends Base {
  type: 'compression';
  /** Compressions per minute, as computed by the bracelet. */
  rate_cpm: number;
  /** Estimated depth in cm. UNVERIFIED until ruler-tested. */
  depth_cm: number;
  /** Relative pressure 0..1. Units/meaning TBD with the bracelet owner. */
  pressure: number;
  /** Bracelet's own quality label, e.g. "good" | "shallow" | "fast". */
  quality: string;
  /** 0..1. Below the threshold the app must not show numbers as solid. */
  confidence: number;
}

/** Glasses -> Arduino/hub. */
export interface VoiceEventMsg extends Base {
  type: 'voice_event';
  phrase: string;
}

export interface ConfirmMsg extends Base {
  type: 'confirm';
  what: 'hands_placed' | 'start_compressions' | 'end_session';
}

export type InboundMsg = PlacementMsg | CompressionMsg;
export type OutboundMsg = VoiceEventMsg | ConfirmMsg;

const num = (v: unknown): number | undefined =>
  typeof v === 'number' && Number.isFinite(v) ? v : undefined;

/** Validate untrusted JSON from the network. Returns null for anything malformed. */
export function parseMessage(raw: unknown): InboundMsg | null {
  if (typeof raw !== 'object' || raw === null) return null;
  const m = raw as Record<string, unknown>;
  const ts = num(m.ts) ?? Date.now();
  const source = (typeof m.source === 'string' ? m.source : 'arduino') as Source;

  if (m.type === 'placement') {
    const dirs = ['head', 'feet', 'left', 'right'] as const;
    const direction = dirs.find((d) => d === m.direction) ?? null;
    return {
      type: 'placement',
      ts,
      source,
      on_target: m.on_target === true,
      distance_cm: num(m.distance_cm) ?? null,
      direction,
      signal: num(m.signal) ?? 0,
    };
  }

  if (m.type === 'compression') {
    const rate = num(m.rate_cpm);
    const depth = num(m.depth_cm);
    if (rate === undefined || depth === undefined) return null;
    return {
      type: 'compression',
      ts,
      source,
      rate_cpm: rate,
      depth_cm: depth,
      pressure: num(m.pressure) ?? 0,
      quality: typeof m.quality === 'string' ? m.quality : '',
      confidence: num(m.confidence) ?? 0,
    };
  }

  return null;
}
