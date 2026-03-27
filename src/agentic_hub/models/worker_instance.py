from pydantic import Field
from .worker_base import WorkerBase


class WorkerInstance(WorkerBase):
    interface_mode: str = Field(default="internal", description="managed, internal, hybrid")
    enabled: bool = True
    priority_bias: int = 0
    owner: str | None = None
    notes: str = ""
