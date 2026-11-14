/**
 * Phone beep on every compression beat (the glasses have no speaker).
 *
 * Beeps are scheduled ahead on the Web Audio clock, so they land exactly on the
 * beat even if the JS thread is busy. Beat k is at startedAt + k * (60000 / bpm),
 * the same clock the pace circle on the glasses uses.
 *
 * Browsers (and possibly the Even app WebView) only allow sound after a user
 * gesture, so `unlock()` is called on the first tap/click on the phone screen.
 * UNVERIFIED on hardware: audio playback inside the Even app WebView.
 */

export interface Metronome {
  start(startedAtMs: number, bpm: number): void;
  stop(): void;
}

const LOOKAHEAD_MS = 150;
const TICK_MS = 25;
const BEEP_HZ = 1000;
const BEEP_S = 0.06;

export class PhoneBeeper implements Metronome {
  enabled = true;
  private ctx?: AudioContext;
  private timer?: ReturnType<typeof setInterval>;
  private nextBeat = 0;
  private startedAt = 0;
  private beatMs = 0;
  /** Date.now()/1000 minus AudioContext time, measured once so beep spacing is exact. */
  private clockOffset?: number;

  /** Create/resume the audio context. Call from a user gesture. */
  async unlock(): Promise<void> {
    try {
      this.ctx ??= new AudioContext();
      if (this.ctx.state !== 'running') await this.ctx.resume();
    } catch (e) {
      console.warn('[beep] audio unavailable:', e);
    }
  }

  /** 'running' when sound can play; otherwise needs a tap on the phone screen. */
  get state(): 'running' | 'locked' | 'unavailable' {
    if (typeof AudioContext === 'undefined') return 'unavailable';
    return this.ctx?.state === 'running' ? 'running' : 'locked';
  }

  start(startedAtMs: number, bpm: number): void {
    this.stop();
    this.startedAt = startedAtMs;
    this.beatMs = 60000 / bpm;
    this.nextBeat = Math.max(0, Math.ceil((Date.now() - startedAtMs) / this.beatMs));
    this.clockOffset = undefined;
    void this.unlock();
    this.timer = setInterval(() => this.schedule(), TICK_MS);
    this.schedule();
  }

  stop(): void {
    clearInterval(this.timer);
    this.timer = undefined;
  }

  /** Short test beep (panel button). */
  test(): void {
    void this.unlock().then(() => this.ctx && this.beepAt(this.ctx.currentTime + 0.02));
  }

  private schedule(): void {
    const ctx = this.ctx;
    if (!ctx || ctx.state !== 'running') return;
    const now = Date.now();
    this.clockOffset ??= now / 1000 - ctx.currentTime;
    for (;;) {
      const beatAt = this.startedAt + this.nextBeat * this.beatMs;
      if (beatAt > now + LOOKAHEAD_MS) break;
      // Skip beats already in the past (e.g. after the audio was unlocked late).
      if (beatAt >= now - 10 && this.enabled) this.beepAt(Math.max(ctx.currentTime, beatAt / 1000 - this.clockOffset));
      this.nextBeat++;
    }
  }

  private beepAt(t: number): void {
    const ctx = this.ctx!;
    const osc = ctx.createOscillator();
    const gain = ctx.createGain();
    osc.frequency.value = BEEP_HZ;
    gain.gain.setValueAtTime(0.0001, t);
    gain.gain.exponentialRampToValueAtTime(0.6, t + 0.005);
    gain.gain.exponentialRampToValueAtTime(0.0001, t + BEEP_S);
    osc.connect(gain).connect(ctx.destination);
    osc.start(t);
    osc.stop(t + BEEP_S + 0.01);
  }
}
