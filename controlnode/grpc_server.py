from collections import defaultdict
from concurrent import futures
import logging
import threading
import time
from typing import Any

import grpc

from config import CLUSTER_API_KEY, CONTROL_GRPC_PORT, CONTROLNODE_ROLE
import db
import dfsha_pb2
import dfsha_pb2_grpc
from tls import server_credentials

LOGGER = logging.getLogger("uvicorn.error")

_COMMANDS_LOCK = threading.Lock()
_PENDING_COMMANDS: dict[str, list[dfsha_pb2.Command]] = defaultdict(list)


def enqueue_command_for_node(node_id: str, command: dfsha_pb2.Command) -> None:
    with _COMMANDS_LOCK:
        _PENDING_COMMANDS[node_id].append(command)


def pop_commands_for_node(node_id: str) -> list[dfsha_pb2.Command]:
    with _COMMANDS_LOCK:
        if node_id in _PENDING_COMMANDS:
            cmds = _PENDING_COMMANDS[node_id]
            del _PENDING_COMMANDS[node_id]
            return cmds
        return []


def verify_api_key(context: grpc.ServicerContext) -> None:
    if not CLUSTER_API_KEY:
        return
    metadata = dict(context.invocation_metadata())
    api_key = metadata.get("x-api-key")
    if api_key != CLUSTER_API_KEY:
        context.abort(grpc.StatusCode.UNAUTHENTICATED, "invalid cluster api key")


class ControlNodeInternalService(dfsha_pb2_grpc.ControlNodeInternalServicer):
    def Heartbeat(self, request: dfsha_pb2.HeartbeatRequest, context: grpc.ServicerContext) -> dfsha_pb2.HeartbeatReply:
        verify_api_key(context)

        # Upsert DataNode status and capacity
        db.upsert_node(
            node_id=request.node_id,
            address=request.address,
            free_bytes=request.free_bytes,
            total_bytes=request.total_bytes,
        )

        # Follower ControlNode does NOT issue commands to DataNodes
        if CONTROLNODE_ROLE != "leader":
            LOGGER.info(
                "Heartbeat received from %s (%s): blocks=%d commands=0 role=follower",
                request.node_id,
                request.address,
                len(request.block_ids),
            )
            return dfsha_pb2.HeartbeatReply(commands=[])

        commands: list[dfsha_pb2.Command] = []

        # 1. Check for orphaned blocks reported by this DataNode
        orphans = db.get_orphan_blocks_for_node(list(request.block_ids))
        for orphan_id in orphans:
            commands.append(
                dfsha_pb2.Command(
                    type=dfsha_pb2.Command.DELETE,
                    block_id=orphan_id,
                )
            )

        # 2. Add queued commands (e.g. REPLICATE)
        queued = pop_commands_for_node(request.node_id)
        commands.extend(queued)

        LOGGER.info(
            "Heartbeat received from %s (%s): blocks=%d commands=%d role=leader",
            request.node_id,
            request.address,
            len(request.block_ids),
            len(commands),
        )
        return dfsha_pb2.HeartbeatReply(commands=commands)

    def ReplicateMetadata(self, request: dfsha_pb2.MetadataSnapshot, context: grpc.ServicerContext) -> dfsha_pb2.ReplicationReply:
        verify_api_key(context)

        if CONTROLNODE_ROLE != "follower":
            return dfsha_pb2.ReplicationReply(
                ok=False,
                error="Only follower ControlNode accepts incoming metadata snapshots",
            )

        try:
            db.restore_from_snapshot_bytes(request.sqlite_snapshot)
            LOGGER.info("Successfully received and restored snapshot generated at %s", request.generated_at)
            return dfsha_pb2.ReplicationReply(ok=True)
        except Exception as e:
            LOGGER.error("Failed to restore metadata snapshot: %s", e)
            return dfsha_pb2.ReplicationReply(ok=False, error=str(e))


def start_grpc_server() -> grpc.Server:
    server = grpc.server(futures.ThreadPoolExecutor(max_workers=8))
    dfsha_pb2_grpc.add_ControlNodeInternalServicer_to_server(
        ControlNodeInternalService(), server
    )
    port = str(CONTROL_GRPC_PORT)
    credentials = server_credentials()
    if credentials:
        server.add_secure_port(f"[::]:{port}", credentials)
    else:
        server.add_insecure_port(f"[::]:{port}")
    server.start()
    LOGGER.info("ControlNode Internal gRPC server listening on port %s", port)
    return server
