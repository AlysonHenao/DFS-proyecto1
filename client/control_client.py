from typing import Any

import requests

from auth import AuthSession
from config import REQUEST_TIMEOUT, control_url, tls_verify

#Clase ControlClient maneja las operaciones de control del cliente DFS, incluyendo la
# planificación y confirmación de cargas y descargas de archivos, así como la gestión
#  del sistema de archivos remoto (crear directorios, listar contenido, eliminar archivos y directorios)
#  mediante solicitudes HTTP autenticadas al servidor de control.

class ControlClient:
    def __init__(self, auth: AuthSession) -> None:
        self.auth = auth

    def request(self, method: str, path: str, **kwargs) -> requests.Response:
        response = requests.request(
            method,
            f"{control_url()}{path}",
            headers=self.auth.headers(),
            timeout=REQUEST_TIMEOUT,
            verify=tls_verify(),
            **kwargs,
        )
        if response.status_code == 503:
            raise RuntimeError(
                "El ControlNode no es leader; actualiza DFSHA_CONTROL_URL"
            )
        response.raise_for_status()
        return response

    def plan_upload(self, path: str, size: int) -> dict[str, Any]:
        return self.request(
            "POST", "/files/put/plan", json={"path": path, "size": size}
        ).json()

    def commit_upload(self, path: str, blocks: list[dict[str, Any]]) -> None:
        self.request("POST", "/files/put/commit", json={"path": path, "blocks": blocks})

    def abort_upload(self, path: str) -> None:
        self.request("POST", "/files/put/abort", json={"path": path})

    def plan_download(self, path: str) -> dict[str, Any]:
        return self.request("GET", "/files/get/plan", params={"path": path}).json()

    def mkdir(self, path: str) -> None:
        self.request("POST", "/fs/mkdir", json={"path": path})

    def ls(self, path: str = "/") -> list[dict[str, Any]]:
        return self.request("GET", "/fs/ls", params={"path": path}).json()["entries"]

    def remove_file(self, path: str) -> None:
        self.request("DELETE", "/fs/file", params={"path": path})

    def remove_directory(self, path: str) -> None:
        self.request("DELETE", "/fs/rmdir", params={"path": path})
