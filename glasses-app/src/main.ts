import { AudioInputSource, waitForEvenAppBridge, type EvenAppBridge } from '@evenrealities/even_hub_sdk';
import { CoachApp, type Input } from './app';
import { PhoneBeeper } from './beeper';
import { BrowserDisplay, TeeDisplay } from './display/browser';
import { EvenDisplay } from './display/even';
import { buildFrames } from './display/frames';
import type { Display } from './display/types';
import { keyToInput, toInput } from './input';
import { mountPanel } from './panel';
import { MockSource } from './sources/mock';
import type { MessageSource } from './sources/types';
import { WebSocketSource } from './sources/websocket';
import { startBrowserMic, VoskVoice } from './voice/vosk';

/**
 * URL options:
 *   ?ws=ws://192.168.4.1:81   use the real Arduino WebSocket server instead of the mock
 *   ?preview=1                skip the Even bridge (browser preview only)
 *   ?even=1                   force the Even bridge on
 *   ?novoice=1                don't load speech recognition
 */
const params = new URLSearchParams(location.search);

/**
 * Resolve the Even bridge if we're inside the Even app or simulator; otherwise null.
 * waitForEvenAppBridge() also resolves in a plain browser (calls then just fail), so
 * we look for the host's WebView handler instead.
 */
async function detectBridge(): Promise<EvenAppBridge | null> {
  if (params.has('preview')) return null;
  const hasHost = () => typeof (window as { flutter_inappwebview?: unknown }).flutter_inappwebview !== 'undefined';
  for (let waited = 0; !hasHost() && !params.has('even') && waited < 2000; waited += 100) {
    await new Promise((r) => setTimeout(r, 100));
  }
  if (!hasHost() && !params.has('even')) return null;
  return waitForEvenAppBridge();
}

async function main(): Promise<void> {
  const wsUrl = params.get('ws');
  const mock = wsUrl ? null : new MockSource();
  const source: MessageSource = mock ?? new WebSocketSource(wsUrl!);

  const frames = await buildFrames();
  const preview = new BrowserDisplay(document.getElementById('preview')!, frames);
  const bridge = await detectBridge();
  const glasses = bridge ? new EvenDisplay(bridge, frames) : null;
  const display: Display = glasses ? new TeeDisplay([glasses, preview]) : preview;
  document.getElementById('mode')!.textContent = bridge
    ? 'Even bridge connected - glasses + mirror'
    : 'Browser preview - keys: R "ready", B "back", S "stop" (Enter/D/arrows = touchpad)';

  const app = new CoachApp(display, source);

  // Phone beep on each beat. Sound needs a user gesture first, so unlock on the first tap.
  const beeper = new PhoneBeeper();
  app.setMetronome(beeper);
  const unlockAudio = () => void beeper.unlock();
  window.addEventListener('pointerdown', unlockAudio);
  window.addEventListener('keydown', unlockAudio);

  // --- Voice ---------------------------------------------------------------
  const voice = new VoskVoice();
  // In a plain browser the computer mic needs a click to start, so don't claim
  // "listening" until it's on. In the Even app the glasses mic is used.
  let micOn = !!bridge;
  const syncVoice = () => app.setVoiceStatus(voice.status === 'listening' && !micOn ? 'off' : voice.status);
  voice.statusChanged.on(syncVoice);
  const enableMic = bridge
    ? null
    : async () => {
        await startBrowserMic(voice);
        micOn = true;
        syncVoice();
      };
  voice.heard.on(({ command, text }) => app.command(command, text));

  // --- Touchpad / keyboard fallback -----------------------------------------
  let last: { input: Input; at: number } | undefined;
  const dispatch = (input: Input) => {
    const now = Date.now();
    if (last && last.input === input && now - last.at < 120) return; // collapse duplicate deliveries
    last = { input, at: now };
    app.handleInput(input);
  };

  bridge?.onEvenHubEvent((ev) => {
    if (ev.audioEvent) {
      voice.feedPcm16(ev.audioEvent.audioPcm);
      return;
    }
    const input = toInput(ev);
    if (input) dispatch(input);
  });
  window.addEventListener('keydown', (e) => {
    if (e.target instanceof HTMLInputElement || e.target instanceof HTMLSelectElement) return;
    const spoken = { r: 'ready', b: 'back', s: 'stop' } as const;
    if (e.key in spoken) return app.command(spoken[e.key as keyof typeof spoken]);
    const input = keyToInput(e.key);
    if (input) {
      e.preventDefault();
      dispatch(input);
    }
  });

  mountPanel(app, source, mock, voice, enableMic, beeper);
  app.start();
  source.start();

  if (!params.has('novoice')) {
    await voice.load(16000);
    // The glasses mic can only be opened once a page exists on the glasses.
    if (bridge && glasses && voice.status === 'listening' && (await glasses.whenStarted())) {
      const ok = await bridge.audioControl(true, AudioInputSource.Glasses);
      if (!ok) {
        console.error('[voice] could not open the glasses mic');
        app.setVoiceStatus('error');
      }
    }
  }
}

void main();
