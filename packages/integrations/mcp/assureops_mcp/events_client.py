"""Ordered, authenticated delivery of runtime events to AssureOps."""

import queue
import threading
import time
import uuid

import httpx

from . import settings


class EventEmitter:
    def __init__(self, source_id: str, token: str, release_fn):
        self.source_id = source_id
        self.token = token
        self.release_fn = release_fn
        self.epoch = uuid.uuid4().hex[:8]  # new epoch per process start; old gaps are not assumed delivered
        self.seq = 0
        self.lock = threading.Lock()
        self.outbox: queue.Queue = queue.Queue()
        self.undelivered = 0

    def start(self, heartbeat_seconds: int = 20):
        threading.Thread(target=self._send_loop, daemon=True).start()
        threading.Thread(target=self._heartbeat_loop, args=(heartbeat_seconds,), daemon=True).start()

    def emit(self, event_type: str, payload: dict, test_traffic: bool = False, release: str | None = None):
        with self.lock:
            self.seq += 1
            event = {
                "event_id": uuid.uuid4().hex, "source_id": self.source_id, "epoch": self.epoch, "seq": self.seq,
                "environment": settings.ENVIRONMENT, "release": release or self.release_fn(), "event_type": event_type,
                "observed_at": time.time(), "test_traffic": test_traffic, "payload": payload,
            }
            self.outbox.put(event)

    def _send_loop(self):
        while True:
            event = self.outbox.get()
            for attempt in range(3):
                try:
                    response = httpx.post(f"{settings.API_URL}/v1/runtime/events:batch", json={"events": [event]},
                                          headers={"Authorization": f"Bearer {self.token}"}, timeout=3)
                    if response.status_code < 500:
                        break
                except httpx.HTTPError:
                    pass
                time.sleep(0.5 * (attempt + 1))
            else:
                self.undelivered += 1  # becomes a sequence gap on the receiver

    def _heartbeat_loop(self, seconds: int):
        while True:
            self.emit("heartbeat", {"undelivered": self.undelivered})
            time.sleep(seconds)
