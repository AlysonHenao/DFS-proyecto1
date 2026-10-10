import requests

from config import CONTROL_URL, REQUEST_TIMEOUT

#Clase encargada de manejar la sesión de autenticación del cliente DFS, obteniendo y almacenando un token de acceso para realizar solicitudes autenticadas al servidor de control.

class AuthSession:
    def __init__(self) -> None:
        self._token = ""

    def login(self) -> None:
        response = requests.post(
            f"{CONTROL_URL}/auth/login",
            json={"username": "demo", "password": "demo"},
            timeout=REQUEST_TIMEOUT,
        )
        response.raise_for_status()
        self._token = response.json()["access_token"]

    def headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self._token}"}
