/**
 * Mock control panel, shown on the phone screen / simulator WebView / browser.
 * Lets you play the Arduino + bracelet and the rescuer's voice while the
 * real hardware isn't ready. Not part of the glasses UI.
 */
import type { CoachApp, Input } from './app';
import type { Command } from './voice/commands';
import type { OutboundMsg, PlacementMsg } from './protocol';
import type { MockSource } from './sources/mock';
import type { MessageSource } from './sources/types';
import type { VoskVoice } from './voice/vosk';
import type { PhoneBeeper } from './beeper';

const $ = <T extends HTMLElement>(id: string) => document.getElementById(id) as T;

export function mountPanel(
  app: CoachApp,
  source: MessageSource,
  mock: MockSource | null,
  voice: VoskVoice,
  enableMic: (() => Promise<void>) | null,
  beeper: PhoneBeeper,
  arduino: { current: string; save: (url: string) => Promise<void> },
): void {
  const phaseEl = $('phase');
  const sourceEl = $('source');
  const logEl = $('log');

  const showPhase = () => (phaseEl.textContent = app.phase);
  app.onPhaseChange(showPhase);
  showPhase();
  const showSource = () => (sourceEl.textContent = `${source.name} - ${source.status}`);
  source.onStatus(showSource);
  showSource();

  const log = (line: string) => {
    const row = document.createElement('div');
    row.textContent = `${new Date().toLocaleTimeString()}  ${line}`;
    logEl.prepend(row);
    while (logEl.childElementCount > 12) logEl.lastElementChild?.remove();
  };

  // Glasses input buttons (the simulator/glasses have their own; these help in a browser).
  document.querySelectorAll<HTMLButtonElement>('[data-input]').forEach((b) =>
    b.addEventListener('click', () => app.handleInput(b.dataset.input as Input)),
  );

  // Voice: simulated commands + real recognition status.
  document.querySelectorAll<HTMLButtonElement>('[data-say]').forEach((b) =>
    b.addEventListener('click', () => app.command(b.dataset.say as Command)),
  );
  const voiceEl = $('voice-status');
  const showVoice = () => {
    const s = app.voiceStatus;
    voiceEl.textContent =
      s === 'listening' ? 'listening - say READY / BACK / STOP'
      : s === 'loading' ? 'loading speech model...'
      : voice.status === 'error' ? `error: ${voice.error}`
      : voice.status === 'listening' ? 'model loaded - turn on the mic'
      : 'off';
  };
  voice.statusChanged.on(showVoice);
  app.onPhaseChange(showVoice);
  setInterval(showVoice, 500);
  showVoice();
  voice.heard.on(({ command, text }) => log(`heard "${text}" -> ${command}`));

  // Arduino (sensing program) address, remembered on the phone.
  const wsInput = $<HTMLInputElement>('ws-url');
  wsInput.value = arduino.current || 'ws://172.17.20.85:8765';
  $('ws-connect').addEventListener('click', () => {
    const url = wsInput.value.trim();
    if (!/^wss?:\/\/[^\s/]+/.test(url)) {
      log('Arduino address must look like ws://172.17.20.85:8765');
      return;
    }
    void arduino.save(url);
  });
  $('ws-mock').addEventListener('click', () => void arduino.save(''));

  // Phone beep on each beat.
  const beepOn = $<HTMLInputElement>('beep-on');
  const beepStatus = $('beep-status');
  beepOn.checked = beeper.enabled;
  beepOn.addEventListener('change', () => (beeper.enabled = beepOn.checked));
  $('beep-test').addEventListener('click', () => beeper.test());
  const showBeep = () => {
    const st = beeper.state;
    beepStatus.textContent = st === 'running' ? 'sound ready' : st === 'locked' ? 'tap anywhere here to allow sound' : 'no audio on this device';
  };
  setInterval(showBeep, 500);
  showBeep();

  const micBtn = $<HTMLButtonElement>('enable-mic');
  if (!enableMic) micBtn.hidden = true;
  else {
    micBtn.addEventListener('click', async () => {
      micBtn.disabled = true;
      try {
        await enableMic();
        micBtn.textContent = 'Computer mic on';
      } catch (e) {
        micBtn.disabled = false;
        log(`mic error: ${e instanceof Error ? e.message : e}`);
      }
    });
  }

  if (!mock) {
    $('mock-controls').hidden = true;
    return;
  }
  mock.sent.on((m: OutboundMsg) => log(`glasses -> ${m.type}${'what' in m ? `: ${m.what}` : `: "${m.phrase}"`}`));

  const s = mock.settings;

  // --- Arduino / placement ---
  const bindCheck = (id: string, get: () => boolean, set: (v: boolean) => void) => {
    const el = $<HTMLInputElement>(id);
    el.checked = get();
    el.addEventListener('change', () => set(el.checked));
  };
  bindCheck('arduino-online', () => s.arduinoOnline, (v) => (s.arduinoOnline = v));
  bindCheck('bracelet-online', () => s.braceletOnline, (v) => (s.braceletOnline = v));

  const modeEl = $<HTMLSelectElement>('placement-mode');
  const manualEl = $('manual-placement');
  modeEl.value = s.placementMode;
  const syncMode = () => {
    s.placementMode = modeEl.value as 'auto' | 'manual';
    manualEl.hidden = s.placementMode !== 'manual';
  };
  modeEl.addEventListener('change', syncMode);
  syncMode();
  $('displace').addEventListener('click', () => mock.displaceHands());

  document.querySelectorAll<HTMLButtonElement>('[data-dir]').forEach((b) =>
    b.addEventListener('click', () => {
      const dir = b.dataset.dir!;
      s.manual.on_target = dir === 'on';
      if (dir !== 'on') s.manual.direction = dir as PlacementMsg['direction'];
    }),
  );
  const distEl = $<HTMLInputElement>('manual-distance');
  distEl.addEventListener('input', () => (s.manual.distance_cm = Number(distEl.value)));

  // --- Bracelet / compressions ---
  const bindRange = (id: string, key: 'rate' | 'depth' | 'pressure' | 'confidence', fmt: (v: number) => string) => {
    const el = $<HTMLInputElement>(id);
    const out = $(`${id}-out`);
    const sync = () => {
      s[key] = Number(el.value);
      out.textContent = fmt(s[key]);
    };
    el.addEventListener('input', sync);
    return (v: number) => {
      el.value = String(v);
      sync();
    };
  };
  const setRate = bindRange('rate', 'rate', (v) => `${v} /min`);
  const setDepth = bindRange('depth', 'depth', (v) => `${v.toFixed(1)} cm`);
  const setPressure = bindRange('pressure', 'pressure', (v) => `${Math.round(v * 100)}%`);
  const setConf = bindRange('confidence', 'confidence', (v) => `${Math.round(v * 100)}%`);
  setRate(s.rate);
  setDepth(s.depth);
  setPressure(s.pressure);
  setConf(s.confidence);

  const presets: Record<string, [number, number, number, number]> = {
    slow: [88, 4.3, 0.6, 0.9],
    good: [110, 5.5, 0.8, 0.92],
    fast: [134, 5.4, 0.8, 0.9],
    shallow: [110, 3.8, 0.5, 0.9],
    lowconf: [110, 5.5, 0.8, 0.4],
  };
  document.querySelectorAll<HTMLButtonElement>('[data-preset]').forEach((b) =>
    b.addEventListener('click', () => {
      const [r, d, p, c] = presets[b.dataset.preset!];
      setRate(r);
      setDepth(d);
      setPressure(p);
      setConf(c);
    }),
  );

  // Make the align step visible in the mock: knock the hands off whenever we arrive there.
  app.onPhaseChange((phase) => {
    if (phase === 'align' && s.placementMode === 'auto') mock.displaceHands();
  });
}
