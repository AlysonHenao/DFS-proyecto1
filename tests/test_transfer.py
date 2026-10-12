import unittest
import sys
from pathlib import Path
from unittest.mock import Mock

import grpc

sys.path.insert(0, str(Path(__file__).parent.parent / "client"))
sys.modules.pop("config", None)
sys.modules.pop("auth", None)
from client.transfer import FileTransfer


class FailingDataNode:
    def __init__(self, failures: int) -> None:
        self.failures = failures

    def read_block(self, address: str, block_id: str):
        if address.startswith("bad"):
            raise grpc.RpcError("unavailable")
        if self.failures:
            self.failures -= 1
            raise ValueError("encrypted block authentication failed")
        yield type("Chunk", (), {"data": b"ok"})()


class FileTransferFallbackTests(unittest.TestCase):
    def test_download_uses_next_replica_after_failure(self) -> None:
        transfer = FileTransfer(Mock(), FailingDataNode(0))
        output = Mock()
        transfer._download_block(
            {"block_id": "block-1", "nodes": ["bad:50051", "good:50051"]},
            output,
        )
        output.write.assert_called_once_with(b"ok")

    def test_download_fails_when_all_replicas_fail(self) -> None:
        transfer = FileTransfer(Mock(), FailingDataNode(1))
        with self.assertRaisesRegex(RuntimeError, "all replicas failed for block-1"):
            transfer._download_block(
                {"block_id": "block-1", "nodes": ["bad:50051", "also-bad:50051"]},
                Mock(),
            )


if __name__ == "__main__":
    unittest.main()
