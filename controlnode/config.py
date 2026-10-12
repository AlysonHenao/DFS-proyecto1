import os
from pathlib import Path

BLOCK_SIZE_BYTES = int(os.getenv("BLOCK_SIZE_BYTES", "65536" if os.getenv("DEV_MODE") == "1" else "8388608"))
REPLICATION_FACTOR = int(os.getenv("REPLICATION_FACTOR", "2"))
MIN_WRITE_ACKS = int(os.getenv("MIN_WRITE_ACKS", "2"))
HEARTBEAT_INTERVAL_S = float(os.getenv("HEARTBEAT_INTERVAL_S", "5"))
DEAD_TIMEOUT_S = float(os.getenv("DEAD_TIMEOUT_S", "15"))

JWT_SECRET = os.getenv("JWT_SECRET", "change-me-jwt-secret-for-dfsha")
JWT_EXPIRE_MIN = int(os.getenv("JWT_EXPIRE_MIN", "60"))
CLUSTER_API_KEY = os.getenv("CLUSTER_API_KEY", "change-me-cluster-api-key")

CONTROLNODE_ID = os.getenv("CONTROLNODE_ID", "control-leader")
CONTROLNODE_ROLE = os.getenv("CONTROLNODE_ROLE", "leader").strip().lower()
CONTROL_REST_PORT = int(os.getenv("CONTROL_REST_PORT", "8000"))
CONTROL_GRPC_PORT = os.getenv("CONTROL_GRPC_PORT", "50050")

DB_PATH = os.getenv("DB_PATH", "/data/meta.db")
SCHEMA_PATH = os.getenv("SCHEMA_PATH", str(Path(__file__).parent / "schema.sql"))
CONTROL_PEER_GRPC_ADDR = os.getenv("CONTROL_PEER_GRPC_ADDR", "")
CONTROL_LEADER_URL = os.getenv("CONTROL_LEADER_URL", "http://control-leader:8000")
