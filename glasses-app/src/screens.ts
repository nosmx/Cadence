/**
 * Screen layouts. Each screen is a pure function of the view state and returns
 * a Page of <= 8 text boxes. Same `layout` key between renders => only the text
 * changes (fast textContainerUpgrade path); a new key => page rebuild.
 */
import {
  depthAdvice,
  directionText,
  gauge,
  LIMITS,
  mmss,
  rateAdvice,
  type CompressionView,
  type PlacementView,
} from './coach';
import type { Page, TextBox } from './display/types';
import { DISCLAIMER, SETUP_PAGES, TARGETS } from './guidance';
import type { SourceStatus } from './sources/types';

const W = 576;

const header = (content: string): TextBox => ({ name: 'header', x: 0, y: 0, w: W, h: 48, content, color: 3 });
const cue = (content: string, y = 56, h = 64): TextBox => ({ name: 'cue', x: 0, y, w: W, h, content, border: 2 });
const footer = (content: string): TextBox => ({ name: 'footer', x: 0, y: 236, w: W, h: 52, content, capture: true, color: 3 });

export function splashScreen(): Page {
  return {
    layout: 'splash',
    boxes: [
      cue('CPR COACH', 0, 56),
      { name: 'body', x: 0, y: 72, w: W, h: 150, content: `${DISCLAIMER}\n\nSet up > align hands > compress` },
      footer('Tap to begin'),
    ],
  };
}

export function setupScreen(index: number): Page {
  const p = SETUP_PAGES[index];
  const last = index === SETUP_PAGES.length - 1;
  return {
    layout: 'setup',
    boxes: [
      header(`SET UP  ${index + 1}/${SETUP_PAGES.length}  -  ${p.title}`),
      { name: 'body', x: 0, y: 56, w: W, h: 168, content: p.body, border: 2 },
      footer(`${last ? 'Tap: align hands' : 'Tap: next'}    Swipe up: back`),
    ],
  };
}

function placementFooter(src: SourceStatus, view: PlacementView): string {
  if (src !== 'connected') return `ARDUINO ${src.toUpperCase()}`;
  if (view.status === 'lost') return 'LOCATION SENSOR LOST - check Arduino';
  if (view.status === 'waiting') return 'Waiting for Arduino...';
  return `Arduino OK   signal ${Math.round((view.msg?.signal ?? 0) * 100)}%`;
}

export function alignScreen(view: PlacementView, holdMs: number, src: SourceStatus): Page {
  let cueText: string;
  let detail: string;
  const sensorDown = src !== 'connected' || view.status === 'lost' || view.status === 'waiting';
  if (sensorDown) {
    cueText = view.status === 'waiting' && src === 'connected' ? 'WAITING FOR HAND TRACKING' : 'HAND TRACKING LOST';
    detail = 'Place hands by the set-up steps.\nTap to continue without tracking.';
  } else if (view.status === 'on_target') {
    const left = Math.max(0, LIMITS.holdOnTargetMs - holdMs) / 1000;
    cueText = 'ON SPOT - HOLD STILL';
    detail = `Locking in... ${left.toFixed(1)} s\n(or tap to confirm)`;
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
      footer(placementFooter(src, view)),
    ],
  };
}

export function readyScreen(view: PlacementView, src: SourceStatus): Page {
  const tracking = src === 'connected' && (view.status === 'on_target' || view.status === 'off_target');
  return {
    layout: 'ready',
    boxes: [
      header(tracking ? 'HANDS IN PLACE' : 'HANDS PLACED (NOT TRACKED)'),
      cue('Say "READY" to start'),
      { name: 'detail', x: 0, y: 128, w: W, h: 100, content: 'or tap to start compressions.\nKeep your hands where they are.' },
      footer(placementFooter(src, view)),
    ],
  };
}

export interface CompressState {
  view: CompressionView;
  count: number;
  elapsedS: number;
  src: SourceStatus;
  /** Set when the Arduino reports the hands have drifted off the spot. */
  handsDrift?: string;
}

export function compressScreen(s: CompressState): Page {
  const v = s.view;
  const ok = v.status === 'ok';
  const lostSrc = s.src !== 'connected';

  let cueText: string;
  if (lostSrc || v.status === 'lost') cueText = 'NO BRACELET DATA - KEEP PUSHING';
  else if (v.status === 'waiting') cueText = 'START PUSHING';
  else if (v.status === 'low_confidence') cueText = 'LOW CONFIDENCE - KEEP PUSHING';
  else cueText = `${rateAdvice(v.rateBand)}   -   ${depthAdvice(v.depthBand)}`;

  const rate = ok
    ? `RATE  ${Math.round(v.rate!)} /min\n${gauge(v.rate!, 60, 160, TARGETS.rateMinCpm, TARGETS.rateMaxCpm)}`
    : 'RATE  -- /min\n(no reliable data)';
  const depth = ok
    ? `DEPTH  ${v.depth!.toFixed(1)} cm\n${gauge(v.depth!, 2, 8, TARGETS.depthMinCm, TARGETS.depthMaxCm)}`
    : 'DEPTH  -- cm\n(no reliable data)';
  const pressPct = ok ? Math.round((v.pressure ?? 0) * 100) : undefined;
  const press = pressPct !== undefined
    ? `PRESSURE  ${pressPct}%\n${'#'.repeat(Math.round(pressPct / 100 * 14)).padEnd(14, '.')}`
    : 'PRESSURE  --\n(no reliable data)';

  const swapLeft = TARGETS.swapSeconds - s.elapsedS;
  const count = `COUNT  ${s.count}\n${swapLeft > 0 ? `SWAP IN ${mmss(swapLeft)}` : 'SWAP RESCUER NOW'}`;

  let status: string;
  if (lostSrc) status = `ARDUINO ${s.src.toUpperCase()}`;
  else if (v.status === 'lost') status = 'BRACELET SILENT - check strap';
  else if (v.status === 'low_confidence') status = `Bracelet conf ${Math.round((v.confidence ?? 0) * 100)}% (low)`;
  else if (s.handsDrift) status = `HANDS DRIFTED - ${s.handsDrift}`;
  else status = `Bracelet OK${ok ? `  conf ${Math.round((v.confidence ?? 0) * 100)}%` : ''}   2x tap: end`;

  return {
    layout: 'compress',
    boxes: [
      cue(cueText, 0, 60),
      { name: 'rate', x: 0, y: 68, w: 284, h: 78, content: rate },
      { name: 'depth', x: 292, y: 68, w: 284, h: 78, content: depth },
      { name: 'press', x: 0, y: 152, w: 284, h: 78, content: press },
      { name: 'count', x: 292, y: 152, w: 284, h: 78, content: count },
      footer(status),
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

export function summaryScreen(s: Summary): Page {
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
      footer('Tap to start again'),
    ],
  };
}
