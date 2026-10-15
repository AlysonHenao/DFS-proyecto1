import logging
import os
import threading
import time
from shutil import disk_usage

import grpc

import dfsha_pb2
import dfsha_pb2_grpc
from chunks import build_write_chunks
from config import control_addresses_from_env
from tls import channel
from storage import BlockStorage

LOGGER = logging.getLogger(__name__)


class HeartbeatCommandExecutor:
    def __init__(self, storage: BlockStorage, chunk_size: int, api_key: str) -> None:
        self.storage = storage
        self.chunk_size = chunk_size
        self.api_key = api_key

    def execute(self, command) -> None:
        try:
            if command.type == dfsha_pb2.Command.DELETE:
                self.storage.move_to_trash(command.block_id)
            elif command.type == dfsha_pb2.Command.REPLICATE:
                self._replicate(command.block_id, command.target_address)
        except (OSError, grpc.RpcError, RuntimeError) as error:
            LOGGER.warning("Heartbeat command failed for %s: %s", command.block_id, error)

    def _replicate(self, block_id: str, target: str) -> None:
        data = self.storage.read_block(block_id)
        metadata = (("x-api-key", self.api_key),) if self.api_key else ()
        with channel(target) as grpc_channel:
            reply = dfsha_pb2_grpc.DataNodeStub(grpc_channel).WriteBlock(
                build_write_chunks(block_id, data, self.chunk_size),
                metadata=metadata,
                timeout=5,
            )
        if not reply.ok:
            raise RuntimeError(reply.error)


class HeartbeatRunner:
    def __init__(
        self,
        node_id: str,
        address: str,
        control_addresses: list[str],
        storage: BlockStorage,
        interval: float,
        retention: float,
        api_key: str,
    ) -> None:
        self.node_id = node_id
        self.address = address
        self.control_addresses = control_addresses
        self.storage = storage
        self.interval = interval
        self.retention = retention
        self.api_key = api_key
        self.executor = HeartbeatCommandExecutor(storage, storage.chunk_size, api_key)
        self.stop_event = threading.Event()
        self.thread = threading.Thread(target=self._run, name="heartbeat", daemon=True)

    def start(self) -> None:
        self.thread.start()

    def stop(self) -> None:
        self.stop_event.set()
        self.thread.join(timeout=2)

    def _run(self) -> None:
        while not self.stop_event.is_set():
            self.send_once()
            self.stop_event.wait(self.interval)

    def send_once(self) -> None:
        total, used, free = disk_usage(self.storage.data_dir)
        request = dfsha_pb2.HeartbeatRequest(
            node_id=self.node_id,
            address=self.address,
            free_bytes=free,
            total_bytes=total,
            block_ids=self.storage.block_ids(),
        )
        metadata = (("x-api-key", self.api_key),) if self.api_key else ()
        self.storage.purge_trash(self.retention)
        for address in self.control_addresses:
            try:
                with channel(address) as grpc_channel:
                    reply = dfsha_pb2_grpc.ControlNodeInternalStub(grpc_channel).Heartbeat(
                        request, metadata=metadata, timeout=2
                    )
                LOGGER.info(
                    "Heartbeat sent successfully to %s: node=%s blocks=%d commands=%d",
                    address,
                    self.node_id,
                    len(request.block_ids),
                    len(reply.commands),
                )
                for command in reply.commands:
                    self.executor.execute(command)
            except grpc.RpcError as error:
                LOGGER.warning("Heartbeat to %s failed: %s", address, error)
            except OSError as error:
                LOGGER.warning("Heartbeat storage check failed: %s", error)
