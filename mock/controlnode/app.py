import math
import os
import secrets
import uuid
from typing import Any

from fastapi import FastAPI, Header, HTTPException

from models import (
    AbortRequest,
    CommitRequest,
    Credentials,
    PathRequest,
    PlanRequest,
)
from grpc_server import start_grpc_server

BLOCK_SIZE = int(os.getenv("BLOCK_SIZE_BYTES", "65536"))
REPLICATION_FACTOR = int(os.getenv("REPLICATION_FACTOR", "2"))
NODES = [x.strip() for x in os.getenv(
    "MOCK_DATANODES", "datanode1:50051,datanode2:50051"
).split(",") if x.strip()]

app = FastAPI(title="DFSha Mock ControlNode")
files: dict[str, dict[str, Any]] = {}
directories: set[str] = {"/"}
tokens: dict[str, str] = {}
grpc_server = None


def normalize_path(path: str) -> str:
    normalized = "/" + "/".join(part for part in path.split("/") if part)
    return normalized if normalized != "" else "/"


def require_parent(path: str) -> None:
    parent = path.rsplit("/", 1)[0] or "/"
    if parent not in directories:
        raise HTTPException(status_code=404, detail="parent directory not found")


def check_token(token: str | None) -> None:
    if not token or token not in tokens:
        raise HTTPException(status_code=401, detail="invalid token")


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.on_event("startup")
def start_internal_grpc() -> None:
    global grpc_server
    grpc_server = start_grpc_server()


@app.on_event("shutdown")
def stop_internal_grpc() -> None:
    if grpc_server is not None:
        grpc_server.stop(grace=1)


@app.post("/auth/login")
def login(body: Credentials) -> dict[str, Any]:
    token = secrets.token_urlsafe(24)
    tokens[token] = body.username
    return {"access_token": token, "token_type": "bearer", "expires_in": 3600}


@app.post("/fs/mkdir", status_code=201)
def mkdir(
    body: PathRequest,
    authorization: str | None = Header(default=None),
) -> dict[str, str]:
    check_token(authorization.removeprefix("Bearer ").strip() if authorization else None)
    path = normalize_path(body.path)
    if path == "/":
        raise HTTPException(status_code=409, detail="directory already exists")
    if path in directories or path in files:
        raise HTTPException(status_code=409, detail="path already exists")
    require_parent(path)
    directories.add(path)
    return {"path": path, "status": "created"}


@app.get("/fs/ls")
def list_directory(
    path: str = "/",
    authorization: str | None = Header(default=None),
) -> dict[str, Any]:
    check_token(authorization.removeprefix("Bearer ").strip() if authorization else None)
    path = normalize_path(path)
    if path not in directories:
        raise HTTPException(status_code=404, detail="directory not found")
    prefix = path.rstrip("/") + "/"
    entries: list[dict[str, Any]] = []
    for directory in sorted(directories):
        if directory != path and directory.startswith(prefix) and "/" not in directory[len(prefix):]:
            entries.append({"name": directory[len(prefix):], "type": "dir", "size": 0})
    for file_path, record in sorted(files.items()):
        if record["committed"] and file_path.startswith(prefix) and "/" not in file_path[len(prefix):]:
            entries.append({
                "name": file_path[len(prefix):],
                "type": "file",
                "size": record["size"],
            })
    return {"path": path, "entries": entries}


@app.delete("/fs/rmdir", status_code=204)
def remove_directory(
    path: str,
    authorization: str | None = Header(default=None),
) -> None:
    check_token(authorization.removeprefix("Bearer ").strip() if authorization else None)
    path = normalize_path(path)
    if path == "/" or path not in directories:
        raise HTTPException(status_code=404, detail="directory not found")
    prefix = path.rstrip("/") + "/"
    if any(item.startswith(prefix) for item in directories | set(files)):
        raise HTTPException(status_code=409, detail="directory not empty")
    directories.remove(path)


@app.delete("/fs/file", status_code=204)
def remove_file(
    path: str,
    authorization: str | None = Header(default=None),
) -> None:
    check_token(authorization.removeprefix("Bearer ").strip() if authorization else None)
    path = normalize_path(path)
    if path not in files or not files[path]["committed"]:
        raise HTTPException(status_code=404, detail="file not found")
    del files[path]


@app.post("/files/put/plan")
def put_plan(
    body: PlanRequest,
    authorization: str | None = Header(default=None),
) -> dict[str, Any]:
    check_token(authorization.removeprefix("Bearer ").strip() if authorization else None)
    body.path = normalize_path(body.path)
    if body.path in files:
        raise HTTPException(status_code=409, detail="path already exists")
    require_parent(body.path)
    if body.size < 0 or len(NODES) < REPLICATION_FACTOR:
        raise HTTPException(status_code=503, detail="not enough DataNodes")
    count = max(1, math.ceil(body.size / BLOCK_SIZE))
    blocks = []
    for index in range(count):
        start = index * BLOCK_SIZE
        size = min(BLOCK_SIZE, max(0, body.size - start))
        if body.size == 0:
            size = 0
        block_id = str(uuid.uuid4())
        chain = NODES[:REPLICATION_FACTOR]
        blocks.append({"index": index, "block_id": block_id, "size": size, "chain": chain})
    files[body.path] = {"size": body.size, "blocks": blocks, "committed": False}
    return {"block_size": BLOCK_SIZE, "blocks": blocks}


@app.post("/files/put/commit")
def put_commit(
    body: CommitRequest,
    authorization: str | None = Header(default=None),
) -> dict[str, Any]:
    check_token(authorization.removeprefix("Bearer ").strip() if authorization else None)
    record = files.get(body.path)
    if not record:
        raise HTTPException(status_code=404, detail="path not found")
    expected = {block["block_id"] for block in record["blocks"]}
    received = {block.block_id for block in body.blocks}
    if expected != received or any(len(block.stored_on) < REPLICATION_FACTOR for block in body.blocks):
        raise HTTPException(status_code=422, detail="incomplete block acknowledgements")
    record["committed"] = True
    return {"status": "ready", "path": body.path}


@app.post("/files/put/abort")
def put_abort(
    body: AbortRequest,
    authorization: str | None = Header(default=None),
) -> dict[str, str]:
    check_token(authorization.removeprefix("Bearer ").strip() if authorization else None)
    files.pop(body.path, None)
    return {"status": "aborted"}


@app.get("/files/get/plan")
def get_plan(
    path: str,
    authorization: str | None = Header(default=None),
) -> dict[str, Any]:
    check_token(authorization.removeprefix("Bearer ").strip() if authorization else None)
    path = normalize_path(path)
    record = files.get(path)
    if not record or not record["committed"]:
        raise HTTPException(status_code=404, detail="file not found")
    return {
        "size": record["size"],
        "block_size": BLOCK_SIZE,
        "blocks": [{"index": b["index"], "block_id": b["block_id"],
                    "size": b["size"], "nodes": b["chain"]}
                   for b in record["blocks"]],
    }
