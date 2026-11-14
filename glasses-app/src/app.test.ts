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
  beat: string[] = [];
  figure: string[] = [];
  async setImage(name: string, frame: string) {
    if (name === 'beat') this.beat.push(frame);
    if (name === 'figure') this.figure.push(frame);
  }
  async update(name: string, content: string, _color?: number) {
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

  it('voice-only: splash -> setup -> align (auto-lock) -> ready -> compress -> summary', () => {
    const display = new FakeDisplay();
    const source = new FakeSource();
    const app = new CoachApp(display, source, () => Date.now());
    app.start();
    expect(app.phase).toBe('splash');

    app.setVoiceStatus('listening');
    expect(display.text.get('footer')).toBe('Say "READY" to begin');
    app.command('ready');
    expect(app.phase).toBe('setup');
    app.command('ready');
    app.command('back');
    app.command('ready');
    app.command('ready');
    app.command('ready');
    expect(app.phase).toBe('align');

    // Off target: shows direction.
    source.msgs.emit({ type: 'placement', ts: Date.now(), source: 'mock', on_target: false, distance_cm: 4, direction: 'head', signal: 0.9 });
    expect(display.text.get('cue')).toBe('MOVE TOWARD HEAD');

    // "READY" can't skip alignment while the Arduino says the hands are off target.
    app.command('ready');
    expect(app.phase).toBe('align');

    // On target held for the lock time -> ready.
    for (let t = 0; t <= 1600; t += 200) {
      source.msgs.emit({ type: 'placement', ts: Date.now(), source: 'mock', on_target: true, distance_cm: 0, direction: null, signal: 0.9 });
      vi.advanceTimersByTime(200);
    }
    expect(app.phase).toBe('ready');

    // "STOP" means nothing here; "READY" starts compressions.
    app.command('stop');
    expect(app.phase).toBe('ready');
    app.command('ready');
    expect(app.phase).toBe('compress');
    expect(source.sent.some((m) => m.type === 'confirm' && m.what === 'start_compressions')).toBe(true);

    source.msgs.emit({ type: 'compression', ts: Date.now(), source: 'mock', rate_cpm: 90, depth_cm: 4.2, pressure: 0.6, quality: 'slow', confidence: 0.9 });
    expect(display.text.get('cue')).toBe('FASTER - match the circle');
    expect(display.text.get('count')).toContain('COUNT 1');
    expect(display.pages[display.pages.length - 1].images!.map((i) => i.name)).toEqual(['beat', 'figure']);

    // Bracelet goes silent -> warning, no stale numbers.
    vi.advanceTimersByTime(2000);
    expect(display.text.get('cue')).toMatch(/^NO BRACELET DATA/);
    expect(display.text.get('nums')).toContain('--');

    app.command('stop');
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
    // Voice is off here, so the screen offers the tap fallback.
    expect(display.text.get('footer')).toBe('VOICE OFF - tap to continue anyway');
    app.handleInput('tap');
    expect(app.phase).toBe('ready');
  });

  it('flashes the circle, moves the figure and beeps on the same 110 bpm beat', () => {
    const display = new FakeDisplay();
    const source = new FakeSource();
    const app = new CoachApp(display, source, () => Date.now());
    const metronome = { starts: [] as [number, number][], stops: 0 };
    app.setMetronome({ start: (t, bpm) => metronome.starts.push([t, bpm]), stop: () => metronome.stops++ });
    app.start();
    app.setVoiceStatus('listening');
    app.command('ready');
    for (let i = 0; i < 3; i++) app.command('ready');
    app.command('ready'); // no tracking -> continue
    app.command('ready'); // start
    expect(app.phase).toBe('compress');
    // The phone beeper is started at 110 bpm on the same clock as the circle.
    expect(metronome.starts).toHaveLength(1);
    expect(metronome.starts[0][1]).toBe(110);

    display.beat.length = 0;
    display.figure.length = 0;
    vi.advanceTimersByTime(60000);
    const on = display.beat.filter((f) => f === 'beat-on').length;
    const off = display.beat.filter((f) => f === 'beat-off').length;
    expect(on).toBeGreaterThanOrEqual(109);
    expect(on).toBeLessThanOrEqual(111);
    expect(Math.abs(on - off)).toBeLessThanOrEqual(1);
    // The figure moves on exactly the same beats as the circle.
    expect(display.figure.filter((f) => f === 'cpr-down').length).toBe(on);
    expect(display.figure.filter((f) => f === 'cpr-up').length).toBe(off);

    app.command('stop');
    expect(metronome.stops).toBeGreaterThan(0);
  });
});
