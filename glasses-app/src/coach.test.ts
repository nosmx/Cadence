import { describe, expect, it } from 'vitest';
import { evaluateCompressions, evaluatePlacement, LIMITS } from './coach';
import type { CompressionMsg, PlacementMsg } from './protocol';
import { parseMessage } from './protocol';
import { compressAdvice, compressScreen, labelAdvice } from './screens';
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

describe('sensing program messages', () => {
  const sensing = parseMessage({
    type: 'compression', ts: 0, src: 'band', source: 'band', count: 37, rate_cpm: 92.2, depth_cm: 2.6,
    push_intensity_g: 1.17, pressure: 0.62, quality: 'faster', quality_full: 'faster', confidence: 0.7, low_confidence: false,
  }) as CompressionMsg;
  it('shows the sensing numbers and label unchanged (matches its terminal output)', () => {
    const v = evaluateCompressions([comp(-500, 120, 5.5), sensing], 0, 10);
    expect(v).toMatchObject({ status: 'ok', rate: 92.2, depth: 2.6, pushG: 1.17, label: 'faster' });
    const nums = compressScreen({ ...base, view: v }).boxes.find((b) => b.name === 'nums')!.content;
    expect(nums).toBe('92.2 /min     2.6 cm     push 1.17 g');
    expect(compressAdvice({ ...base, view: v })).toBe('FASTER - match the circle');
  });
  it('uses the sensing low-confidence flag, not our own threshold', () => {
    expect(evaluateCompressions([{ ...sensing, confidence: 0.55, low_confidence: false }], 0, 10).status).toBe('ok');
    expect(evaluateCompressions([{ ...sensing, confidence: 0.45, low_confidence: true }], 0, 10).status).toBe('low_confidence');
  });
  it('maps every sensing label to one line of advice', () => {
    expect(labelAdvice('release fully')).toBe('RELEASE FULLY - let the chest rise');
    expect(labelAdvice('lighter')).toMatch(/^LESS DEEP/);
  });
});

const base = { count: 10, elapsedS: 30, src: 'connected' as const, voice: 'listening' as const, beatOn: true };

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
