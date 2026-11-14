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

  private connect(): void {
    this.setStatus('connecting');
    const ws = new WebSocket(this.url);
    this.ws = ws;
    ws.onopen = () => {
      this.retryMs = 500;
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
    ws.onclose = () => {
      this.setStatus('disconnected');
      setTimeout(() => this.connect(), this.retryMs);
      this.retryMs = Math.min(this.retryMs * 2, 5000);
    };
    ws.onerror = () => ws.close();
  }
}
