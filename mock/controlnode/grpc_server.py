from concurrent import futures
import logging
import os
import threading

import grpc

import dfsha_pb2
import dfsha_pb2_grpc

LOGGER = logging.getLogger(__name__)
nodes: dict[str, dfsha_pb2.HeartbeatRequest] = {}
pending_commands: list[dfsha_pb2.Command] = []


class MockControlNode(dfsha_pb2_grpc.ControlNodeInternalServicer):
    def Heartbeat(self, request, context):
        nodes[request.node_id] = request
        commands = list(pending_commands)
        pending_commands.clear()
        return dfsha_pb2.HeartbeatReply(commands=commands)


def enqueue_command(command_type, block_id: str, target_address: str = "") -> None:
    pending_commands.append(
        dfsha_pb2.Command(
            type=command_type,
            block_id=block_id,
            target_address=target_address,
        )
    )


def start_grpc_server() -> grpc.Server:
    server = grpc.server(futures.ThreadPoolExecutor(max_workers=8))
    dfsha_pb2_grpc.add_ControlNodeInternalServicer_to_server(
        MockControlNode(), server
    )
    server.add_insecure_port("[::]:" + os.getenv("CONTROL_GRPC_PORT", "50050"))
    server.start()
    return server
