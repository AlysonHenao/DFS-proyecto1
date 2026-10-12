import math
import uuid
from typing import Any

from fastapi import Depends, FastAPI, Header, HTTPException, Request
from fastapi.responses import JSONResponse

from auth import create_access_token, get_current_user, hash_password, verify_password
from config import (
    BLOCK_SIZE_BYTES,
    CONTROLNODE_ID,
    CONTROLNODE_ROLE,
    MIN_WRITE_ACKS,
    REPLICATION_FACTOR,
)
import db
from grpc_server import start_grpc_server
from models import (
    AbortRequest,
    CommitRequest,
    Credentials,
    PathRequest,
    PlanRequest,
)
from monitor import ClusterMonitor

app = FastAPI(title="DFSha ControlNode", version="1.0.0")

_grpc_server = None
_cluster_monitor = None


@app.middleware("http")
async def role_guard_middleware(request: Request, call_next):
    # Follower rejects all requests except /health with 503
    if CONTROLNODE_ROLE == "follower" and request.url.path != "/health":
        return JSONResponse(
            status_code=503,
            content={"detail": "El ControlNode no es leader; actualiza DFSHA_CONTROL_URL"},
        )
    return await call_next(request)


@app.on_event("startup")
def startup_event() -> None:
    global _grpc_server, _cluster_monitor
    db.init_db()
    _grpc_server = start_grpc_server()
    _cluster_monitor = ClusterMonitor()
    _cluster_monitor.start()


@app.on_event("shutdown")
def shutdown_event() -> None:
    global _grpc_server, _cluster_monitor
    if _cluster_monitor is not None:
        _cluster_monitor.stop()
    if _grpc_server is not None:
        _grpc_server.stop(grace=1)


# ----------------------------------------------------------------------
# Health & Status
# ----------------------------------------------------------------------

@app.get("/health")
def health() -> dict[str, str]:
    return {
        "status": "ok",
        "role": CONTROLNODE_ROLE,
        "id": CONTROLNODE_ID,
    }


# ----------------------------------------------------------------------
# Authentication
# ----------------------------------------------------------------------

@app.post("/auth/register", status_code=201)
def register(body: Credentials) -> dict[str, str]:
    existing = db.get_user_by_username(body.username)
    if existing:
        raise HTTPException(status_code=409, detail="user already exists")

    pwd_hash = hash_password(body.password)
    db.create_user(body.username, pwd_hash)
    return {"username": body.username}


@app.post("/auth/login")
def login(body: Credentials) -> dict[str, Any]:
    user = db.get_user_by_username(body.username)
    if not user or not verify_password(body.password, user["password_hash"]):
        raise HTTPException(status_code=401, detail="invalid credentials")

    token = create_access_token(user["username"])
    return {
        "access_token": token,
        "token_type": "bearer",
        "expires_in": 3600,
    }


# ----------------------------------------------------------------------
# Filesystem Management (RF1)
# ----------------------------------------------------------------------

@app.post("/fs/mkdir", status_code=201)
def mkdir(
    body: PathRequest,
    current_user: dict[str, Any] = Depends(get_current_user),
) -> dict[str, str]:
    try:
        return db.create_directory(current_user["id"], body.path)
    except KeyError as e:
        raise HTTPException(status_code=404, detail=str(e).strip("'"))
    except FileExistsError as e:
        raise HTTPException(status_code=409, detail=str(e).strip("'"))
    except ValueError as e:
        raise HTTPException(status_code=409, detail=str(e).strip("'"))


@app.get("/fs/ls")
def list_directory(
    path: str = "/",
    current_user: dict[str, Any] = Depends(get_current_user),
) -> dict[str, Any]:
    try:
        norm_path = db.normalize_path(path)
        entries = db.list_directory(current_user["id"], norm_path)
        return {"path": norm_path, "entries": entries}
    except KeyError:
        raise HTTPException(status_code=404, detail="directory not found")


@app.delete("/fs/rmdir", status_code=204)
def remove_directory(
    path: str,
    current_user: dict[str, Any] = Depends(get_current_user),
) -> None:
    try:
        db.remove_directory(current_user["id"], path)
    except KeyError:
        raise HTTPException(status_code=404, detail="directory not found")
    except FileExistsError:
        raise HTTPException(status_code=409, detail="directory not empty")
    except ValueError:
        raise HTTPException(status_code=409, detail="cannot remove root directory")


@app.delete("/fs/file", status_code=204)
def remove_file(
    path: str,
    current_user: dict[str, Any] = Depends(get_current_user),
) -> None:
    try:
        db.remove_file(current_user["id"], path)
    except KeyError:
        raise HTTPException(status_code=404, detail="file not found")


# ----------------------------------------------------------------------
# File Transfers (RF2)
# ----------------------------------------------------------------------

@app.post("/files/put/plan")
def put_plan(
    body: PlanRequest,
    current_user: dict[str, Any] = Depends(get_current_user),
) -> dict[str, Any]:
    if body.size < 0:
        raise HTTPException(status_code=422, detail="file size cannot be negative")

    # Get alive DataNodes
    alive_nodes = db.get_alive_nodes()
    if len(alive_nodes) < REPLICATION_FACTOR:
        raise HTTPException(status_code=503, detail="not enough DataNodes")

    count = max(1, math.ceil(body.size / BLOCK_SIZE_BYTES)) if body.size > 0 else 1
    blocks = []

    for index in range(count):
        start = index * BLOCK_SIZE_BYTES
        size = min(BLOCK_SIZE_BYTES, max(0, body.size - start)) if body.size > 0 else 0
        block_id = str(uuid.uuid4())

        # Select top nodes with most free space, rotating order to balance write pipeline
        # e.g. for index 0: [node0, node1], for index 1: [node1, node0]
        selected_nodes = list(alive_nodes[:REPLICATION_FACTOR])
        if index % 2 == 1 and len(selected_nodes) >= 2:
            selected_nodes = list(reversed(selected_nodes))

        chain = [n["address"] for n in selected_nodes]
        blocks.append({
            "index": index,
            "block_id": block_id,
            "size": size,
            "chain": chain,
        })

    try:
        db.create_upload_plan(
            owner_id=current_user["id"],
            path=body.path,
            size=body.size,
            block_size=BLOCK_SIZE_BYTES,
            blocks=blocks,
        )
    except KeyError as e:
        raise HTTPException(status_code=404, detail=str(e).strip("'"))
    except FileExistsError as e:
        raise HTTPException(status_code=409, detail=str(e).strip("'"))

    return {"block_size": BLOCK_SIZE_BYTES, "blocks": blocks}


@app.post("/files/put/commit")
def put_commit(
    body: CommitRequest,
    current_user: dict[str, Any] = Depends(get_current_user),
) -> dict[str, Any]:
    try:
        db.commit_upload(
            owner_id=current_user["id"],
            path=body.path,
            blocks_stored_on=[b.dict() for b in body.blocks],
            min_write_acks=MIN_WRITE_ACKS,
        )
        return {"status": "ready", "path": db.normalize_path(body.path)}
    except KeyError as e:
        raise HTTPException(status_code=404, detail=str(e).strip("'"))
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e).strip("'"))


@app.post("/files/put/abort")
def put_abort(
    body: AbortRequest,
    current_user: dict[str, Any] = Depends(get_current_user),
) -> dict[str, str]:
    db.abort_upload(current_user["id"], body.path)
    return {"status": "aborted"}


@app.get("/files/get/plan")
def get_plan(
    path: str,
    current_user: dict[str, Any] = Depends(get_current_user),
) -> dict[str, Any]:
    plan = db.get_download_plan(current_user["id"], path)
    if not plan:
        raise HTTPException(status_code=404, detail="file not found")
    return plan
