import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { CoachApp } from './app';
import type { Display, Page } from './display/types';
import { validatePage } from './display/types';
import type { InboundMsg, OutboundMsg } from './protocol';
import { Emitter, type MessageSource, type SourceStatus } from './sources/types';

class FakeDisplay implements Display {
  pages: Page[] = [];
  text = new Map<string, string>();
  async show(page: Page) {
    expect(validatePage(page)).toBeNull();
    this.pages.push(page);
    this.text = new Map(page.boxes.map((b) => [b.name, b.content]));
  }
  async update(name: string, content: string) {
    this.text.set(name, content);
  }
}

class FakeSource implements MessageSource {
  name = 'fake';
  status: SourceStatus = 'connected';
  sent: OutboundMsg[] = [];
  msgs = new Emitter<InboundMsg>();
  onMessage(cb: (m: InboundMsg) => void) { this.msgs.on(cb); }
  onStatus() {}
  send(m: OutboundMsg) { this.sent.push(m); }
  start() {}
}

describe('CoachApp flow', () => {
  beforeEach(() => vi.useFakeTimers());
  afterEach(() => vi.useRealTimers());

  it('splash -> setup -> align (auto-lock) -> ready -> voice "ready" -> compress -> summary', () => {
    const display = new FakeDisplay();
    const source = new FakeSource();
    const app = new CoachApp(display, source, () => Date.now());
    app.start();
    expect(app.phase).toBe('splash');

    app.handleInput('tap');
    expect(app.phase).toBe('setup');
    app.handleInput('tap');
    app.handleInput('tap');
    app.handleInput('tap');
    expect(app.phase).toBe('align');

    // Off target: shows direction.
    source.msgs.emit({ type: 'placement', ts: Date.now(), source: 'mock', on_target: false, distance_cm: 4, direction: 'head', signal: 0.9 });
    expect(display.text.get('cue')).toBe('MOVE TOWARD HEAD');

    // Tap is ignored while off target.
    app.handleInput('tap');
    expect(app.phase).toBe('align');

    // On target held for the lock time -> ready.
    for (let t = 0; t <= 1600; t += 200) {
      source.msgs.emit({ type: 'placement', ts: Date.now(), source: 'mock', on_target: true, distance_cm: 0, direction: null, signal: 0.9 });
      vi.advanceTimersByTime(200);
    }
    expect(app.phase).toBe('ready');

    // Voice phrase that isn't "ready" does nothing.
    app.voice('hello');
    expect(app.phase).toBe('ready');
    app.voice('Ready!');
    expect(app.phase).toBe('compress');
    expect(source.sent.some((m) => m.type === 'confirm' && m.what === 'start_compressions')).toBe(true);

    source.msgs.emit({ type: 'compression', ts: Date.now(), source: 'mock', rate_cpm: 90, depth_cm: 4.2, pressure: 0.6, quality: 'slow', confidence: 0.9 });
    expect(display.text.get('cue')).toBe('FASTER   -   PUSH HARDER');
    expect(display.text.get('count')).toContain('COUNT  1');

    // Bracelet goes silent -> warning, no stale numbers.
    vi.advanceTimersByTime(2000);
    expect(display.text.get('cue')).toBe('NO BRACELET DATA - KEEP PUSHING');
    expect(display.text.get('rate')).toContain('--');

    app.handleInput('double');
    expect(app.phase).toBe('summary');
    expect(display.text.get('body')).toContain('Compressions: 1');
  });

  it('lets the rescuer skip alignment when hand tracking is lost', () => {
    const display = new FakeDisplay();
    const source = new FakeSource();
    const app = new CoachApp(display, source, () => Date.now());
    app.start();
    app.handleInput('tap');
    for (let i = 0; i < 3; i++) app.handleInput('tap');
    expect(app.phase).toBe('align');
    expect(display.text.get('cue')).toBe('WAITING FOR HAND TRACKING');
    app.handleInput('tap');
    expect(app.phase).toBe('ready');
  });
});
