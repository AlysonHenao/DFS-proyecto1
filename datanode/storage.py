import os
from collections.abc import Iterator

# Clase BlockStorage maneja el almacenamiento de bloques en el sistema de archivos local, permitiendo guardar y leer bloques de datos en trozos (chunks) de tamaño configurable.

class BlockStorage:
    def __init__(self, data_dir: str, chunk_size: int) -> None:
        self.data_dir = data_dir
        self.chunk_size = chunk_size
        os.makedirs(data_dir, exist_ok=True)

    def _block_path(self, block_id: str) -> str:
        return os.path.join(self.data_dir, block_id)

    def save_block(self, block_id: str, data: bytes) -> None:
        with open(self._block_path(block_id), "wb") as stream:
            stream.write(data)

    def read_block_chunks(self, block_id: str) -> Iterator[bytes]:
        with open(self._block_path(block_id), "rb") as stream:
            while chunk := stream.read(self.chunk_size):
                yield chunk

