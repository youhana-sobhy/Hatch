"""In-process, thread-safe event bus that fans out live events to WebSocket clients.

Pipelines run on worker threads while WebSocket handlers live on the asyncio loop, so
publishing hops onto each subscriber's loop with ``call_soon_threadsafe``.
"""

from __future__ import annotations

import asyncio
import threading
from collections import deque
from datetime import UTC, datetime
from typing import Any


class _Subscriber:
    def __init__(self, loop: asyncio.AbstractEventLoop) -> None:
        self.loop = loop
        self.queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue(maxsize=1000)

    def deliver(self, event: dict[str, Any]) -> None:
        def _put() -> None:
            if self.queue.full():  # drop the oldest event for slow consumers
                self.queue.get_nowait()
            self.queue.put_nowait(event)

        self.loop.call_soon_threadsafe(_put)


class EventBus:
    def __init__(self, history: int = 200) -> None:
        self._lock = threading.Lock()
        self._subscribers: set[_Subscriber] = set()
        self._history: deque[dict[str, Any]] = deque(maxlen=history)
        self._listeners: list = []

    def publish(self, event: dict[str, Any]) -> None:
        event = {"at": datetime.now(UTC).isoformat(), **event}
        with self._lock:
            self._history.append(event)
            subscribers = list(self._subscribers)
            listeners = list(self._listeners)
        for subscriber in subscribers:
            try:
                subscriber.deliver(event)
            except RuntimeError:  # loop closed
                self.unsubscribe(subscriber)
        for listener in listeners:
            listener(event)

    def subscribe(self) -> _Subscriber:
        subscriber = _Subscriber(asyncio.get_running_loop())
        with self._lock:
            self._subscribers.add(subscriber)
        return subscriber

    def unsubscribe(self, subscriber: _Subscriber) -> None:
        with self._lock:
            self._subscribers.discard(subscriber)

    def add_listener(self, listener) -> None:
        """Register a synchronous callback (used by notifications and tests)."""
        with self._lock:
            self._listeners.append(listener)

    def remove_listener(self, listener) -> None:
        with self._lock:
            if listener in self._listeners:
                self._listeners.remove(listener)

    def recent(self, limit: int = 50) -> list[dict[str, Any]]:
        with self._lock:
            return list(self._history)[-limit:]


bus = EventBus()
