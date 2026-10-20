"""Expose a loopback-only service on the container's private address (lab sidecar; shares the lab's network namespace).

    python tcp_forward.py 8811

Binds <container private IP>:PORT and relays bytes to 127.0.0.1:PORT unchanged,
so a runner on the same internal network can reach a target that only listens
on loopback. Headers are not touched.
"""

import asyncio
import socket
import sys


async def pipe(reader, writer):
    try:
        while data := await reader.read(65536):
            writer.write(data)
            await writer.drain()
    finally:
        writer.close()


async def handle(client_reader, client_writer, port):
    upstream_reader, upstream_writer = await asyncio.open_connection("127.0.0.1", port)
    await asyncio.gather(pipe(client_reader, upstream_writer), pipe(upstream_reader, client_writer), return_exceptions=True)


async def main(port: int):
    address = socket.gethostbyname(socket.gethostname())
    server = await asyncio.start_server(lambda r, w: handle(r, w, port), address, port)
    print(f"forwarding {address}:{port} -> 127.0.0.1:{port}", flush=True)
    async with server:
        await server.serve_forever()


if __name__ == "__main__":
    asyncio.run(main(int(sys.argv[1])))
