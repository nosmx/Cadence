"""Outputs for messages. publish() never blocks the sensing loop:

  stdout     JSON lines (default on)
  WebSocket  server on ws://0.0.0.0:8765, every message to every client
  HTTP POST  each message to a hub URL
  serial     one compact JSON line per message to a USB serial port (for an Arduino hub)

A slow or dead client only loses its own messages: every client has a small queue and
the oldest message is dropped when it is full.
"""
import asyncio
import json
import queue
import sys
import threading
import urllib.request

from . import config


class WebSocketOutput:
    """WebSocket server in a background thread. Text a client sends is given to
    on_message(dict) (used for the Arduino's "chest" messages)."""

    def __init__(self, host=config.WS_HOST, port=config.WS_PORT, on_message=None):
        self.host, self.port, self.on_message = host, port, on_message
        self._clients = {}          # connection -> asyncio.Queue
        self._loop = None
        self._ready = threading.Event()
        self._error = None
        self._stop = None
        self._thread = threading.Thread(target=self._run, name="ws-server", daemon=True)

    def start(self):
        self._thread.start()
        self._ready.wait(5)
        if self._error:
            raise self._error
        return self

    @property
    def client_count(self):
        return len(self._clients)

    def _run(self):
        try:
            asyncio.run(self._main())
        except Exception as e:          # e.g. the port is taken
            self._error = e
            self._ready.set()

    async def _main(self):
        from websockets.asyncio.server import serve
        self._loop = asyncio.get_running_loop()
        self._stop = asyncio.Event()
        async with serve(self._handle, self.host, self.port):
            self._ready.set()
            await self._stop.wait()

    async def _handle(self, connection):
        outbox = asyncio.Queue(maxsize=config.CLIENT_QUEUE)
        self._clients[connection] = outbox
        sender = asyncio.ensure_future(self._send_loop(connection, outbox))
        try:
            async for text in connection:
                if self.on_message is None:
                    continue
                try:
                    data = json.loads(text)
                except (ValueError, TypeError):
                    continue
                if isinstance(data, dict):
                    try:
                        self.on_message(data)
                    except Exception as e:
                        print("ws: problem in the message handler: %s" % e, file=sys.stderr)
        except Exception:
            pass
        finally:
            self._clients.pop(connection, None)
            sender.cancel()

    @staticmethod
    async def _send_loop(connection, outbox):
        try:
            while True:
                await connection.send(await outbox.get())
        except Exception:
            pass

    def _broadcast(self, text):
        for outbox in list(self._clients.values()):
            if outbox.full():
                try:
                    outbox.get_nowait()         # slow client: drop its oldest message
                except asyncio.QueueEmpty:
                    pass
            outbox.put_nowait(text)

    def send(self, text):
        if self._loop is not None and not self._loop.is_closed():
            try:
                self._loop.call_soon_threadsafe(self._broadcast, text)
            except RuntimeError:
                pass

    def close(self):
        if self._loop is not None and self._stop is not None and not self._loop.is_closed():
            try:
                self._loop.call_soon_threadsafe(self._stop.set)
            except RuntimeError:
                pass
        self._thread.join(2)


class _Worker:
    """A thread with a bounded queue: put never blocks, the oldest entry goes when full."""

    def __init__(self, name, work, size):
        self._queue = queue.Queue(maxsize=size)
        self._work = work
        self.failed = 0
        self.sent = 0
        self._warned = False
        self._name = name
        threading.Thread(target=self._run, name=name, daemon=True).start()

    def put(self, item):
        while True:
            try:
                self._queue.put_nowait(item)
                return
            except queue.Full:
                try:
                    self._queue.get_nowait()
                except queue.Empty:
                    pass

    def _run(self):
        while True:
            item = self._queue.get()
            if item is None:
                return
            try:
                self._work(item)
                self.sent += 1
                self._warned = False
            except Exception as e:
                self.failed += 1
                if not self._warned:        # say it once, not for every message
                    self._warned = True
                    print("%s: could not send (%s). Sensing goes on." % (self._name, e), file=sys.stderr)

    def close(self):
        self.put(None)


class HttpPostOutput:
    """By default only "compression" and "placement" are posted (--post-all: every type)."""

    def __init__(self, url, types=("compression", "placement")):
        self.url = url
        self.types = types
        self._worker = _Worker("post", self._post, config.POST_QUEUE)

    def _post(self, text):
        request = urllib.request.Request(self.url, data=text.encode("utf-8"),
                                         headers={"Content-Type": "application/json"}, method="POST")
        with urllib.request.urlopen(request, timeout=config.POST_TIMEOUT_S) as response:
            response.read()

    def send(self, text, kind=None):
        if self.types is None or kind is None or kind in self.types:
            self._worker.put(text)

    def close(self):
        self._worker.close()


class SerialOutput:
    """Writes each message as one JSON line to a serial port. `port` is either a port name
    ("COM5") or an object with write(bytes) (the serial chest adapter shares its port)."""

    def __init__(self, port, baud=115200):
        if isinstance(port, str):
            import serial
            port = serial.Serial(port, baud, timeout=0.2, write_timeout=0.5)
        self._port = port
        self._worker = _Worker("serial-out", self._write, config.POST_QUEUE)

    def _write(self, text):
        self._port.write(text.encode("utf-8") + b"\n")

    def send(self, text):
        self._worker.put(text)

    def close(self):
        self._worker.close()


class Publisher:
    def __init__(self, stdout=True, ws=False, ws_port=config.WS_PORT, post_url=None, serial_out=None,
                 on_message=None, stream=None, post_all=False):
        self._stream = stream or sys.stdout
        self._stdout = stdout
        self._outputs = []
        self.ws = None
        if ws:
            self.ws = WebSocketOutput(port=ws_port, on_message=on_message).start()
            self._outputs.append(self.ws)
        if post_url:
            self._outputs.append(HttpPostOutput(post_url, types=None if post_all else ("compression", "placement")))
        if serial_out is not None:
            self._outputs.append(SerialOutput(serial_out))

    def publish(self, message):
        text = json.dumps(message, separators=(",", ":"))
        if self._stdout:
            try:
                self._stream.write(text + "\n")
                self._stream.flush()
            except (OSError, ValueError):
                self._stdout = False
        for output in self._outputs:
            if isinstance(output, HttpPostOutput):
                output.send(text, message.get("type"))
            else:
                output.send(text)

    def close(self):
        for output in self._outputs:
            output.close()
