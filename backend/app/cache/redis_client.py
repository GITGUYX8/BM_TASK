"""Shared per-process Redis client.

Celery prefork forks children that must never share the parent's socket: a
TCP connection used from two processes corrupts both streams (redis-py
likewise forbids sharing clients across forks/threads). So no client is
created at import time. The first use in each process connects, guarded by
PID: a forked child that inherited the file descriptor reconnects on first
use instead of touching the parent's socket.

The subscriber path (`events.TraceSubscriber`) intentionally keeps its own
dedicated connection per stream: a connection in subscribed mode cannot
serve regular commands, and its lifetime is tied to the stream (closed on
disconnect). Everything else shares the client below.
"""

import os

import redis.asyncio as aioredis

from app.config import settings

_client = None
_client_pid = None
_client_url = None


async def get_client(redis_url: str | None = None):
    """Return the current process's shared client, connecting on first use."""
    global _client, _client_pid, _client_url
    url = redis_url or settings.redis_url
    if _client is None or _client_pid != os.getpid() or _client_url != url:
        if _client is not None:
            try:
                await _client.aclose()
            except Exception:
                pass
        _client = await aioredis.from_url(url, decode_responses=True)
        _client_pid = os.getpid()
        _client_url = url
    return _client


def reset_client() -> None:
    """Drop the cached client (tests only — forces reconnect on next use)."""
    global _client, _client_pid, _client_url
    _client = None
    _client_pid = None
    _client_url = None
