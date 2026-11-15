/**
 * Checks that every screen's text fits its container on the real glasses,
 * using Even's G2 font metrics (@evenrealities/pretext: exact glyph widths,
 * kerning, 27 px line height). Catches overflow before it reaches hardware.
 */
import { measureTextWrap } from '@evenrealities/pretext';
import { describe, expect, it } from 'vitest';
import type { CompressionView, PlacementView } from './coach';
import { validatePage, type Page } from './display/types';
import { SETUP_PAGES } from './guidance';
import {
  alignScreen,
  compressScreen,
  readyScreen,
  setupScreen,
  splashScreen,
  summaryScreen,
} from './screens';
import type { VoiceStatus } from './voice/commands';

/** Must match paddingLength in display/even.ts. */
const PADDING = 6;

function pages(): Page[] {
  const out: Page[] = [];
  const voices: VoiceStatus[] = ['listening', 'loading', 'error'];
  const placements: PlacementView[] = [
    { status: 'waiting' },
    { status: 'lost' },
    { status: 'on_target', msg: { type: 'placement', ts: 0, source: 'mock', on_target: true, distance_cm: 0, direction: null, signal: 0.9 } },
    {
      status: 'off_target', trend: 'farther',
      msg: { type: 'placement', ts: 0, source: 'mock', on_target: false, distance_cm: 12.5, direction: 'right', signal: 0.9 },
    },
  ];
  const views: CompressionView[] = [
    { status: 'waiting' },
    { status: 'lost' },
    { status: 'low_confidence', confidence: 0.3 },
    { status: 'ok', rate: 138, depth: 7.9, pressure: 1, confidence: 0.9, rateBand: 'high', depthBand: 'high' },
    { status: 'ok', rate: 110, depth: 3.1, pressure: 0.5, confidence: 0.9, rateBand: 'ok', depthBand: 'low' },
  ];
  for (const v of voices) {
    out.push(splashScreen(v));
    SETUP_PAGES.forEach((_, i) => out.push(setupScreen(i, v)));
    for (const p of placements) {
      out.push(alignScreen(p, 500, 'connected', v), readyScreen(p, 'connected', v));
      out.push(alignScreen(p, 0, 'disconnected', v), readyScreen(p, 'connecting', v));
    }
    for (const view of views) {
      for (const elapsedS of [0, 119.5, 200]) {
        out.push(compressScreen({ view, count: 1234, elapsedS, src: 'connected', voice: v, beatOn: true }));
      }
      out.push(compressScreen({ view, count: 5, elapsedS: 3, src: 'disconnected', voice: v, beatOn: false }));
      out.push(compressScreen({ view, count: 5, elapsedS: 3, src: 'connected', voice: v, beatOn: false, band: 'paused' }));
      out.push(compressScreen({ view, count: 5, elapsedS: 3, src: 'connected', voice: v, beatOn: false, band: 'alive' }));
      out.push(compressScreen({ view, count: 5, elapsedS: 3, src: 'connected', voice: v, beatOn: false, handsDrift: "MOVE TO PATIENT'S RIGHT" }));
    }
    out.push(summaryScreen({ count: 1234, durationS: 754, confident: 1200, rateOk: 999, depthOk: 1000 }, v));
  }
  return out;
}

describe('every screen fits the G2 display', () => {
  for (const page of pages()) {
    for (const box of page.boxes) {
      it(`${page.layout}/${box.name}: "${box.content.replace(/\n/g, '\\n').slice(0, 50)}"`, () => {
        expect(validatePage(page)).toBeNull();
        const inset = 2 * (PADDING + (box.border ?? 0));
        const m = measureTextWrap(box.content, box.w - inset);
        const explicitLines = box.content.split('\n').length;
        // No unplanned word-wrapping...
        expect(m.lineCount, `wraps: line widths ${m.lineWidths} > ${box.w - inset}`).toBe(explicitLines);
        // ...and every line fits vertically.
        expect(m.height, `too tall for ${box.h - inset}px`).toBeLessThanOrEqual(box.h - inset);
      });
    }
  }
});
