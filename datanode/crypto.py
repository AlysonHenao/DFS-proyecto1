import base64
import os

from cryptography.hazmat.primitives.ciphers.aead import AESGCM


NONCE_SIZE = 12
KEY_SIZE = 32


def _key() -> bytes:
    value = os.getenv("DATANODE_MASTER_KEY", "")
    try:
        key = base64.b64decode(value, validate=True)
    except Exception as error:
        raise ValueError("DATANODE_MASTER_KEY must be valid base64") from error
    if len(key) != KEY_SIZE:
        raise ValueError("DATANODE_MASTER_KEY must decode to exactly 32 bytes")
    return key


def encrypt(data: bytes) -> bytes:
    nonce = os.urandom(NONCE_SIZE)
    return nonce + AESGCM(_key()).encrypt(nonce, data, None)


def decrypt(payload: bytes) -> bytes:
    if len(payload) < NONCE_SIZE:
        raise ValueError("encrypted block is missing its nonce")
    nonce = payload[:NONCE_SIZE]
    try:
        return AESGCM(_key()).decrypt(nonce, payload[NONCE_SIZE:], None)
    except Exception as error:
        raise ValueError("encrypted block authentication failed") from error
