import { SCREEN_H, SCREEN_W, validatePage, type Display, type Page } from './types';

/**
 * Approximate in-browser preview of the G2 display (576x288, green, 5 brightness levels).
 * Fonts and wrapping differ from the glasses - use the official simulator or hardware
 * for real layout checks. This exists so the mock can be viewed in any browser and
 * mirrored on the phone screen.
 */
export class BrowserDisplay implements Display {
  private boxes = new Map<string, HTMLDivElement>();
  private screen: HTMLDivElement;
  private errorEl: HTMLDivElement;

  constructor(host: HTMLElement) {
    this.screen = document.createElement('div');
    this.screen.className = 'g2-screen';
    this.screen.style.width = `${SCREEN_W}px`;
    this.screen.style.height = `${SCREEN_H}px`;
    this.errorEl = document.createElement('div');
    this.errorEl.className = 'g2-error';
    host.append(this.screen, this.errorEl);
  }

  async show(page: Page): Promise<void> {
    const err = validatePage(page);
    this.errorEl.textContent = err ? `Layout "${page.layout}": ${err}` : '';
    this.screen.replaceChildren();
    this.boxes.clear();
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

  async update(name: string, content: string): Promise<void> {
    const el = this.boxes.get(name);
    if (el && el.textContent !== content) el.textContent = content;
  }
}

/** Sends every call to several displays (glasses + phone-screen mirror). */
export class TeeDisplay implements Display {
  constructor(private targets: Display[]) {}
  async show(page: Page): Promise<void> {
    await Promise.all(this.targets.map((t) => t.show(page)));
  }
  async update(name: string, content: string): Promise<void> {
    await Promise.all(this.targets.map((t) => t.update(name, content)));
  }
}
