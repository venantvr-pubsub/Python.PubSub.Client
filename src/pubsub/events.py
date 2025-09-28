from pydantic import BaseModel


class AllProcessingCompleted(BaseModel):
    payload: bool = True


class WorkerFailed(BaseModel):
    worker_name: str
    reason: str
