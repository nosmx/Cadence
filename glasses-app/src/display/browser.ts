import type { FrameStore } from './frames';
import { SCREEN_H, SCREEN_W, validatePage, type Display, type Page } from './types';

/**
 * Approximate in-browser preview of the G2 display (576x288, green, 5 brightness levels).
 * Fonts and wrapping differ from the glasses - use the official simulator or hardware
 * for real layout checks. This exists so the mock can be viewed in any browser and
 * mirrored on the phone screen.
 */
export class BrowserDisplay implements Display {
  private boxes = new Map<string, HTMLDivElement>();
  private images = new Map<string, HTMLImageElement>();
  private screen: HTMLDivElement;
  private errorEl: HTMLDivElement;

  constructor(
    host: HTMLElement,
    private frames: FrameStore,
  ) {
    this.screen = document.createElement('div');
    this.screen.className = 'g2-screen';
    this.screen.style.width = `${SCREEN_W}px`;
    this.screen.style.height = `${SCREEN_H}px`;
    this.errorEl = document.createElement('div');
    this.errorEl.className = 'g2-error';
    host.append(this.screen, this.errorEl);
    this.calibrateFont();
  }

  /**
   * Scale the preview font so text is as wide as on the glasses. The sample's
   * width in the G2 firmware font (915 px) was measured with @evenrealities/pretext.
   * Line height is the G2's fixed 27 px (set in index.html).
   */
  private calibrateFont(): void {
    const SAMPLE = 'The quick brown fox jumps over the lazy dog. PACK MY BOX WITH FIVE DOZEN LIQUOR JUGS 0123456789';
    const G2_WIDTH = 915;
    const ctx = document.createElement('canvas').getContext('2d');
    if (!ctx) return;
    const family = getComputedStyle(this.screen).fontFamily;
    ctx.font = `20px ${family}`;
    const measured = ctx.measureText(SAMPLE).width;
    if (measured > 0) this.screen.style.fontSize = `${((20 * G2_WIDTH) / measured).toFixed(2)}px`;
  }

  async show(page: Page): Promise<void> {
    const err = validatePage(page);
    this.errorEl.textContent = err ? `Layout "${page.layout}": ${err}` : '';
    this.screen.replaceChildren();
    this.boxes.clear();
    this.images.clear();
    for (const im of page.images ?? []) {
      const el = document.createElement('img');
      el.className = 'g2-image';
      el.alt = '';
      Object.assign(el.style, { left: `${im.x}px`, top: `${im.y}px`, width: `${im.w}px`, height: `${im.h}px` });
      const f = this.frames.get(im.frame);
      if (f) el.src = f.previewUrl;
      el.dataset.frame = im.frame;
      this.screen.append(el);
      this.images.set(im.name, el);
    }
    for (const b of page.boxes) {
      const el = document.createElement('div');
      el.className = 'g2-box';
      Object.assign(el.style, {
        left: `${b.x}px`,
        top: `${b.y}px`,
        width: `${b.w}px`,
        height: `${b.h}px`,
        borderWidth: `${b.border ?? 0}px`,
        opacity: String(0.2 + 0.2 * (b.color ?? 4)),
      });
      el.textContent = b.content;
      this.screen.append(el);
      this.boxes.set(b.name, el);
    }
  }

  async update(name: string, content: string, color?: number): Promise<void> {
    const el = this.boxes.get(name);
    if (!el) return;
    if (el.textContent !== content) el.textContent = content;
    if (color !== undefined) el.style.opacity = String(0.2 + 0.2 * color);
  }

  async setImage(name: string, frame: string): Promise<void> {
    const el = this.images.get(name);
    const f = this.frames.get(frame);
    if (!el || !f || el.dataset.frame === frame) return;
    el.src = f.previewUrl;
    el.dataset.frame = frame;
  }
}

/** Sends every call to several displays (glasses + phone-screen mirror). */
export class TeeDisplay implements Display {
  constructor(private targets: Display[]) {}
  async show(page: Page): Promise<void> {
    await Promise.all(this.targets.map((t) => t.show(page)));
  }
  async update(name: string, content: string, color?: number): Promise<void> {
    await Promise.all(this.targets.map((t) => t.update(name, content, color)));
  }
  async setImage(name: string, frame: string): Promise<void> {
    await Promise.all(this.targets.map((t) => t.setImage(name, frame)));
  }
}
