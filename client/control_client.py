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

    def register(self, username: str, password: str) -> dict[str, str]:
        response = requests.post(
            f"{control_url()}/auth/register",
            json={"username": username, "password": password},
            timeout=REQUEST_TIMEOUT,
            verify=tls_verify(),
        )
        if response.status_code == 503:
            raise RuntimeError(
                "El ControlNode no es leader; actualiza DFSHA_CONTROL_URL"
            )
        response.raise_for_status()
        return response.json()

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

    def open_file(self, path: str, mode: str = "r", append: bool = False) -> dict[str, Any]:
        return self.request(
            "POST",
            "/files/open",
            json={"path": path, "mode": mode, "append": append},
        ).json()

    def close_file(
        self, session_id: str, blocks: list[dict[str, Any]] | None = None
    ) -> dict[str, Any]:
        body: dict[str, Any] = {"session_id": session_id}
        if blocks is not None:
            body["blocks"] = blocks
        return self.request("POST", "/files/close", json=body).json()

    def lock_file(self, session_id: str, lease_seconds: int | None = None) -> dict[str, Any]:
        body: dict[str, Any] = {"session_id": session_id}
        if lease_seconds is not None:
            body["lease_seconds"] = lease_seconds
        return self.request("POST", "/files/lock", json=body).json()

    def unlock_file(self, session_id: str) -> None:
        self.request("POST", "/files/unlock", json={"session_id": session_id})

    def renew_lease(self, session_id: str, lease_seconds: int | None = None) -> dict[str, Any]:
        body: dict[str, Any] = {"session_id": session_id}
        if lease_seconds is not None:
            body["lease_seconds"] = lease_seconds
        return self.request("POST", "/files/lock/renew", json=body).json()

    def plan_read(
        self, session_id: str, offset: int = 0, length: int | None = None
    ) -> dict[str, Any]:
        params: dict[str, Any] = {"session_id": session_id, "offset": offset}
        if length is not None:
            params["length"] = length
        return self.request("GET", "/files/read/plan", params=params).json()

    def plan_write(
        self, session_id: str, offset: int, length: int, append: bool = False
    ) -> dict[str, Any]:
        return self.request(
            "POST",
            "/files/write/plan",
            json={
                "session_id": session_id,
                "offset": offset,
                "length": length,
                "append": append,
            },
        ).json()

    def write_file(self, session_id: str, offset: int, data: str) -> dict[str, Any]:
        """Write raw data to an opened session.
        The data is sent as a UTF‑8 string; the server will store the bytes.
        """
        return self.request(
            "POST",
            "/files/write",
            json={
                "session_id": session_id,
                "offset": offset,
                "data": data,
            },
        ).json()
