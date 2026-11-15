import { parseMessage, type InboundMsg, type OutboundMsg } from '../protocol';
import { Emitter, type MessageSource, type SourceStatus } from './types';

/**
 * Real source: the Arduino's WebSocket server (JSON text frames, one message each).
 *
 * UNVERIFIED (go/no-go test #3): whether the Even app WebView can reach a plain
 * ws:// server on the LAN. The Arduino's address must also be in app.json's
 * network whitelist. WebSockets drop when the app is backgrounded - this class
 * reconnects with backoff, and the UI shows "lost" while disconnected.
 */
export class WebSocketSource implements MessageSource {
  readonly name: string;
  status: SourceStatus = 'disconnected';
  /** Why the last attempt failed, for the phone panel ("" when connected). */
  detail = '';
  private attempts = 0;
  private ws: WebSocket | undefined;
  private retryMs = 500;
  private messages = new Emitter<InboundMsg>();
  private statuses = new Emitter<SourceStatus>();

  constructor(private url: string) {
    this.name = `ws ${url}`;
  }

  onMessage(cb: (msg: InboundMsg) => void): void {
    this.messages.on(cb);
  }
  onStatus(cb: (status: SourceStatus) => void): void {
    this.statuses.on(cb);
  }

  start(): void {
    this.connect();
  }

  send(msg: OutboundMsg): void {
    if (this.ws?.readyState === WebSocket.OPEN) this.ws.send(JSON.stringify(msg));
  }

  private setStatus(s: SourceStatus): void {
    this.status = s;
    this.statuses.emit(s);
  }

  private retry(): void {
    setTimeout(() => this.connect(), this.retryMs);
    this.retryMs = Math.min(this.retryMs * 2, 5000);
  }

  private connect(): void {
    this.attempts++;
    this.setStatus('connecting');
    const started = Date.now();
    let ws: WebSocket;
    try {
      ws = new WebSocket(this.url);
    } catch (e) {
      // Thrown synchronously when the page is not allowed to open this address at all
      // (e.g. ws:// from an https page = mixed content). Without this the retries stopped.
      this.detail = `blocked before connecting: ${e instanceof Error ? `${e.name}: ${e.message}` : String(e)}`;
      this.setStatus('disconnected');
      this.retry();
      return;
    }
    this.ws = ws;
    ws.onopen = () => {
      this.retryMs = 500;
      this.detail = '';
      this.setStatus('connected');
    };
    ws.onmessage = (ev) => {
      try {
        const msg = parseMessage(JSON.parse(String(ev.data)));
        if (msg) this.messages.emit(msg);
      } catch {
        // Ignore malformed frames; staleness checks surface a silent sensor.
      }
    };
    ws.onclose = (ev) => {
      const ms = Date.now() - started;
      // A failure within a few ms never reached the network (blocked inside the app);
      // a failure after seconds is the network (no route, firewall, wrong address).
      this.detail = `attempt ${this.attempts}: closed ${ev.code} after ${ms} ms` +
        (ms < 50 ? ' (failed at once: refused, or blocked by the app)' : ms > 2500 ? ' (no answer: network?)' : '');
      this.setStatus('disconnected');
      this.retry();
    };
    ws.onerror = () => ws.close();
  }
}
