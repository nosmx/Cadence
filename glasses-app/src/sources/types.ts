import type { InboundMsg, OutboundMsg } from '../protocol';

export type SourceStatus = 'connecting' | 'connected' | 'disconnected';

/** Where messages come from: the mock generator now, the Arduino server later. */
export interface MessageSource {
  readonly name: string;
  readonly status: SourceStatus;
  onMessage(cb: (msg: InboundMsg) => void): void;
  onStatus(cb: (status: SourceStatus) => void): void;
  send(msg: OutboundMsg): void;
  start(): void;
}

/** Small helper so sources don't each re-implement listener lists. */
export class Emitter<T> {
  private cbs: ((v: T) => void)[] = [];
  on(cb: (v: T) => void): void {
    this.cbs.push(cb);
  }
  emit(v: T): void {
    for (const cb of this.cbs) cb(v);
  }
}
