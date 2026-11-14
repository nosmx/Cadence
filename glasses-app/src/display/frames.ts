/**
 * Bitmaps for image containers, drawn at startup on a canvas (no asset files).
 *
 * - Pace circle: "beat-on" (filled disc) / "beat-off" (dim ring), flashed on each beat.
 * - CPR figure: "cpr-up" (arms straight, shoulders high) / "cpr-down" (pushing,
 *   chest compressed), swapped in time with the circle.
 * - Set-up pictures (static): "setup-kneel", "setup-hands", "setup-body".
 *
 * The glasses get PNG bytes (white on black; the host converts to 4-bit grey and
 * the display tints it green). The browser preview gets a green version.
 */

export interface Frame {
  /** PNG bytes for updateImageRawData. */
  png: Uint8Array;
  /** Object URL of a green-tinted copy for the browser preview. */
  previewUrl: string;
}

export type FrameStore = Map<string, Frame>;

export const FIGURE_W = 288;
export const FIGURE_H = 144;
export const BEAT_SIZE = 124;

/** Pace circle: a big filled disc on the beat, a dim ring between beats (so it never vanishes). */
export function drawBeatCircle(ctx: CanvasRenderingContext2D, on: boolean, color: string, dim: string): void {
  const c = BEAT_SIZE / 2;
  ctx.fillStyle = '#000';
  ctx.fillRect(0, 0, BEAT_SIZE, BEAT_SIZE);
  ctx.beginPath();
  if (on) {
    ctx.arc(c, c, c - 2, 0, Math.PI * 2);
    ctx.fillStyle = color;
    ctx.fill();
  } else {
    ctx.arc(c, c, c - 6, 0, Math.PI * 2);
    ctx.strokeStyle = dim;
    ctx.lineWidth = 6;
    ctx.stroke();
  }
}

type P = [number, number];

/** A rescuer pose, in figure coordinates (288 x 144, ground at y = 137). */
interface Pose {
  hip: P;
  shoulder: P;
  /** Shoulder -> (elbow ->) hands. Last point is where the hands are. */
  arms: P[];
  /** Draw stacked hands as a block at the end of the arms. */
  handsOnChest: boolean;
}

interface SceneOpts {
  /** Chest compression depth in px (0..8). */
  depth?: number;
  /** Down arrow (push frame). */
  arrow?: boolean;
  /** Dashed ring around the hand spot on the chest. */
  highlightSpot?: boolean;
  /** Dashed bracket from shoulder height to the hands ("shoulders over hands"). */
  plumbLine?: boolean;
}

const GROUND = 137;
const CHEST_X = 200;
const chestTop = (depth: number) => 107 + depth;

/** Patient + rescuer side view, shared by the set-up pictures and the CPR animation. */
function drawScene(ctx: CanvasRenderingContext2D, pose: Pose, color: string, dim: string, o: SceneOpts = {}): void {
  const w = FIGURE_W;
  const h = FIGURE_H;
  const depth = o.depth ?? 0;
  ctx.fillStyle = '#000';
  ctx.fillRect(0, 0, w, h);
  ctx.lineCap = 'round';
  ctx.lineJoin = 'round';

  const path = (pts: P[]) => {
    ctx.beginPath();
    ctx.moveTo(pts[0][0], pts[0][1]);
    for (const [x, y] of pts.slice(1)) ctx.lineTo(x, y);
  };
  const stroke = (pts: P[], width: number, c: string, dash: number[] = []) => {
    path(pts);
    ctx.setLineDash(dash);
    ctx.strokeStyle = c;
    ctx.lineWidth = width;
    ctx.stroke();
    ctx.setLineDash([]);
  };
  /** Bright limb with a black outline so it reads clearly where it crosses the patient. */
  const limb = (pts: P[], width: number) => {
    stroke(pts, width + 4, '#000');
    stroke(pts, width, color);
  };
  const disc = (x: number, y: number, r: number, c: string, outline = false) => {
    if (outline) disc(x, y, r + 2, '#000');
    ctx.beginPath();
    ctx.arc(x, y, r, 0, Math.PI * 2);
    ctx.fillStyle = c;
    ctx.fill();
  };

  // Ground
  stroke([[4, GROUND + 3], [w - 4, GROUND + 3]], 2, dim);

  // ---- Patient (dim), on their back, head to the right ----
  const top = chestTop(depth);
  stroke([[134, 126], [84, 129], [36, 130]], 13, dim); // legs
  stroke([[36, 130], [30, 120]], 7, dim); // feet pointing up
  ctx.fillStyle = dim;
  ctx.beginPath();
  ctx.moveTo(128, 134);
  ctx.lineTo(128, 118);
  ctx.quadraticCurveTo(160, 112, CHEST_X - 14, top + 2);
  ctx.lineTo(CHEST_X + 14, top + 1);
  ctx.quadraticCurveTo(232, 108, 238, 116);
  ctx.lineTo(238, 134);
  ctx.closePath();
  ctx.fill();
  stroke([[238, 124], [248, 123]], 9, dim); // neck
  disc(260, 121, 12, dim); // head

  // ---- Rescuer (bright), kneeling at the chest ----
  const foot: P = [94, GROUND];
  const knee: P = [146, GROUND - 2];
  limb([foot, knee], 11); // shin on the ground
  limb([knee, pose.hip], 14); // thigh
  limb([pose.hip, pose.shoulder], 18); // back
  // Head continues the line of the back, tipped slightly forward to look at the chest.
  const dx = pose.shoulder[0] - pose.hip[0];
  const dy = pose.shoulder[1] - pose.hip[1];
  const len = Math.hypot(dx, dy);
  const ux = dx / len;
  const uy = dy / len;
  limb([pose.shoulder, [pose.shoulder[0] + ux * 10 + 4, pose.shoulder[1] + uy * 10]], 9);
  disc(pose.shoulder[0] + ux * 22 + 6, pose.shoulder[1] + uy * 22, 12, color, true);
  limb(pose.arms, 9);
  const hands = pose.arms[pose.arms.length - 1];
  if (pose.handsOnChest) {
    ctx.fillStyle = '#000';
    ctx.fillRect(hands[0] - 14, hands[1] - 2, 28, 10);
    ctx.fillStyle = color;
    ctx.fillRect(hands[0] - 12, hands[1], 24, 6);
  }

  if (o.highlightSpot) {
    ctx.setLineDash([5, 4]);
    ctx.strokeStyle = color;
    ctx.lineWidth = 3;
    ctx.beginPath();
    ctx.arc(CHEST_X, top + 2, 20, 0, Math.PI * 2);
    ctx.stroke();
    ctx.setLineDash([]);
  }
  if (o.plumbLine) {
    // Bracket from shoulder height down to the hands: "shoulders straight over hands".
    const bx = CHEST_X + 46;
    const y0 = pose.shoulder[1];
    const y1 = top - 2;
    stroke([[bx, y0], [bx, y1]], 3, color, [5, 4]);
    stroke([[bx - 8, y0], [bx + 8, y0]], 3, color);
    stroke([[bx - 8, y1], [bx + 8, y1]], 3, color);
  }
  if (o.arrow) {
    const ax = CHEST_X + 48;
    stroke([[ax, 30], [ax, 66]], 5, color);
    stroke([[ax - 9, 57], [ax, 68], [ax + 9, 57]], 5, color);
  }
}

/** Compression pose: shoulders straight over the hands, arms locked. */
function cprPose(depth: number): Pose {
  const hands: P = [CHEST_X, chestTop(depth) - 2];
  const shoulder: P = [CHEST_X - 2, 47 + depth]; // arms locked: shoulders drop with the chest
  return { hip: [152, 86 + depth * 0.35], shoulder, arms: [shoulder, [hands[0], hands[1] - 4]], handsOnChest: true };
}

/**
 * CPR animation frame. `push` = 0 (top of stroke) .. 1 (bottom of stroke).
 * Because the arms are locked, the shoulders drop by exactly the compression
 * depth; the hips act as the hinge.
 */
export function drawCprFigure(ctx: CanvasRenderingContext2D, push: number, color: string, dim: string): void {
  const depth = 8 * push;
  drawScene(ctx, cprPose(depth), color, dim, { depth, arrow: push > 0.5 });
}

/** Set-up step 1 - KNEEL: kneeling upright, close to the patient's side, hands resting on thighs. */
export function drawSetupKneel(ctx: CanvasRenderingContext2D, color: string, dim: string): void {
  const shoulder: P = [150, 40];
  drawScene(ctx, { hip: [150, 88], shoulder, arms: [shoulder, [160, 66], [166, 90]], handsOnChest: false }, color, dim);
}

/** Set-up step 2 - HANDS: reaching to the centre of the chest; the hand spot is circled. */
export function drawSetupHands(ctx: CanvasRenderingContext2D, color: string, dim: string): void {
  const shoulder: P = [180, 50];
  const hands: P = [CHEST_X, chestTop(0) - 2];
  drawScene(
    ctx,
    { hip: [150, 88], shoulder, arms: [shoulder, [196, 80], [hands[0], hands[1] - 4]], handsOnChest: true },
    color,
    dim,
    { highlightSpot: true },
  );
}

/** Set-up step 3 - BODY: final position, shoulders over hands (dashed guide), arms locked. */
export function drawSetupBody(ctx: CanvasRenderingContext2D, color: string, dim: string): void {
  drawScene(ctx, cprPose(0), color, dim, { plumbLine: true });
}

type Draw = (ctx: CanvasRenderingContext2D, color: string, dim: string) => void;

async function render(w: number, h: number, draw: Draw, color: string, dim: string): Promise<Blob> {
  const canvas = document.createElement('canvas');
  canvas.width = w;
  canvas.height = h;
  draw(canvas.getContext('2d')!, color, dim);
  return new Promise((resolve, reject) =>
    canvas.toBlob((b) => (b ? resolve(b) : reject(new Error('canvas.toBlob failed'))), 'image/png'),
  );
}

export async function buildFrames(): Promise<FrameStore> {
  const specs: [string, number, number, Draw][] = [
    ['beat-on', BEAT_SIZE, BEAT_SIZE, (c, col, dim) => drawBeatCircle(c, true, col, dim)],
    ['beat-off', BEAT_SIZE, BEAT_SIZE, (c, col, dim) => drawBeatCircle(c, false, col, dim)],
    ['cpr-up', FIGURE_W, FIGURE_H, (c, col, dim) => drawCprFigure(c, 0, col, dim)],
    ['cpr-down', FIGURE_W, FIGURE_H, (c, col, dim) => drawCprFigure(c, 1, col, dim)],
    ['setup-kneel', FIGURE_W, FIGURE_H, drawSetupKneel],
    ['setup-hands', FIGURE_W, FIGURE_H, drawSetupHands],
    ['setup-body', FIGURE_W, FIGURE_H, drawSetupBody],
  ];
  const store: FrameStore = new Map();
  for (const [name, w, h, draw] of specs) {
    const png = new Uint8Array(await (await render(w, h, draw, '#ffffff', '#909090')).arrayBuffer());
    const previewUrl = URL.createObjectURL(await render(w, h, draw, '#3dff7a', '#1f8a42'));
    store.set(name, { png, previewUrl });
  }
  return store;
}
