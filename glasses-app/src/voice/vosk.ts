/**
 * Offline speech recognition with Vosk (WASM, runs in a Web Worker on the phone).
 * The recognizer is limited to a handful of command words (see GRAMMAR), which
 * makes it fast and robust to noise compared with open dictation.
 *
 * The model (~40 MB) is not in git: run `npm run fetch-model` to put it in
 * public/models/. UNVERIFIED on real hardware: WASM + worker performance inside
 * the Even app WebView, and recognition quality with the glasses mic during CPR.
 */
import type { KaldiRecognizer, Model } from 'vosk-browser';
import { Emitter } from '../sources/types';
import { GRAMMAR, parseCommand, type Command, type VoiceStatus } from './commands';

export const MODEL_PATH = 'models/vosk-model-small-en-us-0.15.tar.gz';

/** Minimum per-word confidence (0..1) to accept a command. */
const MIN_WORD_CONF = 0.5;
/** Ignore the same command repeated within this window. */
const REPEAT_MS = 1200;
const LOAD_TIMEOUT_MS = 60000;

function withTimeout<T>(p: Promise<T>, ms: number, message: string): Promise<T> {
  return Promise.race([p, new Promise<T>((_, reject) => setTimeout(() => reject(new Error(message)), ms))]);
}

export class VoskVoice {
  status: VoiceStatus = 'off';
  error = '';
  readonly statusChanged = new Emitter<VoiceStatus>();
  readonly heard = new Emitter<{ command: Command; text: string }>();

  private model?: Model;
  private recognizer?: KaldiRecognizer;
  private last?: { command: Command; at: number };

  async load(sampleRate: number): Promise<void> {
    this.setStatus('loading');
    try {
      const url = new URL(MODEL_PATH, location.href).href;
      // Dev servers answer missing files with index.html, so check the type too.
      const head = await fetch(url, { method: 'HEAD' });
      if (!head.ok || (head.headers.get('content-type') ?? '').includes('text/html')) {
        throw new Error(`model not found at public/${MODEL_PATH} - run "npm run fetch-model"`);
      }
      // Loaded on demand: the library embeds ~5 MB of WASM.
      const { createModel } = await import('vosk-browser');
      this.model = await withTimeout(createModel(url), LOAD_TIMEOUT_MS, 'speech model took too long to load');
      const rec = new this.model.KaldiRecognizer(sampleRate, JSON.stringify(GRAMMAR));
      rec.setWords(true);
      rec.on('result', (msg) => {
        if (msg.event !== 'result') return;
        const words = msg.result.result ?? [];
        const confident = words.filter((w) => w.conf >= MIN_WORD_CONF).map((w) => w.word).join(' ');
        this.handleText(words.length ? confident : msg.result.text);
      });
      rec.on('error', (msg) => {
        if (msg.event === 'error') console.error('[voice]', msg.error);
      });
      this.recognizer = rec;
      this.setStatus('listening');
    } catch (e) {
      this.error = e instanceof Error ? e.message : String(e);
      console.error('[voice] failed to load:', this.error);
      this.setStatus('error');
    }
  }

  /** 16-bit little-endian mono PCM, e.g. from the G2 glasses mic (16 kHz). */
  feedPcm16(bytes: Uint8Array, sampleRate = 16000): void {
    if (!this.recognizer) return;
    const n = bytes.length >> 1;
    const view = new DataView(bytes.buffer, bytes.byteOffset, n * 2);
    const out = new Float32Array(n);
    for (let i = 0; i < n; i++) out[i] = view.getInt16(i * 2, true) / 32768;
    this.recognizer.acceptWaveformFloat(out, sampleRate);
  }

  /** Float samples in -1..1, e.g. from the computer mic in the browser preview. */
  feedFloat(samples: Float32Array, sampleRate: number): void {
    this.recognizer?.acceptWaveformFloat(samples, sampleRate);
  }

  private handleText(text: string): void {
    const command = parseCommand(text);
    if (!command) return;
    const now = Date.now();
    if (this.last && this.last.command === command && now - this.last.at < REPEAT_MS) return;
    this.last = { command, at: now };
    this.heard.emit({ command, text });
  }

  private setStatus(s: VoiceStatus): void {
    this.status = s;
    this.statusChanged.emit(s);
  }
}

/** Browser preview only: stream the computer's microphone into the recognizer. */
export async function startBrowserMic(voice: VoskVoice): Promise<void> {
  const stream = await navigator.mediaDevices.getUserMedia({ audio: { channelCount: 1, echoCancellation: true } });
  // 16 kHz to match the recognizer (same rate as the glasses mic).
  const ctx = new AudioContext({ sampleRate: 16000 });
  const src = ctx.createMediaStreamSource(stream);
  // ScriptProcessor is deprecated but universally supported and fine for a preview.
  const proc = ctx.createScriptProcessor(4096, 1, 1);
  proc.onaudioprocess = (e) => voice.feedFloat(new Float32Array(e.inputBuffer.getChannelData(0)), ctx.sampleRate);
  src.connect(proc);
  proc.connect(ctx.destination);
}
