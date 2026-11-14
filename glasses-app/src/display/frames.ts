/**
 * Bitmaps for image containers, drawn at startup on a canvas (no asset files).
 *
 * The CPR figure has two frames - "up" (arms straight, shoulders high) and
 * "down" (pushing, chest compressed) - swapped in time with the pace dot.
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

/**
 * Draw one frame. `push` = 0 (top of stroke) .. 1 (bottom of stroke).
 *
 * Side view, patient on their back (head right), rescuer kneeling at the chest:
 * shoulders straight above the hands, arms locked. Because the arms are locked,
 * the shoulders drop by exactly the compression depth; the hips act as the hinge.
 */
export function drawCprFigure(ctx: CanvasRenderingContext2D, push: number, color: string, dim: string): void {
  const w = FIGURE_W;
  const h = FIGURE_H;
  ctx.fillStyle = '#000';
  ctx.fillRect(0, 0, w, h);
  ctx.lineCap = 'round';
  ctx.lineJoin = 'round';

  type P = [number, number];
  const path = (pts: P[]) => {
    ctx.beginPath();
    ctx.moveTo(pts[0][0], pts[0][1]);
    for (const [x, y] of pts.slice(1)) ctx.lineTo(x, y);
  };
  const stroke = (pts: P[], width: number, c: string) => {
    path(pts);
    ctx.strokeStyle = c;
    ctx.lineWidth = width;
    ctx.stroke();
  };
  /** Bright limb with a black outline so it reads clearly where it crosses the patient. */
  const limb = (pts: P[], width: number) => {
    stroke(pts, width + 4, '#000');
    stroke(pts, width, color);
  };
  const disc = (x: number, y: number, r: number, c: string, outline = false) => {
    ctx.beginPath();
    ctx.arc(x, y, r + (outline ? 2 : 0), 0, Math.PI * 2);
    ctx.fillStyle = outline ? '#000' : c;
    ctx.fill();
    if (outline) disc(x, y, r, c);
  };

  const ground = 137;
  const depth = 8 * push; // compression depth in px (chest dip = shoulder drop)

  // Ground
  stroke([[4, ground + 3], [w - 4, ground + 3]], 2, dim);

  // ---- Patient (dim) ----
  const chestX = 200;
  const chestTop = 107 + depth;
  // Legs
  stroke([[134, 126], [84, 129], [36, 130]], 13, dim);
  stroke([[36, 130], [30, 120]], 7, dim); // feet pointing up
  // Torso as a filled shape: back on the ground, chest rising under the hands.
  ctx.fillStyle = dim;
  ctx.beginPath();
  ctx.moveTo(128, 134);
  ctx.lineTo(128, 118);
  ctx.quadraticCurveTo(160, 112, chestX - 14, chestTop + 2);
  ctx.lineTo(chestX + 14, chestTop + 1);
  ctx.quadraticCurveTo(232, 108, 238, 116);
  ctx.lineTo(238, 134);
  ctx.closePath();
  ctx.fill();
  stroke([[238, 124], [248, 123]], 9, dim); // neck
  disc(260, 121, 12, dim); // head

  // ---- Rescuer (bright) ----
  const foot: P = [94, ground];
  const knee: P = [146, ground - 2];
  const hip: P = [152, 86 + depth * 0.35];
  const shoulder: P = [chestX - 2, 47 + depth];
  const hands: P = [chestX, chestTop + 2];
  limb([foot, knee], 11); // shin on the ground
  limb([knee, hip], 14); // thigh, nearly upright
  limb([hip, shoulder], 18); // back, leaning forward from the hips
  // Head and neck, looking down at the chest.
  limb([shoulder, [shoulder[0] + 13, shoulder[1] - 8]], 9);
  disc(shoulder[0] + 21, shoulder[1] - 14, 12, color, true);
  // Arms locked straight, shoulders over hands.
  limb([shoulder, [hands[0], hands[1] - 6]], 9);
  // Hands stacked on the centre of the chest.
  ctx.fillStyle = '#000';
  ctx.fillRect(hands[0] - 14, hands[1] - 7, 28, 10);
  ctx.fillStyle = color;
  ctx.fillRect(hands[0] - 12, hands[1] - 5, 24, 6);

  // Push arrow on the down frame.
  if (push > 0.5) {
    const ax = chestX + 48;
    stroke([[ax, 30], [ax, 66]], 5, color);
    stroke([[ax - 9, 57], [ax, 68], [ax + 9, 57]], 5, color);
  }
}

async function render(push: number, color: string, dim: string): Promise<Blob> {
  const canvas = document.createElement('canvas');
  canvas.width = FIGURE_W;
  canvas.height = FIGURE_H;
  const ctx = canvas.getContext('2d')!;
  drawCprFigure(ctx, push, color, dim);
  return new Promise((resolve, reject) =>
    canvas.toBlob((b) => (b ? resolve(b) : reject(new Error('canvas.toBlob failed'))), 'image/png'),
  );
}

export async function buildFrames(): Promise<FrameStore> {
  const store: FrameStore = new Map();
  for (const [name, push] of [['cpr-up', 0], ['cpr-down', 1]] as const) {
    const png = new Uint8Array(await (await render(push, '#ffffff', '#909090')).arrayBuffer());
    const previewUrl = URL.createObjectURL(await render(push, '#3dff7a', '#1f8a42'));
    store.set(name, { png, previewUrl });
  }
  return store;
}
