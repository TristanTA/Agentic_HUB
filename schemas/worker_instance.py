from pydantic import Field
from .worker_base import WorkerBase


class WorkerInstance(WorkerBase):
    enabled: bool = True
    priority_bias: int = 0
    owner: str | None = None
    notes: str = ""
