"""Publish loopback-only listeners of the shared network namespace (infra/compose/full-stack.yml).

    python loopback_relay.py 8720 8730 8740 8811 8812

Docker forwards a published port to the namespace's interface address, not to 127.0.0.1, so a process that
binds loopback only (the MCP tool server, the encoder service, Ollama, the lab applications) is unreachable
from the host. This relay listens on the interface address of each given port and copies bytes to 127.0.0.1
on the same port.
It adds no exposure of its own: the hub publishes these ports on the host's 127.0.0.1 only.
"""

import asyncio
import socket
import sys


async def _pipe(reader, writer):
    try:
        while data := await reader.read(65536):
            writer.write(data)
            await writer.drain()
    except (ConnectionError, OSError):
        pass
    finally:
        writer.close()


def _handler(port):
    async def handle(client_reader, client_writer):
        try:
            upstream_reader, upstream_writer = await asyncio.open_connection("127.0.0.1", port)
        except OSError:  # the service is not listening (yet); the client sees a closed connection
            client_writer.close()
            return
        await asyncio.gather(_pipe(client_reader, upstream_writer), _pipe(upstream_reader, client_writer))
    return handle


async def main(ports):
    address = socket.gethostbyname(socket.gethostname())  # the namespace's interface address
    servers = [await asyncio.start_server(_handler(p), address, p) for p in ports]
    print(f"relaying {address}:{{{','.join(map(str, ports))}}} -> 127.0.0.1", flush=True)
    await asyncio.gather(*(s.serve_forever() for s in servers))


if __name__ == "__main__":
    asyncio.run(main([int(p) for p in sys.argv[1:]]))
