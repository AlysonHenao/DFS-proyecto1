from __future__ import annotations

import os
from typing import TYPE_CHECKING, Any

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

    def _download_block(self, block: dict[str, Any], output) -> None:
        last_error = None
        for address in block["nodes"]:
            try:
                data = bytearray()
                for chunk in self.datanodes.read_block(address, block["block_id"]):
                    data.extend(chunk.data)
                output.write(data)
                return
            except (grpc.RpcError, ValueError) as error:
                last_error = error
        raise RuntimeError(f"all replicas failed for {block['block_id']}") from last_error
