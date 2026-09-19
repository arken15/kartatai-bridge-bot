from __future__ import annotations

import asyncio
import unittest

from src.access import AccessGuard


class AccessGuardTests(unittest.IsolatedAsyncioTestCase):
    async def test_waiter_gets_lease_after_release(self) -> None:
        guard = AccessGuard()
        first, _ = await guard.acquire(1)
        waiting = asyncio.create_task(guard.acquire(2))
        await asyncio.sleep(0)

        self.assertEqual(guard.queue_position(2), 1)
        await guard.release(1, first.token)
        second, _ = await asyncio.wait_for(waiting, timeout=1)
        self.assertEqual(second.user_id, 2)

    async def test_cancelled_waiter_does_not_block_queue(self) -> None:
        guard = AccessGuard()
        first, _ = await guard.acquire(1)
        waiting = asyncio.create_task(guard.acquire(2))
        await asyncio.sleep(0)
        waiting.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await waiting

        self.assertNotIn(2, guard.queue)
        await guard.release(1, first.token)
        third, _ = await asyncio.wait_for(guard.acquire(3), timeout=1)
        self.assertEqual(third.user_id, 3)

    async def test_same_user_reuses_lease(self) -> None:
        guard = AccessGuard()
        first, switched = await guard.acquire(1)
        second, switched_again = await guard.acquire(1)

        self.assertTrue(switched)
        self.assertFalse(switched_again)
        self.assertEqual(first.token, second.token)


if __name__ == "__main__":
    unittest.main()
