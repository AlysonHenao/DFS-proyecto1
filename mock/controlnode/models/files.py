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
