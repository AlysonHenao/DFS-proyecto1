import os

CHUNK_SIZE = int(os.getenv("CHUNK_SIZE_BYTES", "524288"))
REQUEST_TIMEOUT = 10


def control_url() -> str:
    return os.getenv("DFSHA_CONTROL_URL", "http://localhost:8000").rstrip("/")


def tls_verify() -> bool | str:
    if os.getenv("TLS_ENABLED", "false").lower() != "true":
        return False
    path = os.getenv("TLS_CA", "")
    if not path or not os.path.isfile(path):
        raise RuntimeError(f"TLS is enabled but TLS_CA cannot be read: {path}")
    return path
