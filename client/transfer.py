from __future__ import annotations

import os
import hashlib
from typing import TYPE_CHECKING, Any, BinaryIO

import grpc

from config import CHUNK_SIZE
if TYPE_CHECKING:
    from control_client import ControlClient
    from datanode_client import DataNodeClient

#Coordina el flujo de transferencia de archivos entre el cliente y los nodos de datos, 
# manejando la planificación, escritura y lectura de bloques de datos a través del servidor 
# de control y los nodos de datos.

class FileTransfer:
    def __init__(self, control: ControlClient, datanodes: DataNodeClient) -> None:
        self.control = control
        self.datanodes = datanodes

    def upload(self, source: str, remote_path: str) -> None:
        plan = self.control.plan_upload(remote_path, os.path.getsize(source))
        committed: list[dict[str, Any]] = []
        try:
            with open(source, "rb") as stream:
                for block in plan["blocks"]:
                    data = stream.read(block["size"])
                    chain = block["chain"]
                    reply = self.datanodes.write_block(
                        chain[0], block["block_id"], data, chain[1:], CHUNK_SIZE
                    )
                    if not reply.ok:
                        raise RuntimeError(reply.error)
                    committed.append({
                        "index": block["index"],
                        "block_id": block["block_id"],
                        "stored_on": list(reply.stored_on),
                    })
            self.control.commit_upload(remote_path, committed)
        except Exception:
            self.control.abort_upload(remote_path)
            raise

    def download(self, remote_path: str, destination: str) -> None:
        plan = self.control.plan_download(remote_path)
        with open(destination, "wb") as output:
            for block in plan["blocks"]:
                self._download_block(block, output)

    def read_range(self, plan: dict[str, Any], offset: int, length: int) -> bytes:
        if offset < 0 or length < 0:
            raise ValueError("offset and length must be non-negative")
        if length == 0:
            return b""

        block_size = int(plan["block_size"])
        result = bytearray()
        end = offset + length
        for block in plan["blocks"]:
            block_offset = int(block.get("offset", block["index"] * block_size))
            block_end = block_offset + int(block["size"])
            if block_end <= offset or block_offset >= end:
                continue
            data = self._read_block(block)
            expected_hash = block.get("sha256")
            if expected_hash and sha256(data) != expected_hash:
                raise ValueError(f"sha256 mismatch for {block['block_id']}")
            start = max(offset, block_offset) - block_offset
            stop = min(end, block_end) - block_offset
            result.extend(data[start:stop])
        if len(result) != length:
            raise ValueError("requested range exceeds the file version")
        return bytes(result)

    def write_block_copy(self, block: dict[str, Any], data: bytes) -> dict[str, Any]:
        chain = block["chain"]
        reply = self.datanodes.write_block(
            chain[0], block["block_id"], data, chain[1:], CHUNK_SIZE
        )
        if not reply.ok:
            raise RuntimeError(reply.error)
        actual_hash = sha256(data)
        expected_hash = block.get("sha256")
        if expected_hash and expected_hash != actual_hash:
            raise ValueError(f"sha256 mismatch for {block['block_id']}")
        return {
            "index": block["index"],
            "block_id": block["block_id"],
            "stored_on": list(reply.stored_on),
            "sha256": actual_hash,
        }

    def _read_block(self, block: dict[str, Any]) -> bytes:
        last_error: Exception | None = None
        expected_hash = block.get("sha256")
        for address in block["nodes"]:
            try:
                data = bytearray()
                for chunk in self.datanodes.read_block(address, block["block_id"]):
                    data.extend(chunk.data)
                if expected_hash and sha256(data) != expected_hash:
                    raise ValueError(f"sha256 mismatch for {block['block_id']}")
                return bytes(data)
            except (grpc.RpcError, ValueError) as error:
                last_error = error
        raise RuntimeError(f"all replicas failed for {block['block_id']}") from last_error

    def _download_block(self, block: dict[str, Any], output: BinaryIO) -> None:
        last_error = None
        for address in block["nodes"]:
            try:
                data = bytearray()
                for chunk in self.datanodes.read_block(address, block["block_id"]):
                    data.extend(chunk.data)
                expected_hash = block.get("sha256")
                if expected_hash and sha256(data) != expected_hash:
                    raise ValueError(f"sha256 mismatch for {block['block_id']}")
                output.write(data)
                return
            except (grpc.RpcError, ValueError) as error:
                last_error = error
        raise RuntimeError(f"all replicas failed for {block['block_id']}") from last_error


def sha256(data: bytes | bytearray) -> str:
    return hashlib.sha256(data).hexdigest()
