from pydantic import BaseModel


# @dataclass(frozen=True)
class AllProcessingCompleted(BaseModel):
    payload: bool = True


# @dataclass(frozen=True)
class WorkerFailed(BaseModel):
    worker_name: str
    reason: str
