from __future__ import annotations

import asyncio
import logging
import secrets
import time
from dataclasses import dataclass

logger = logging.getLogger(__name__)


@dataclass
class Lease:
    user_id: int
    token: str
    acquired_at: float


class AccessGuard:
    """One client at a time on the shared team account."""

    idle_sec = 90
    queue_timeout_sec = 180
    max_queue = 8

    def __init__(self) -> None:
        self._cond = asyncio.Condition()
        self.lease: Lease | None = None
        self.last_active: float = 0.0
        self.queue: list[int] = []

    def owner_id(self) -> int | None:
        return self.lease.user_id if self.lease else None

    def busy_by_other(self, user_id: int) -> bool:
        return self.lease is not None and self.lease.user_id != user_id and not self.is_expired()

    def matches(self, user_id: int, token: str) -> bool:
        return bool(
            self.lease
            and self.lease.user_id == user_id
            and self.lease.token == token
        )

    def touch(self, user_id: int, token: str) -> bool:
        if not self.matches(user_id, token):
            return False
        self.last_active = time.time()
        return True

    def is_free(self) -> bool:
        return self.lease is None and not self.queue

    def is_expired(self) -> bool:
        if self.lease is None:
            return False
        return time.time() - self.last_active > self.idle_sec

    def expired_lease(self) -> Lease | None:
        if self.is_expired() and self.lease is not None:
            return self.lease
        return None

    def queue_position(self, user_id: int) -> int:
        if self.lease and self.lease.user_id == user_id:
            return 0
        if user_id in self.queue:
            return self.queue.index(user_id) + 1
        return len(self.queue) + 1

    async def acquire(self, user_id: int) -> tuple[Lease, bool]:
        async with self._cond:
            if self.lease and self.lease.user_id == user_id:
                self.last_active = time.time()
                return self.lease, False

            if self.is_expired():
                logger.info("Drop expired lease user=%s", self.lease.user_id if self.lease else None)
                self.lease = None
                self._cond.notify_all()

            if user_id not in self.queue:
                if self.lease is not None and len(self.queue) >= self.max_queue:
                    raise OverflowError("queue full")
                self.queue.append(user_id)

            deadline = time.time() + self.queue_timeout_sec
            try:
                while True:
                    if self.lease and self.lease.user_id == user_id:
                        self.last_active = time.time()
                        return self.lease, False
                    if self.is_expired():
                        self.lease = None
                    if self.lease is None and self.queue and self.queue[0] == user_id:
                        self.queue.pop(0)
                        lease = Lease(
                            user_id=user_id,
                            token=secrets.token_hex(4),
                            acquired_at=time.time(),
                        )
                        self.lease = lease
                        self.last_active = time.time()
                        logger.info("Lease granted user=%s token=%s", user_id, lease.token)
                        return lease, True
                    remaining = deadline - time.time()
                    if remaining <= 0:
                        raise TimeoutError("queue timeout")
                    try:
                        await asyncio.wait_for(
                            self._cond.wait(),
                            timeout=min(remaining, 4),
                        )
                    except asyncio.TimeoutError:
                        # Wake periodically to check expiry, but keep waiting
                        # until the real queue deadline.
                        continue
            finally:
                if user_id in self.queue and (not self.lease or self.lease.user_id != user_id):
                    self.queue = [item for item in self.queue if item != user_id]
                    self._cond.notify_all()

    async def release(self, user_id: int, token: str | None = None) -> bool:
        async with self._cond:
            if self.lease is None or self.lease.user_id != user_id:
                return False
            if token is not None and self.lease.token != token:
                return False
            logger.info("Lease released user=%s", user_id)
            self.lease = None
            self._cond.notify_all()
            return True

    async def drop_waiter(self, user_id: int) -> None:
        async with self._cond:
            self.queue = [item for item in self.queue if item != user_id]
            self._cond.notify_all()
