import os
import time
from collections.abc import Iterator
from pathlib import Path

# Clase BlockStorage maneja el almacenamiento de bloques en el sistema de archivos local, permitiendo guardar y leer bloques de datos en trozos (chunks) de tamaño configurable.

class BlockStorage:
    def __init__(self, data_dir: str, chunk_size: int) -> None:
        self.data_dir = data_dir
        self.chunk_size = chunk_size
        self.trash_dir = os.path.join(data_dir, "trash")
        os.makedirs(data_dir, exist_ok=True)
        os.makedirs(self.trash_dir, exist_ok=True)

    def _block_path(self, block_id: str) -> str:
        return os.path.join(self.data_dir, block_id)

    def save_block(self, block_id: str, data: bytes) -> None:
        trash_path = os.path.join(self.trash_dir, block_id)
        if os.path.exists(trash_path):
            os.replace(trash_path, self._block_path(block_id))
        with open(self._block_path(block_id), "wb") as stream:
            stream.write(data)

    def read_block_chunks(self, block_id: str) -> Iterator[bytes]:
        with open(self._block_path(block_id), "rb") as stream:
            while chunk := stream.read(self.chunk_size):
                yield chunk

    def read_block(self, block_id: str) -> bytes:
        with open(self._block_path(block_id), "rb") as stream:
            return stream.read()

    def block_ids(self) -> list[str]:
        return sorted(
            path.name
            for path in Path(self.data_dir).iterdir()
            if path.is_file()
        )

    def move_to_trash(self, block_id: str) -> bool:
        source = self._block_path(block_id)
        if not os.path.exists(source):
            return False
        os.replace(source, os.path.join(self.trash_dir, block_id))
        return True

    def purge_trash(self, retention_seconds: float) -> None:
        cutoff = time.time() - retention_seconds
        for path in Path(self.trash_dir).iterdir():
            if path.is_file() and path.stat().st_mtime <= cutoff:
                path.unlink()
