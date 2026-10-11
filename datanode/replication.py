import grpc

import dfsha_pb2
import dfsha_pb2_grpc

from chunks import build_write_chunks


class BlockReplication:
    def __init__(self, chunk_size: int) -> None:
        self.chunk_size = chunk_size

    def replicate(
        self,
        block_id: str,
        data: bytes,
        targets,
    ) -> list[str]:
        stored_on: list[str] = []
        for target in targets:
            with grpc.insecure_channel(target) as channel:
                stub = dfsha_pb2_grpc.DataNodeStub(channel)
                reply = stub.WriteBlock(
                    build_write_chunks(block_id, data, self.chunk_size)
                )
            if not reply.ok:
                raise RuntimeError(reply.error)
            stored_on.extend(reply.stored_on)
        return stored_on
