import { OsEventTypeList, type EvenHubEvent } from '@evenrealities/even_hub_sdk';
import type { Input } from './app';

/**
 * Map a raw Even Hub event (temple touchpad or R1 ring) to an app input.
 * Returns null for events the app doesn't act on (audio, IMU, foreground changes).
 */
export function toInput(ev: EvenHubEvent): Input | null {
  if (ev.audioEvent || ev.menuItemClickEvent) return null;
  if (ev.sysEvent?.imuData) return null;
  const e = ev.textEvent ?? ev.listEvent ?? ev.sysEvent;
  if (!e) return null;
  // Protobuf drops zero-valued fields, so a click (0) can arrive with eventType missing.
  const type = e.eventType ?? OsEventTypeList.CLICK_EVENT;
  switch (type) {
    case OsEventTypeList.CLICK_EVENT: return 'tap';
    case OsEventTypeList.DOUBLE_CLICK_EVENT: return 'double';
    case OsEventTypeList.SCROLL_TOP_EVENT: return 'up';
    case OsEventTypeList.SCROLL_BOTTOM_EVENT: return 'down';
    default: return null;
  }
}

/** Keyboard stand-in for the touchpad when running in a plain browser. */
export function keyToInput(key: string): Input | null {
  switch (key) {
    case 'Enter':
    case ' ': return 'tap';
    case 'Backspace':
    case 'd': return 'double';
    case 'ArrowUp': return 'up';
    case 'ArrowDown': return 'down';
    default: return null;
  }
}
