import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from datanode.config import control_addresses_from_env
from datanode.storage import BlockStorage


class BlockStorageTrashTests(unittest.TestCase):
    def test_delete_is_deferred_and_rewrite_restores_block(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            storage = BlockStorage(directory, 4)
            storage.save_block("block-1", b"data")

            self.assertTrue(storage.move_to_trash("block-1"))
            self.assertFalse(Path(directory, "block-1").exists())
            self.assertTrue(Path(directory, "trash", "block-1").exists())

            storage.purge_trash(600)
            self.assertTrue(Path(directory, "trash", "block-1").exists())

            storage.save_block("block-1", b"new")
            self.assertEqual(storage.read_block("block-1"), b"new")
            self.assertFalse(Path(directory, "trash", "block-1").exists())

    def test_expired_trash_is_removed(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            storage = BlockStorage(directory, 4)
            storage.save_block("block-1", b"data")
            storage.move_to_trash("block-1")
            trash_path = Path(directory, "trash", "block-1")
            old_time = time.time() - 10
            import os
            os.utime(trash_path, (old_time, old_time))

            storage.purge_trash(1)
            self.assertFalse(trash_path.exists())

    def test_delete_of_missing_block_is_idempotent(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            storage = BlockStorage(directory, 4)
            self.assertFalse(storage.move_to_trash("missing"))

    def test_control_addresses_prefer_plural_and_support_legacy_name(self) -> None:
        with patch.dict(
            "os.environ",
            {"CONTROL_GRPC_ADDRS": "leader:50050, follower:50050"},
            clear=True,
        ):
            self.assertEqual(
                control_addresses_from_env(),
                ["leader:50050", "follower:50050"],
            )
        with patch.dict(
            "os.environ",
            {"CONTROL_GRPC_ADDR": "legacy:50050"},
            clear=True,
        ):
            self.assertEqual(control_addresses_from_env(), ["legacy:50050"])


if __name__ == "__main__":
    unittest.main()
