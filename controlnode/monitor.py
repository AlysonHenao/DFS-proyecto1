import logging
import threading
import time

import grpc

from config import (
    CLUSTER_API_KEY,
    CONTROL_PEER_GRPC_ADDR,
    CONTROLNODE_ROLE,
    DEAD_TIMEOUT_S,
    HEARTBEAT_INTERVAL_S,
    REPLICATION_FACTOR,
)
import db
import dfsha_pb2
import dfsha_pb2_grpc
from grpc_server import enqueue_command_for_node
from tls import channel

LOGGER = logging.getLogger(__name__)


class ClusterMonitor:
    def __init__(self) -> None:
        self.stop_event = threading.Event()
        self.thread = threading.Thread(target=self._run, name="cluster-monitor", daemon=True)

    def start(self) -> None:
        self.thread.start()
        LOGGER.info("Cluster monitor started (role: %s)", CONTROLNODE_ROLE)

    def stop(self) -> None:
        self.stop_event.set()
        self.thread.join(timeout=2)
        LOGGER.info("Cluster monitor stopped")

    def _run(self) -> None:
        while not self.stop_event.is_set():
            try:
                if CONTROLNODE_ROLE == "leader":
                    self._check_cluster_health()
                    self._replicate_metadata_snapshot()
            except Exception as e:
                LOGGER.error("Error in cluster monitor loop: %s", e)

            self.stop_event.wait(HEARTBEAT_INTERVAL_S)

    def _check_cluster_health(self) -> None:
        # 1. Mark dead nodes
        dead_nodes = db.mark_dead_nodes(DEAD_TIMEOUT_S)

        # 2. Check for under-replicated blocks
        alive_nodes = db.get_alive_nodes()
        if len(alive_nodes) < REPLICATION_FACTOR:
            return

        under_replicated = db.get_under_replicated_blocks(REPLICATION_FACTOR)
        for item in under_replicated:
            block_id = item["block_id"]
            current_addrs = set(item["alive_addresses"])

            # Find target alive node that does not have this block
            eligible_targets = [n for n in alive_nodes if n["address"] not in current_addrs]
            if not eligible_targets:
                continue

            target_node = eligible_targets[0]  # highest free_bytes

            # Pick a source node that holds this replica
            source_candidates = [n for n in alive_nodes if n["address"] in current_addrs]
            if not source_candidates:
                continue

            source_node = source_candidates[0]

            cmd = dfsha_pb2.Command(
                type=dfsha_pb2.Command.REPLICATE,
                block_id=block_id,
                target_address=target_node["address"],
            )
            enqueue_command_for_node(source_node["node_id"], cmd)
            LOGGER.info(
                "Enqueued REPLICATE for block %s from %s to %s",
                block_id,
                source_node["node_id"],
                target_node["address"],
            )

    def _replicate_metadata_snapshot(self) -> None:
        if not CONTROL_PEER_GRPC_ADDR:
            return

        try:
            snapshot_bytes = db.create_snapshot_bytes()
            metadata = (("x-api-key", CLUSTER_API_KEY),) if CLUSTER_API_KEY else ()
            with channel(CONTROL_PEER_GRPC_ADDR) as grpc_channel:
                stub = dfsha_pb2_grpc.ControlNodeInternalStub(grpc_channel)
                reply = stub.ReplicateMetadata(
                    dfsha_pb2.MetadataSnapshot(
                        sqlite_snapshot=snapshot_bytes,
                        generated_at=int(time.time()),
                    ),
                    metadata=metadata,
                    timeout=3,
                )
                if not reply.ok:
                    LOGGER.warning("Peer follower rejected metadata snapshot: %s", reply.error)
        except grpc.RpcError as rpc_err:
            # Follower may be offline or starting up; log debug/warning
            LOGGER.debug("Snapshot replication to %s failed (peer possibly offline): %s", CONTROL_PEER_GRPC_ADDR, rpc_err)
        except Exception as e:
            LOGGER.warning("Metadata snapshot creation/push failed: %s", e)
