"""Run the MAGI loopback WebSocket service."""

import asyncio

from backend.server.app import main


if __name__ == "__main__":
    asyncio.run(main())
