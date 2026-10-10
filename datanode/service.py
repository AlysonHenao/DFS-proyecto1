import grpc

import dfsha_pb2
import dfsha_pb2_grpc

from chunks import receive_write_request
from replication import BlockReplication
from storage import BlockStorage

#Servicio de DataNode mantiene los RPC públicos para escribir y leer bloques, delegando el almacenamiento y la replicación a las clases BlockStorage y BlockReplication.

class DataNodeService(dfsha_pb2_grpc.DataNodeServicer):
    def __init__(
        self,
        address: str,
        storage: BlockStorage,
        replication: BlockReplication,
    ) -> None:
        self.address = address
        self.storage = storage
        self.replication = replication

    def WriteBlock(self, request_iterator, context):
        try:
            header, data = receive_write_request(request_iterator)
            if header is None:
                return dfsha_pb2.WriteBlockReply(ok=False, error="missing header")

            self.storage.save_block(header.block_id, data)
            stored_on = [self.address]
            stored_on.extend(
                self.replication.replicate(header.block_id, data, header.chain)
            )
            return dfsha_pb2.WriteBlockReply(ok=True, stored_on=stored_on)
        except (OSError, RuntimeError) as error:
            return dfsha_pb2.WriteBlockReply(ok=False, error=str(error))

    def ReadBlock(self, request, context):
        try:
            for chunk in self.storage.read_block_chunks(request.block_id):
                yield dfsha_pb2.BlockChunk(data=chunk)
        except FileNotFoundError:
            context.abort(grpc.StatusCode.NOT_FOUND, "block not found")

