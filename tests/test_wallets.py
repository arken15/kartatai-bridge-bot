from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from src.wallets import WalletStore, normalize_network, validate_address


class WalletStoreTests(unittest.TestCase):
    def setUp(self) -> None:
        self.store = WalletStore(Path(tempfile.mkdtemp()) / "wallets.json")

    def test_wallets_are_isolated_by_user_id(self) -> None:
        trc20 = "T" + "A" * 33
        bep20 = "0x" + "b" * 40
        self.store.set_address(101, "trc20", trc20, username="first")
        self.store.set_address(202, "bep20", bep20, username="second")

        self.assertEqual(self.store.get(101).trc20, trc20)
        self.assertEqual(self.store.get(101).bep20, "")
        self.assertEqual(self.store.get(202).trc20, "")
        self.assertEqual(self.store.get(202).bep20, bep20)

    def test_store_survives_reload_and_admin_lookup(self) -> None:
        address = "0x" + "a" * 40
        self.store.set_address(303, "bep20", address, username="CryptoUser")
        reloaded = WalletStore(self.store.path)

        self.assertEqual(reloaded.find("@cryptouser").user_id, 303)
        self.assertEqual(reloaded.find("303").bep20, address)

    def test_network_and_address_validation(self) -> None:
        self.assertEqual(normalize_network("👛 USDT (TRC-20)"), "trc20")
        self.assertEqual(normalize_network("👛 USDT (BEP-20)"), "bep20")
        self.assertTrue(validate_address("trc20", "T" + "A" * 33))
        self.assertTrue(validate_address("bep20", "0x" + "a" * 40))
        self.assertFalse(validate_address("trc20", "0x" + "a" * 40))
        self.assertFalse(validate_address("bep20", "T" + "A" * 33))


if __name__ == "__main__":
    unittest.main()
