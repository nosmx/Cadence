/**
 * Spoken commands. The rescuer's hands stay on the chest, so every step is
 * driven by voice:
 *   "READY" (or "NEXT") -> go to the next step / start compressions
 *   "BACK"              -> previous step
 *   "STOP"              -> end the compression session
 */
export type Command = 'ready' | 'back' | 'stop';

/** Words the recognizer is restricted to. "[unk]" absorbs everything else. */
export const GRAMMAR = ['ready', 'next', 'back', 'stop', '[unk]'];

export function parseCommand(text: string): Command | null {
  const words: string[] = text.toLowerCase().match(/[a-z]+/g) ?? [];
  if (words.includes('stop')) return 'stop';
  if (words.includes('back')) return 'back';
  if (words.includes('ready') || words.includes('next')) return 'ready';
  return null;
}

export type VoiceStatus = 'off' | 'loading' | 'listening' | 'error';
