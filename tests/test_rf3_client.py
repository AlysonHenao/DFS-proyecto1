import sys
import unittest
from pathlib import Path
from unittest.mock import Mock

sys.path.insert(0, str(Path(__file__).parent.parent / "client"))
sys.modules.pop("config", None)
sys.modules.pop("auth", None)

from client.control_client import ControlClient
from client.transfer import FileTransfer, sha256


class ControlClientRF3ContractTests(unittest.TestCase):
    def test_plan_read_and_write_use_expected_contract(self) -> None:
        client = ControlClient(Mock())
        client.request = Mock(
            side_effect=[
                Mock(json=lambda: {"blocks": []}),
                Mock(json=lambda: {"blocks": []}),
            ]
        )

        client.plan_read("session-1", 4, 8)
        client.plan_write("session-1", 4, 3)

        self.assertEqual(
            client.request.call_args_list[0].kwargs["params"],
            {"session_id": "session-1", "offset": 4, "length": 8},
        )
        self.assertEqual(
            client.request.call_args_list[1].kwargs["json"],
            {
                "session_id": "session-1",
                "offset": 4,
                "length": 3,
                "append": False,
            },
        )


class FileTransferRF3Tests(unittest.TestCase):
    def test_read_range_spans_blocks_and_verifies_hash(self) -> None:
        datanodes = Mock()
        datanodes.read_block.side_effect = [
            [type("Chunk", (), {"data": b"abcd"})()],
            [type("Chunk", (), {"data": b"efgh"})()],
        ]
        transfer = FileTransfer(Mock(), datanodes)
        plan = {
            "block_size": 4,
            "blocks": [
                {
                    "index": 0,
                    "size": 4,
                    "block_id": "a",
                    "nodes": ["a"],
                    "sha256": sha256(b"abcd"),
                },
                {
                    "index": 1,
                    "size": 4,
                    "block_id": "b",
                    "nodes": ["b"],
                    "sha256": sha256(b"efgh"),
                },
            ],
        }

        self.assertEqual(transfer.read_range(plan, 2, 4), b"cdef")

    def test_read_range_rejects_tampered_block(self) -> None:
        datanodes = Mock()
        datanodes.read_block.return_value = [
            type("Chunk", (), {"data": b"tampered"})()
        ]
        transfer = FileTransfer(Mock(), datanodes)
        plan = {
            "block_size": 8,
            "blocks": [
                {
                    "index": 0,
                    "size": 8,
                    "block_id": "a",
                    "nodes": ["a"],
                    "sha256": sha256(b"expected"),
                }
            ],
        }

        with self.assertRaisesRegex(RuntimeError, "all replicas failed"):
            transfer.read_range(plan, 0, 8)

    def test_read_range_uses_next_replica_after_hash_failure(self) -> None:
        datanodes = Mock()
        datanodes.read_block.side_effect = [
            [type("Chunk", (), {"data": b"tampered"})()],
            [type("Chunk", (), {"data": b"valid"})()],
        ]
        transfer = FileTransfer(Mock(), datanodes)
        plan = {
            "block_size": 5,
            "blocks": [
                {
                    "index": 0,
                    "size": 5,
                    "block_id": "a",
                    "nodes": ["bad", "good"],
                    "sha256": sha256(b"valid"),
                }
            ],
        }

        self.assertEqual(transfer.read_range(plan, 0, 5), b"valid")

    def test_read_range_rejects_out_of_bounds(self) -> None:
        transfer = FileTransfer(Mock(), Mock())
        with self.assertRaisesRegex(ValueError, "exceeds"):
            transfer.read_range({"block_size": 4, "blocks": []}, 0, 1)


if __name__ == "__main__":
    unittest.main()
