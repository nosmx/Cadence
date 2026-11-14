import { waitForEvenAppBridge, type EvenAppBridge } from '@evenrealities/even_hub_sdk';
import { CoachApp, type Input } from './app';
import { BrowserDisplay, TeeDisplay } from './display/browser';
import { EvenDisplay } from './display/even';
import type { Display } from './display/types';
import { keyToInput, toInput } from './input';
import { mountPanel } from './panel';
import { MockSource } from './sources/mock';
import type { MessageSource } from './sources/types';
import { WebSocketSource } from './sources/websocket';

/**
 * URL options:
 *   ?ws=ws://192.168.4.1:81   use the real Arduino WebSocket server instead of the mock
 *   ?preview=1                skip the Even bridge (browser preview only)
 */
const params = new URLSearchParams(location.search);

/**
 * Resolve the Even bridge if we're inside the Even app or simulator; otherwise null.
 * waitForEvenAppBridge() also resolves in a plain browser (calls then just fail), so
 * we look for the host's WebView handler instead. ?even=1 forces the bridge on.
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

  const preview = new BrowserDisplay(document.getElementById('preview')!);
  const bridge = await detectBridge();
  const display: Display = bridge ? new TeeDisplay([new EvenDisplay(bridge), preview]) : preview;
  document.getElementById('mode')!.textContent = bridge
    ? 'Even bridge connected - glasses + mirror'
    : 'Browser preview (no Even bridge) - keys: Enter tap, D double tap, arrows swipe, R say "ready"';

  const app = new CoachApp(display, source);

  // Collapse duplicate deliveries of the same gesture.
  let last: { input: Input; at: number } | undefined;
  const dispatch = (input: Input) => {
    const now = Date.now();
    if (last && last.input === input && now - last.at < 120) return;
    last = { input, at: now };
    app.handleInput(input);
  };

  bridge?.onEvenHubEvent((ev) => {
    const input = toInput(ev);
    if (input) dispatch(input);
  });
  window.addEventListener('keydown', (e) => {
    if (e.target instanceof HTMLInputElement || e.target instanceof HTMLSelectElement) return;
    if (e.key === 'r') return app.voice('ready');
    const input = keyToInput(e.key);
    if (input) {
      e.preventDefault();
      dispatch(input);
    }
  });

  mountPanel(app, source, mock);
  app.start();
  source.start();
}

void main();
