from collections.abc import Iterable

import dfsha_pb2

# Funciones auxiliares para manejar la recepción de solicitudes de escritura de bloques y la construcción de trozos (chunks) de datos para enviar a través de gRPC.

def receive_write_request(request_iterator) -> tuple[object | None, bytes]:
    header = None
    payload = bytearray()
    for request in request_iterator:
        if request.HasField("header"):
            header = request.header
        elif request.HasField("data"):
            payload.extend(request.data)
    return header, bytes(payload)


def build_write_chunks(
    block_id: str,
    data: bytes,
    chunk_size: int,
) -> Iterable[dfsha_pb2.WriteBlockChunk]:
    yield dfsha_pb2.WriteBlockChunk(
        header=dfsha_pb2.WriteBlockHeader(block_id=block_id)
    )
    for offset in range(0, len(data), chunk_size):
        yield dfsha_pb2.WriteBlockChunk(data=data[offset:offset + chunk_size])

