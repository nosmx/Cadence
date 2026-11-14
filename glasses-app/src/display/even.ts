import {
  CreateStartUpPageContainer,
  RebuildPageContainer,
  StartUpPageCreateResult,
  TextContainerProperty,
  TextContainerUpgrade,
  type EvenAppBridge,
} from '@evenrealities/even_hub_sdk';
import { validatePage, type Display, type Page } from './types';

/**
 * Renders pages on the G2 through the Even Hub SDK.
 *
 * - First page uses createStartUpPageContainer, later ones rebuildPageContainer.
 * - Text updates go through textContainerUpgrade (the fast path), are skipped when
 *   unchanged, and are coalesced per box: while one update is in flight, only the
 *   newest pending text is kept, so a burst of messages never queues up over BLE.
 */
export class EvenDisplay implements Display {
  private started = false;
  private ids = new Map<string, number>();
  private shown = new Map<string, string>();
  private pending = new Map<string, string>();
  private inFlight = new Set<string>();
  private pageChange: Promise<void> = Promise.resolve();

  constructor(private bridge: EvenAppBridge) {}

  show(page: Page): Promise<void> {
    const err = validatePage(page);
    if (err) console.error(`[EvenDisplay] invalid page "${page.layout}": ${err}`);

    this.ids.clear();
    this.shown.clear();
    this.pending.clear();
    page.boxes.forEach((b, i) => {
      this.ids.set(b.name, i + 1);
      this.shown.set(b.name, b.content);
    });

    const textObject = page.boxes.map((b, i) => new TextContainerProperty({
      containerID: i + 1,
      containerName: b.name,
      xPosition: b.x,
      yPosition: b.y,
      width: b.w,
      height: b.h,
      content: b.content,
      borderWidth: b.border ?? 0,
      borderColor: b.border ? 15 : 0,
      borderRadius: b.border ? 6 : 0,
      paddingLength: 6,
      textColor: b.color ?? 4,
      isEventCapture: b.capture ? 1 : 0,
    }));

    const container = { containerTotalNum: textObject.length, textObject };
    this.pageChange = this.pageChange.then(async () => {
      if (!this.started) {
        const res = await this.bridge.createStartUpPageContainer(new CreateStartUpPageContainer(container));
        if (res !== StartUpPageCreateResult.success) {
          console.error('[EvenDisplay] createStartUpPageContainer failed:', res);
          return;
        }
        this.started = true;
      } else {
        const ok = await this.bridge.rebuildPageContainer(new RebuildPageContainer(container));
        if (!ok) console.error('[EvenDisplay] rebuildPageContainer failed');
      }
    });
    return this.pageChange;
  }

  async update(name: string, content: string): Promise<void> {
    if (!this.ids.has(name)) return;
    if (this.inFlight.has(name)) {
      this.pending.set(name, content);
      return;
    }
    if (this.shown.get(name) === content) return;
    await this.send(name, content);
  }

  private async send(name: string, content: string): Promise<void> {
    this.inFlight.add(name);
    try {
      await this.pageChange;
      const id = this.ids.get(name);
      if (id === undefined) return;
      const ok = await this.bridge.textContainerUpgrade(
        new TextContainerUpgrade({ containerID: id, containerName: name, content }),
      );
      if (ok) this.shown.set(name, content);
    } finally {
      this.inFlight.delete(name);
    }
    const next = this.pending.get(name);
    this.pending.delete(name);
    if (next !== undefined && next !== this.shown.get(name)) await this.send(name, next);
  }
}
