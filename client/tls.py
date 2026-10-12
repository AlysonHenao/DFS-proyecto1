import os


def verify() -> bool | str:
    if os.getenv("TLS_ENABLED", "false").lower() != "true":
        return False
    path = os.getenv("TLS_CA", "")
    if not path or not os.path.isfile(path):
        raise RuntimeError(f"TLS is enabled but TLS_CA cannot be read: {path}")
    return path


def channel(address: str):
    import grpc

    if os.getenv("TLS_ENABLED", "false").lower() != "true":
        return grpc.insecure_channel(address)
    path = verify()
    with open(path, "rb") as stream:
        credentials = grpc.ssl_channel_credentials(stream.read())
    return grpc.secure_channel(address, credentials)
