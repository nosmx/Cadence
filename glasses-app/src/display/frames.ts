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

/** Draw one frame. `push` = 0 (top of stroke) .. 1 (bottom of stroke). */
export function drawCprFigure(ctx: CanvasRenderingContext2D, push: number, color: string, dim: string): void {
  const w = FIGURE_W;
  const h = FIGURE_H;
  ctx.fillStyle = '#000';
  ctx.fillRect(0, 0, w, h);
  ctx.lineCap = 'round';
  ctx.lineJoin = 'round';

  type P = [number, number];
  const line = (pts: P[], width: number, c = color) => {
    ctx.strokeStyle = c;
    ctx.lineWidth = width;
    ctx.beginPath();
    ctx.moveTo(pts[0][0], pts[0][1]);
    for (const [x, y] of pts.slice(1)) ctx.lineTo(x, y);
    ctx.stroke();
  };
  const disc = (x: number, y: number, r: number, c = color) => {
    ctx.fillStyle = c;
    ctx.beginPath();
    ctx.arc(x, y, r, 0, Math.PI * 2);
    ctx.fill();
  };

  const ground = 138;
  const dip = 6 * push; // chest goes down
  const drop = 12 * push; // rescuer's shoulders go down

  // Ground
  line([[6, ground + 3], [w - 6, ground + 3]], 2, dim);

  // Patient on their back, head to the right (dimmer, so the rescuer stands out).
  const chestX = 196;
  const chestY = 118 + dip;
  line([[40, 130], [120, 128], [chestX, chestY], [244, 124]], 10, dim);
  disc(262, 122, 11, dim);

  // Rescuer kneeling beside the chest: shoulders straight over hands, arms locked.
  const foot: P = [70, ground];
  const knee: P = [116, ground];
  const hip: P = [124, 94 + drop * 0.3];
  const shoulder: P = [chestX - 6, 48 + drop];
  const hands: P = [chestX, chestY - 9];
  line([foot, knee, hip], 9); // shin + thigh
  line([hip, shoulder], 13); // back
  line([shoulder, hands], 7); // straight arms
  // Head continues the line of the back.
  const dx = shoulder[0] - hip[0];
  const dy = shoulder[1] - hip[1];
  const len = Math.hypot(dx, dy);
  disc(shoulder[0] + (dx / len) * 22, shoulder[1] + (dy / len) * 22 - 4, 13);
  // Stacked hands on the chest.
  ctx.fillStyle = color;
  ctx.fillRect(hands[0] - 11, hands[1] - 2, 22, 7);

  // Push arrow on the down frame.
  if (push > 0.5) {
    const ax = chestX + 40;
    line([[ax, 44], [ax, 80]], 5);
    line([[ax - 9, 71], [ax, 82], [ax + 9, 71]], 5);
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
