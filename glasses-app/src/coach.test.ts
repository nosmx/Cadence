import { describe, expect, it } from 'vitest';
import { evaluateCompressions, evaluatePlacement, LIMITS } from './coach';
import type { CompressionMsg, PlacementMsg } from './protocol';
import { parseMessage } from './protocol';
import { compressAdvice, compressScreen } from './screens';
import { parseCommand } from './voice/commands';
import { validatePage } from './display/types';

const comp = (ts: number, rate: number, depth: number, confidence = 0.9): CompressionMsg => ({
  type: 'compression', ts, source: 'mock', rate_cpm: rate, depth_cm: depth, pressure: 0.7, quality: '', confidence,
});

describe('evaluateCompressions', () => {
  it('waits before any data', () => {
    expect(evaluateCompressions([], undefined, 0).status).toBe('waiting');
  });

  it('reports lost when data is stale - never shows the old number', () => {
    const v = evaluateCompressions([comp(0, 110, 5.5)], 0, LIMITS.compressionStaleMs + 1);
    expect(v.status).toBe('lost');
    expect(v.rate).toBeUndefined();
  });

  it('withholds numbers when confidence is low', () => {
    const v = evaluateCompressions([comp(0, 110, 5.5, 0.3)], 0, 100);
    expect(v.status).toBe('low_confidence');
    expect(v.rate).toBeUndefined();
  });

  it('advises faster / slower / good from the median rate', () => {
    const at = (rate: number) => evaluateCompressions([comp(0, rate, 5.5), comp(500, rate, 5.5)], 500, 600).rateBand;
    expect(at(90)).toBe('low');
    expect(at(110)).toBe('ok');
    expect(at(130)).toBe('high');
  });

  it('ignores a single outlier thanks to the median', () => {
    const msgs = [comp(0, 110, 5.5), comp(500, 110, 5.5), comp(1000, 170, 5.5)];
    expect(evaluateCompressions(msgs, 1000, 1100).rateBand).toBe('ok');
  });
});

describe('evaluatePlacement', () => {
  const p = (dist: number, on = false): PlacementMsg => ({
    type: 'placement', ts: 0, source: 'mock', on_target: on, distance_cm: dist, direction: on ? null : 'head', signal: 0.9,
  });
  it('detects closer / farther trend', () => {
    expect(evaluatePlacement(p(3), 5, 0, 10).trend).toBe('closer');
    expect(evaluatePlacement(p(6), 5, 0, 10).trend).toBe('farther');
  });
  it('uses the sender trend when distance is unknown', () => {
    const m: PlacementMsg = { ...p(0), distance_cm: null, trend: 'closer' };
    expect(evaluatePlacement(m, null, 0, 10).trend).toBe('closer');
    expect(parseMessage({ type: 'placement', on_target: false, distance_cm: null, signal: 0.5, trend: 'farther' })).toMatchObject({ trend: 'farther' });
  });
  it('reports lost when the Arduino goes quiet', () => {
    expect(evaluatePlacement(p(0, true), 0, 0, LIMITS.placementStaleMs + 1).status).toBe('lost');
  });
});

describe('parseMessage', () => {
  it('rejects malformed compression messages', () => {
    expect(parseMessage({ type: 'compression', rate_cpm: 'fast' })).toBeNull();
    expect(parseMessage(null)).toBeNull();
  });
  it('accepts a placement message and defaults unknown direction to null', () => {
    const m = parseMessage({ type: 'placement', on_target: false, distance_cm: 3, direction: 'up', signal: 0.5 });
    expect(m).toMatchObject({ type: 'placement', direction: null, distance_cm: 3 });
  });
});

describe('screens', () => {
  const base = { count: 10, elapsedS: 30, src: 'connected' as const, voice: 'listening' as const, beatOn: true };
  it('compress screen fits G2 limits and hides numbers when lost', () => {
    const page = compressScreen({ ...base, view: { status: 'lost' } });
    expect(validatePage(page)).toBeNull();
    expect(page.boxes.find((b) => b.name === 'nums')!.content).toContain('--');
    expect(page.boxes.find((b) => b.name === 'cue')!.content).toContain('NO BRACELET DATA');
  });
  it('tells a paused band apart from a lost one (sensing heartbeat)', () => {
    const lost = { ...base, view: { status: 'lost' as const } };
    expect(compressAdvice({ ...lost, band: 'paused' })).toMatch(/^HANDS OFF/);
    expect(compressAdvice({ ...lost, band: 'alive' })).toMatch(/^FINDING RHYTHM/);
    expect(compressAdvice(lost)).toMatch(/^NO BRACELET DATA/);
    expect(compressAdvice({ ...lost, src: 'disconnected', band: 'paused' })).toMatch(/^NO BRACELET DATA/);
  });
  it('gives one instruction at a time: rate before depth', () => {
    const view = { status: 'ok' as const, rate: 90, depth: 4, rateBand: 'low' as const, depthBand: 'low' as const };
    expect(compressAdvice({ ...base, view })).toMatch(/^FASTER/);
    expect(compressAdvice({ ...base, view: { ...view, rate: 110, rateBand: 'ok' as const } })).toMatch(/^PUSH HARDER/);
  });
});

describe('parseCommand', () => {
  it('maps spoken text to commands', () => {
    expect(parseCommand('ready')).toBe('ready');
    expect(parseCommand('next')).toBe('ready');
    expect(parseCommand('[unk] back')).toBe('back');
    expect(parseCommand('stop')).toBe('stop');
    expect(parseCommand('[unk]')).toBeNull();
  });
});
