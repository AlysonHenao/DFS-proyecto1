import getpass
import json
import os

import requests

from config import REQUEST_TIMEOUT, control_url, session_file, tls_verify


class AuthSession:
    def __init__(self) -> None:
        self._token = ""

    @staticmethod
    def credentials(
        username: str | None = None,
        password: str | None = None,
        confirm: bool = False,
    ) -> tuple[str, str]:
        username = username or os.getenv("DFSHA_USERNAME") or input("DFSha username: ")
        supplied_password = password or os.getenv("DFSHA_PASSWORD")
        password = supplied_password or None
        if password is None:
            password = getpass.getpass("DFSha password: ")
        if confirm and supplied_password is None and password != getpass.getpass(
            "Confirm password: "
        ):
            raise ValueError("passwords do not match")
        return username, password

    def login(self, username: str | None = None, password: str | None = None) -> None:
        username, password = self.credentials(username, password)
        response = requests.post(
            f"{control_url()}/auth/login",
            json={"username": username, "password": password},
            timeout=REQUEST_TIMEOUT,
            verify=tls_verify(),
        )
        if response.status_code == 503:
            raise RuntimeError(
                "El ControlNode no es leader; actualiza DFSHA_CONTROL_URL"
            )
        response.raise_for_status()
        self._token = response.json()["access_token"]
        self._save(username)

    def load(self) -> bool:
        try:
            with open(session_file(), encoding="utf-8") as stream:
                session = json.load(stream)
        except (FileNotFoundError, OSError, json.JSONDecodeError):
            return False
        token = session.get("access_token")
        if not isinstance(token, str) or not token:
            return False
        self._token = token
        return True

    def _save(self, username: str) -> None:
        path = session_file()
        directory = os.path.dirname(path)
        if directory:
            os.makedirs(directory, exist_ok=True)
        with open(path, "w", encoding="utf-8") as stream:
            json.dump({"username": username, "access_token": self._token}, stream)
        try:
            os.chmod(path, 0o600)
        except OSError:
            pass

    def headers(self) -> dict[str, str]:
        if not self._token:
            raise RuntimeError("No hay una sesión activa; ejecuta primero `login`")
        return {"Authorization": f"Bearer {self._token}"}
