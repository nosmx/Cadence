/**
 * Screen layouts. Each screen is a pure function of the view state and returns
 * a Page of <= 8 text boxes. Same `layout` key between renders => only the text
 * changes (fast textContainerUpgrade path); a new key => page rebuild.
 *
 * Navigation is by voice ("READY" / "BACK" / "STOP") because the rescuer's hands
 * are on the chest. Taps still work as a fallback, and are only advertised when
 * voice isn't available.
 */
import {
  depthAdvice,
  directionText,
  LIMITS,
  mmss,
  rateAdvice,
  type CompressionView,
  type PlacementView,
} from './coach';
import type { Page, TextBox } from './display/types';
import { DISCLAIMER, SETUP_PAGES, TARGETS } from './guidance';
import type { SourceStatus } from './sources/types';
import type { VoiceStatus } from './voice/commands';

const W = 576;

const header = (content: string): TextBox => ({ name: 'header', x: 0, y: 0, w: W, h: 48, content, color: 3 });
const cue = (content: string, y = 56, h = 64): TextBox => ({ name: 'cue', x: 0, y, w: W, h, content, border: 2 });
const footer = (content: string): TextBox => ({ name: 'footer', x: 0, y: 236, w: W, h: 52, content, capture: true, color: 3 });

/** "Say READY to begin", or a tap fallback when voice isn't working. */
export function sayReady(voice: VoiceStatus, what: string): string {
  if (voice === 'listening') return `Say "READY" ${what}`;
  if (voice === 'loading') return `Voice loading... (tap ${what})`;
  return `VOICE OFF - tap ${what}`;
}

export function splashScreen(voice: VoiceStatus): Page {
  return {
    layout: 'splash',
    boxes: [
      cue('CPR COACH', 0, 56),
      { name: 'body', x: 0, y: 72, w: W, h: 150, content: `${DISCLAIMER}\n\nControlled by voice: READY, BACK, STOP` },
      footer(sayReady(voice, 'to begin')),
    ],
  };
}

export function setupScreen(index: number, voice: VoiceStatus): Page {
  const p = SETUP_PAGES[index];
  const last = index === SETUP_PAGES.length - 1;
  return {
    layout: 'setup',
    boxes: [
      header(`SET UP  ${index + 1}/${SETUP_PAGES.length}  -  ${p.title}`),
      { name: 'body', x: 0, y: 56, w: W, h: 168, content: p.body, border: 2 },
      footer(sayReady(voice, last ? 'to align hands' : 'for next')),
    ],
  };
}

function trackingLine(src: SourceStatus, view: PlacementView): string {
  if (src !== 'connected') return `ARDUINO ${src.toUpperCase()}`;
  if (view.status === 'lost') return 'LOCATION SENSOR LOST - check Arduino';
  if (view.status === 'waiting') return 'Waiting for Arduino...';
  return `Arduino OK   signal ${Math.round((view.msg?.signal ?? 0) * 100)}%`;
}

export function alignScreen(view: PlacementView, holdMs: number, src: SourceStatus, voice: VoiceStatus): Page {
  let cueText: string;
  let detail: string;
  let foot = trackingLine(src, view);
  const sensorDown = src !== 'connected' || view.status === 'lost' || view.status === 'waiting';
  if (sensorDown) {
    cueText = view.status === 'waiting' && src === 'connected' ? 'WAITING FOR HAND TRACKING' : 'HAND TRACKING LOST';
    detail = 'Place hands as in the set-up steps.';
    foot = sayReady(voice, 'to continue anyway');
  } else if (view.status === 'on_target') {
    const left = Math.max(0, LIMITS.holdOnTargetMs - holdMs) / 1000;
    cueText = 'ON SPOT - HOLD STILL';
    detail = `Locking in... ${left.toFixed(1)} s`;
  } else {
    const m = view.msg!;
    cueText = directionText(m.direction);
    const dist = m.distance_cm === null ? 'distance unknown' : `${m.distance_cm.toFixed(1)} cm away`;
    const trend = view.trend === 'closer' ? '   CLOSER' : view.trend === 'farther' ? '   FARTHER' : '';
    detail = `${dist}${trend}`;
  }
  return {
    layout: 'align',
    boxes: [
      header('ALIGN HANDS ON THE CHEST'),
      cue(cueText),
      { name: 'detail', x: 0, y: 128, w: W, h: 100, content: detail },
      footer(foot),
    ],
  };
}

export function readyScreen(view: PlacementView, src: SourceStatus, voice: VoiceStatus): Page {
  const tracking = src === 'connected' && (view.status === 'on_target' || view.status === 'off_target');
  return {
    layout: 'ready',
    boxes: [
      header(tracking ? 'HANDS IN PLACE' : 'HANDS PLACED (NOT TRACKED)'),
      cue(voice === 'listening' ? 'Say "READY" to start' : 'Tap to start'),
      { name: 'detail', x: 0, y: 128, w: W, h: 100, content: 'Keep your hands where they are.\nPush in time with the dot.' },
      footer(voice === 'listening' ? trackingLine(src, view) : sayReady(voice, 'to start')),
    ],
  };
}

/** Pace dot, drawn with text (no image refresh needed). Pulses bright/dim. */
const D = '●'; // filled circle - confirm the G2 font has it (the simulator shows a placeholder if not)
export const DOT = [`  ${D.repeat(3)}`, ` ${D.repeat(5)}`, D.repeat(7), ` ${D.repeat(5)}`, `  ${D.repeat(3)}`].join('\n');
export const DOT_BRIGHT = 4;
export const DOT_DIM = 1;

export interface CompressState {
  view: CompressionView;
  count: number;
  elapsedS: number;
  src: SourceStatus;
  voice: VoiceStatus;
  beatOn: boolean;
  /** Set when the Arduino reports the hands have drifted off the spot. */
  handsDrift?: string;
}

/** One instruction at a time, most important first. */
export function compressAdvice(s: CompressState): string {
  const v = s.view;
  if (s.src !== 'connected' || v.status === 'lost') return 'NO BRACELET DATA\n\nKeep pushing with the dot';
  if (v.status === 'waiting') return 'START PUSHING\n\nPush with the dot';
  if (v.status === 'low_confidence') return 'READING UNCLEAR\n\nKeep pushing with the dot';
  if (s.handsDrift) return `HANDS DRIFTED\n\n${s.handsDrift}`;
  if (v.rateBand !== 'ok') return `${rateAdvice(v.rateBand)}\n\nMatch the dot`;
  if (v.depthBand !== 'ok') return `${depthAdvice(v.depthBand)}\n\nKeep the pace`;
  return 'GOOD\n\nKeep going';
}

export function compressScreen(s: CompressState): Page {
  const v = s.view;
  const nums = v.status === 'ok'
    ? `${Math.round(v.rate!)} /min     ${v.depth!.toFixed(1)} cm     pressure ${Math.round((v.pressure ?? 0) * 100)}%`
    : '-- /min     -- cm     (no reliable data)';
  const swapLeft = TARGETS.swapSeconds - s.elapsedS;
  const swap = swapLeft > 0 ? `swap in ${mmss(swapLeft)}` : 'SWAP RESCUER NOW';
  const end = s.voice === 'listening' ? 'say STOP to end' : 'double tap to end';

  return {
    layout: 'compress',
    boxes: [
      { name: 'dot', x: 0, y: 0, w: 168, h: 170, content: DOT, color: s.beatOn ? DOT_BRIGHT : DOT_DIM },
      { name: 'cue', x: 176, y: 0, w: 400, h: 170, content: compressAdvice(s), border: 2 },
      { name: 'nums', x: 0, y: 178, w: W, h: 52, content: nums, color: 3 },
      footer(`Count ${s.count}    ${swap}    ${end}`),
    ],
  };
}

export interface Summary {
  count: number;
  durationS: number;
  confident: number;
  rateOk: number;
  depthOk: number;
}

export function summaryScreen(s: Summary, voice: VoiceStatus): Page {
  const pct = (n: number) => (s.confident ? `${Math.round((n / s.confident) * 100)}%` : '--');
  return {
    layout: 'summary',
    boxes: [
      header('SESSION ENDED'),
      {
        name: 'body', x: 0, y: 56, w: W, h: 168, border: 2,
        content:
          `Compressions: ${s.count}    Time: ${mmss(s.durationS)}\n` +
          `Rate in target: ${pct(s.rateOk)}\n` +
          `Depth in target: ${pct(s.depthOk)}\n` +
          `(of ${s.confident} confident readings)`,
      },
      footer(sayReady(voice, 'to go again')),
    ],
  };
}
