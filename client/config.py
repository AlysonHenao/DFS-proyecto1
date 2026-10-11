import os

CHUNK_SIZE = int(os.getenv("CHUNK_SIZE_BYTES", "524288"))
REQUEST_TIMEOUT = 10


def control_url() -> str:
    return os.getenv("DFSHA_CONTROL_URL", "http://localhost:8000").rstrip("/")
