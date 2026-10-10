import os
from concurrent import futures

import grpc

import dfsha_pb2
import dfsha_pb2_grpc
from replication import BlockReplication
from service import DataNodeService
from storage import BlockStorage

DATA_DIR = os.getenv("DATANODE_DATA_DIR", "/data")
ADDRESS = os.getenv("DATANODE_ADDR", "localhost:50051")
PORT = os.getenv("DATANODE_PORT", "50051")
CHUNK_SIZE = int(os.getenv("CHUNK_SIZE_BYTES", "524288"))

#configuracion del servidor gRPC, lee variables del entorno y crea el servicio de DataNode con almacenamiento y replicación de bloques

def main():
    server = grpc.server(futures.ThreadPoolExecutor(max_workers=16))
    storage = BlockStorage(DATA_DIR, CHUNK_SIZE)
    replication = BlockReplication(CHUNK_SIZE)
    service = DataNodeService(ADDRESS, storage, replication)
    dfsha_pb2_grpc.add_DataNodeServicer_to_server(service, server)
    server.add_insecure_port(f"[::]:{PORT}")
    server.start()
    print(f"DataNode listening on {ADDRESS}", flush=True)
    server.wait_for_termination()


if __name__ == "__main__":
    main()
