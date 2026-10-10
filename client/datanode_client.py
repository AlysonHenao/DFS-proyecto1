from collections.abc import Iterable

import grpc

import dfsha_pb2
import dfsha_pb2_grpc

#Clase DataNodeClient proporciona métodos para interactuar con los servicios de DataNode a través de gRPC, permitiendo escribir y leer bloques de datos en el sistema distribuido.

class DataNodeClient:
    def write_block(self, address: str, block_id: str, data: bytes,chain: list[str], chunk_size: int,):

        def chunks() -> Iterable[dfsha_pb2.WriteBlockChunk]:
            yield dfsha_pb2.WriteBlockChunk(
                header=dfsha_pb2.WriteBlockHeader(block_id=block_id, chain=chain)
            )
            for offset in range(0, len(data), chunk_size):
                yield dfsha_pb2.WriteBlockChunk(data=data[offset:offset + chunk_size])

        with grpc.insecure_channel(address) as channel:
            return dfsha_pb2_grpc.DataNodeStub(channel).WriteBlock(chunks())

    def read_block(self, address: str, block_id: str):
        with grpc.insecure_channel(address) as channel:
            stream = dfsha_pb2_grpc.DataNodeStub(channel).ReadBlock(
                dfsha_pb2.ReadBlockRequest(block_id=block_id)
            )
            yield from stream
