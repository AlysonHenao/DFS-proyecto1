import os

CONTROL_URL = os.getenv("DFSHA_CONTROL_URL", "http://localhost:8000")
CHUNK_SIZE = int(os.getenv("CHUNK_SIZE_BYTES", "524288"))
REQUEST_TIMEOUT = 10
