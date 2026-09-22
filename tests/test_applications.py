from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from src.applications import ApplicationStore
from src.config import merge_admin_ids
from src.content import ContentStore


class ApplicationStoreTests(unittest.TestCase):
    def setUp(self) -> None:
        self.store = ApplicationStore(Path(tempfile.mkdtemp()) / "applications.json")

    def test_application_requires_decision_before_access(self) -> None:
        self.store.start(10, username="new")
        self.store.set_answer(10, 0, "год в поддержке")
        self.store.set_answer(10, 1, "6 часов")
        self.store.set_answer(10, 2, "да, только OnlyFans")
        self.assertFalse(self.store.is_approved(10))

        self.store.submit(10)
        self.assertEqual(self.store.count("pending"), 1)
        self.assertFalse(self.store.is_approved(10))

        self.assertTrue(self.store.decide(10, "approved", 8708949561))
        self.assertTrue(self.store.is_approved(10))
        self.assertFalse(self.store.decide(10, "rejected", 7573475844))

    def test_rejected_user_can_start_again(self) -> None:
        self.store.start(11, username="again")
        for index, answer in enumerate(("a", "b", "c")):
            self.store.set_answer(11, index, answer)
        self.store.submit(11)
        self.store.decide(11, "rejected", 7741029169)

        restarted = self.store.start(11, username="again")
        self.assertEqual(restarted.status, "draft")
        self.assertFalse(self.store.is_approved(11))

    def test_existing_client_stays_approved(self) -> None:
        self.store.ensure_approved(12)
        self.store.ensure_approved(12)
        self.assertTrue(self.store.is_approved(12))


class ContentAndAdminTests(unittest.TestCase):
    def test_manual_is_shared_and_validated(self) -> None:
        store = ContentStore(Path(tempfile.mkdtemp()) / "content.json")
        store.set_manual("Текст мануала", 8708949561)
        self.assertEqual(ContentStore(store.path).manual_text(), "Текст мануала")
        with self.assertRaises(ValueError):
            store.set_manual("   ", 8708949561)

    def test_requested_admins_are_always_included(self) -> None:
        admins = merge_admin_ids(111, [8708949561, 222])
        self.assertEqual(admins[:3], [8708949561, 7573475844, 7741029169])
        self.assertEqual(admins[-2:], [222, 111])


if __name__ == "__main__":
    unittest.main()
