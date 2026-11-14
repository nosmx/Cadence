/**
 * Minimal display model that maps 1:1 onto G2 text containers.
 *
 * G2 limits (SDK 0.0.16): <= 12 containers per page, <= 8 text containers,
 * <= 4 image containers (max 288x144), exactly one container with event capture.
 * Text has no font-size or alignment control - emphasis comes from layout and borders.
 */

export const SCREEN_W = 576;
export const SCREEN_H = 288;
export const MAX_TEXT_BOXES = 8;

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

export interface Page {
  /** Same layout key => only text changes; different key => page rebuild. */
  layout: string;
  boxes: TextBox[];
}

export interface Display {
  /** Replace the whole page (slow: rebuilds containers). */
  show(page: Page): Promise<void>;
  /**
   * Change one box's text and optionally its brightness (fast path).
   * Implementations skip updates that change nothing.
   */
  update(name: string, content: string, color?: number): Promise<void>;
}

export function validatePage(page: Page): string | null {
  if (page.boxes.length > MAX_TEXT_BOXES) return `too many text boxes (${page.boxes.length} > ${MAX_TEXT_BOXES})`;
  const captures = page.boxes.filter((b) => b.capture).length;
  if (captures !== 1) return `expected exactly 1 capture box, got ${captures}`;
  for (const b of page.boxes) {
    if (b.x < 0 || b.y < 0 || b.x + b.w > SCREEN_W || b.y + b.h > SCREEN_H) return `box ${b.name} is off-screen`;
  }
  return null;
}
