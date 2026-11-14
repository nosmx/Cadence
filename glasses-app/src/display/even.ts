import {
  CreateStartUpPageContainer,
  ImageContainerProperty,
  ImageRawDataUpdate,
  ImageRawDataUpdateResult,
  RebuildPageContainer,
  StartUpPageCreateResult,
  TextContainerProperty,
  TextContainerUpgrade,
  type EvenAppBridge,
} from '@evenrealities/even_hub_sdk';
import type { FrameStore } from './frames';
import { validatePage, type Display, type Page } from './types';

/**
 * Renders pages on the G2 through the Even Hub SDK.
 *
 * - First page uses createStartUpPageContainer, later ones rebuildPageContainer.
 * - Text updates go through textContainerUpgrade (the fast path), are skipped when
 *   unchanged, and are coalesced per box: while one update is in flight, only the
 *   newest pending text is kept, so a burst of messages never queues up over BLE.
 * - Image boxes get PNG frames via updateImageRawData, one image send at a time,
 *   also coalesced (a slow link drops intermediate frames instead of lagging).
 */
export class EvenDisplay implements Display {
  private started = false;
  private ids = new Map<string, number>();
  /** What is on the glasses now, per box: text + brightness. */
  private shown = new Map<string, Shown>();
  private pending = new Map<string, Shown>();
  private inFlight = new Set<string>();
  private pageChange: Promise<void> = Promise.resolve();

  private imageIds = new Map<string, number>();
  private imageShown = new Map<string, string | undefined>();
  private imageWanted = new Map<string, string>();
  private imageBusy = false;

  constructor(
    private bridge: EvenAppBridge,
    private frames: FrameStore,
  ) {}

  show(page: Page): Promise<void> {
    const err = validatePage(page);
    if (err) console.error(`[EvenDisplay] invalid page "${page.layout}": ${err}`);

    this.ids.clear();
    this.shown.clear();
    this.pending.clear();
    page.boxes.forEach((b, i) => {
      this.ids.set(b.name, i + 1);
      this.shown.set(b.name, { content: b.content, color: b.color ?? 4 });
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

    const images = page.images ?? [];
    this.imageIds.clear();
    this.imageShown.clear();
    this.imageWanted.clear();
    const imageObject = images.map((im, i) => {
      const id = page.boxes.length + i + 1;
      this.imageIds.set(im.name, id);
      this.imageShown.set(im.name, undefined); // blank until the first updateImageRawData
      this.imageWanted.set(im.name, im.frame);
      return new ImageContainerProperty({
        containerID: id,
        containerName: im.name,
        xPosition: im.x,
        yPosition: im.y,
        width: im.w,
        height: im.h,
      });
    });

    const container = {
      containerTotalNum: textObject.length + imageObject.length,
      textObject,
      ...(imageObject.length ? { imageObject } : {}),
    };
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
    void this.pageChange.then(() => this.pumpImages());
    return this.pageChange;
  }

  async setImage(name: string, frame: string): Promise<void> {
    if (!this.imageIds.has(name)) return;
    this.imageWanted.set(name, frame);
    await this.pumpImages();
  }

  /** Send whichever image is out of date, one at a time, always the newest wanted frame. */
  private async pumpImages(): Promise<void> {
    if (this.imageBusy) return;
    this.imageBusy = true;
    try {
      await this.pageChange;
      for (;;) {
        const stale = [...this.imageWanted].find(([n, f]) => this.imageShown.get(n) !== f);
        if (!stale) break;
        const [name, frame] = stale;
        const id = this.imageIds.get(name);
        const data = this.frames.get(frame);
        if (id === undefined || !data) {
          this.imageWanted.delete(name);
          continue;
        }
        const res = await this.bridge.updateImageRawData(
          new ImageRawDataUpdate({ containerID: id, containerName: name, imageData: data.png }),
        );
        if (res !== ImageRawDataUpdateResult.success) {
          console.error('[EvenDisplay] updateImageRawData failed:', res);
          break;
        }
        this.imageShown.set(name, frame);
      }
    } finally {
      this.imageBusy = false;
    }
  }

  async update(name: string, content: string, color?: number): Promise<void> {
    const cur = this.shown.get(name);
    if (!cur) return;
    const want: Shown = { content, color: color ?? cur.color };
    if (this.inFlight.has(name)) {
      this.pending.set(name, want);
      return;
    }
    if (same(cur, want)) return;
    await this.send(name, want);
  }

  private async send(name: string, want: Shown): Promise<void> {
    this.inFlight.add(name);
    try {
      await this.pageChange;
      const id = this.ids.get(name);
      const cur = this.shown.get(name);
      if (id === undefined || !cur) return;
      const ok = await this.bridge.textContainerUpgrade(
        new TextContainerUpgrade({
          containerID: id,
          containerName: name,
          content: want.content,
          ...(want.color !== cur.color ? { textColor: want.color } : {}),
        }),
      );
      if (ok) this.shown.set(name, want);
    } finally {
      this.inFlight.delete(name);
    }
    const next = this.pending.get(name);
    this.pending.delete(name);
    const cur = this.shown.get(name);
    if (next && cur && !same(next, cur)) await this.send(name, next);
  }

  /**
   * Waits for pending page changes; true once the first page exists
   * (the glasses mic can only be turned on after that).
   */
  async whenStarted(): Promise<boolean> {
    await this.pageChange;
    return this.started;
  }
}

interface Shown {
  content: string;
  color: number;
}

const same = (a: Shown, b: Shown) => a.content === b.content && a.color === b.color;
