from pydantic import BaseModel


class PlanRequest(BaseModel):
    path: str
    size: int


class CommitBlock(BaseModel):
    index: int
    block_id: str
    stored_on: list[str]


class CommitRequest(BaseModel):
    path: str
    blocks: list[CommitBlock]


class AbortRequest(BaseModel):
    path: str


class OpenRequest(BaseModel):
    path: str
    mode: str = "r"
    append: bool = False
    lease_seconds: int = 300


class CloseBlock(BaseModel):
    index: int
    block_id: str
    stored_on: list[str] = []
    sha256: str | None = None


class CloseRequest(BaseModel):
    session_id: str
    blocks: list[CloseBlock] | None = None


class LockRequest(BaseModel):
    session_id: str
    lease_seconds: int = 300


class UnlockRequest(BaseModel):
    session_id: str


class WritePlanRequest(BaseModel):
    session_id: str
    offset: int
    length: int
    append: bool = False
