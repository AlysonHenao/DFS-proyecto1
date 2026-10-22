import os


def control_addresses_from_env() -> list[str]:
    raw = os.getenv("CONTROL_GRPC_ADDRS", "").strip()
    if not raw:
        raw = os.getenv("CONTROL_GRPC_ADDR", "")
    return [address.strip() for address in raw.split(",") if address.strip()]
