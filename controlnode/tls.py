import os

import grpc


def enabled() -> bool:
    return os.getenv("TLS_ENABLED", "false").lower() == "true"


def _read(path: str, label: str) -> bytes:
    if not path:
        raise RuntimeError(f"TLS is enabled but {label} is not configured")
    try:
        with open(path, "rb") as stream:
            return stream.read()
    except OSError as error:
        raise RuntimeError(f"TLS is enabled but {label} cannot be read: {path}") from error


def channel_credentials() -> grpc.ChannelCredentials | None:
    if not enabled():
        return None
    return grpc.ssl_channel_credentials(_read(os.getenv("TLS_CA", ""), "TLS_CA"))


def server_credentials() -> grpc.ServerCredentials | None:
    if not enabled():
        return None
    certificate = _read(os.getenv("TLS_CERT", ""), "TLS_CERT")
    key = _read(os.getenv("TLS_KEY", ""), "TLS_KEY")
    return grpc.ssl_server_credentials(((key, certificate),))


def channel(address: str):
    credentials = channel_credentials()
    return grpc.secure_channel(address, credentials) if credentials else grpc.insecure_channel(address)
