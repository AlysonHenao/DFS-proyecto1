import requests

from config import REQUEST_TIMEOUT, control_url, tls_verify

#Clase encargada de manejar la sesión de autenticación del cliente DFS, obteniendo y almacenando un token de acceso para realizar solicitudes autenticadas al servidor de control.

class AuthSession:
    def __init__(self) -> None:
        self._token = ""

    def login(self) -> None:
        response = requests.post(
            f"{control_url()}/auth/login",
            json={"username": "demo", "password": "demo"},
            timeout=REQUEST_TIMEOUT,
            verify=tls_verify(),
        )
        if response.status_code == 503:
            raise RuntimeError(
                "El ControlNode no es leader; actualiza DFSHA_CONTROL_URL"
            )
        response.raise_for_status()
        self._token = response.json()["access_token"]

    def headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self._token}"}
