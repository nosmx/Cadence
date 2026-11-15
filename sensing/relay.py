"""Pass the board's WebSocket on to the phone through this laptop.

For when the phone cannot reach the UNO Q over Wi-Fi (venue Wi-Fi blocks devices from
talking to each other, or the board cannot join the hotspot). The board stays on the USB
cable; the laptop joins the phone's hotspot; the phone connects to the laptop.

    adb forward tcp:18765 tcp:8765          board's port 8765 -> this laptop's 18765 (over USB)
    python3 -m sensing.relay                this laptop's port 8765 (all networks) -> 18765

Then on the phone: ws://<this laptop's hotspot address>:8765
Standard library only. It copies bytes both ways, so it works for any WebSocket client.
"""
import argparse
import asyncio
import socket
import sys


async def pipe(reader, writer):
    try:
        while data := await reader.read(65536):
            writer.write(data)
            await writer.drain()
    except (ConnectionError, OSError):
        pass
    finally:
        try:
            writer.close()
        except Exception:
            pass


def addresses():
    """This laptop's IPv4 addresses (best effort), to tell the user what to type on the phone."""
    found = set()
    try:
        for info in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET):
            found.add(info[4][0])
    except OSError:
        pass
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.connect(("172.20.10.1", 9))          # no packet is sent; picks the hotspot-facing address if any
            found.add(s.getsockname()[0])
    except OSError:
        pass
    return sorted(a for a in found if not a.startswith("127."))


async def main(listen_port, target_host, target_port):
    async def handle(client_reader, client_writer):
        peer = client_writer.get_extra_info("peername")
        try:
            board_reader, board_writer = await asyncio.open_connection(target_host, target_port)
        except OSError as e:
            print("relay: phone %s connected, but the board is not reachable on %s:%d (%s). "
                  "Is the sensing program running, and did you run: adb forward tcp:%d tcp:8765 ?"
                  % (peer[0], target_host, target_port, e, target_port), file=sys.stderr)
            client_writer.close()
            return
        print("relay: %s connected" % peer[0], file=sys.stderr)
        await asyncio.gather(pipe(client_reader, board_writer), pipe(board_reader, client_writer))
        print("relay: %s disconnected" % peer[0], file=sys.stderr)

    server = await asyncio.start_server(handle, "0.0.0.0", listen_port)
    shown = ", ".join("ws://%s:%d" % (a, listen_port) for a in addresses()) or "ws://<this laptop's IP>:%d" % listen_port
    print("Relay ready. On the phone, use: %s   (Ctrl+C to stop)" % shown, file=sys.stderr)
    async with server:
        await server.serve_forever()


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--port", type=int, default=8765, help="port the phone connects to (default 8765)")
    ap.add_argument("--to", default="127.0.0.1:18765", help="where the board's WebSocket is (default the adb forward)")
    a = ap.parse_args()
    host, _, port = a.to.rpartition(":")
    try:
        asyncio.run(main(a.port, host or "127.0.0.1", int(port)))
    except KeyboardInterrupt:
        pass
