/**
 * Minimal display model that maps 1:1 onto G2 containers.
 *
 * G2 limits (SDK 0.0.16): <= 12 containers per page, <= 8 text containers,
 * <= 4 image containers (20..288 x 20..144 px), exactly one container with event capture.
 * Text has no font-size or alignment control - emphasis comes from layout and borders.
 * Text updates are the fast path; image updates are slower (measure on hardware).
 */

export const SCREEN_W = 576;
export const SCREEN_H = 288;
export const MAX_TEXT_BOXES = 8;
export const MAX_IMAGE_BOXES = 4;
export const MAX_CONTAINERS = 12;

export interface TextBox {
  /** Unique within the page; also used as containerName (keep it short). */
  name: string;
  x: number;
  y: number;
  w: number;
  h: number;
  content: string;
  /** Border thickness in px (0 = none). */
  border?: number;
  /** Brightness 0..4 (default 4). */
  color?: number;
  /** Exactly one box per page should capture input. */
  capture?: boolean;
}

export interface ImageBox {
  name: string;
  x: number;
  y: number;
  w: number;
  h: number;
  /** Key of the bitmap to show (see display/frames.ts). */
  frame: string;
}

export interface Page {
  /** Same layout key => only content changes; different key => page rebuild. */
  layout: string;
  boxes: TextBox[];
  images?: ImageBox[];
}

export interface Display {
  /** Replace the whole page (slow: rebuilds containers). */
  show(page: Page): Promise<void>;
  /**
   * Change one box's text and optionally its brightness (fast path).
   * Implementations skip updates that change nothing.
   */
  update(name: string, content: string, color?: number): Promise<void>;
  /** Show a different bitmap in an image box. Skipped if unchanged. */
  setImage(name: string, frame: string): Promise<void>;
}

export function validatePage(page: Page): string | null {
  const images = page.images ?? [];
  if (page.boxes.length > MAX_TEXT_BOXES) return `too many text boxes (${page.boxes.length} > ${MAX_TEXT_BOXES})`;
  if (images.length > MAX_IMAGE_BOXES) return `too many image boxes (${images.length} > ${MAX_IMAGE_BOXES})`;
  if (page.boxes.length + images.length > MAX_CONTAINERS) return 'too many containers';
  const captures = page.boxes.filter((b) => b.capture).length;
  if (captures !== 1) return `expected exactly 1 capture box, got ${captures}`;
  for (const b of [...page.boxes, ...images]) {
    if (b.x < 0 || b.y < 0 || b.x + b.w > SCREEN_W || b.y + b.h > SCREEN_H) return `box ${b.name} is off-screen`;
  }
  for (const i of images) {
    if (i.w < 20 || i.w > 288 || i.h < 20 || i.h > 144) return `image ${i.name} must be 20..288 x 20..144`;
  }
  return null;
}
