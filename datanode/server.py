import os
import logging
from concurrent import futures

import grpc

import dfsha_pb2
import dfsha_pb2_grpc
from config import control_addresses_from_env
from heartbeat import HeartbeatRunner
from replication import BlockReplication
from service import DataNodeService
from storage import BlockStorage
from tls import server_credentials

logging.basicConfig(
    level=os.getenv("LOG_LEVEL", "INFO").upper(),
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)

DATA_DIR = os.getenv("DATANODE_DATA_DIR", "/data")
ADDRESS = os.getenv("DATANODE_ADDR", "localhost:50051")
PORT = os.getenv("DATANODE_PORT", "50051")
CHUNK_SIZE = int(os.getenv("CHUNK_SIZE_BYTES", "524288"))
HEARTBEAT_INTERVAL = float(os.getenv("HEARTBEAT_INTERVAL_S", "5"))
TRASH_RETENTION = float(os.getenv("TRASH_RETENTION_S", "600"))
API_KEY = os.getenv("CLUSTER_API_KEY", "")

#configuracion del servidor gRPC, lee variables del entorno y crea el servicio de DataNode con almacenamiento y replicación de bloques

def main():
    server = grpc.server(futures.ThreadPoolExecutor(max_workers=16))
    storage = BlockStorage(DATA_DIR, CHUNK_SIZE)
    replication = BlockReplication(CHUNK_SIZE)
    service = DataNodeService(ADDRESS, storage, replication)
    dfsha_pb2_grpc.add_DataNodeServicer_to_server(service, server)
    credentials = server_credentials()
    if credentials:
        server.add_secure_port(f"[::]:{PORT}", credentials)
    else:
        server.add_insecure_port(f"[::]:{PORT}")
    server.start()
    heartbeat = HeartbeatRunner(
        os.getenv("DATANODE_ID", "dn1"),
        ADDRESS,
        control_addresses_from_env(),
        storage,
        HEARTBEAT_INTERVAL,
        TRASH_RETENTION,
        API_KEY,
    )
    heartbeat.start()
    print(f"DataNode listening on {ADDRESS}", flush=True)
    try:
        server.wait_for_termination()
    finally:
        heartbeat.stop()


if __name__ == "__main__":
    main()
