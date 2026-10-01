from typing import Optional, Any
from pydantic import BaseModel


class EventIn(BaseModel):
    pipeline_name: str
    error_type:    str
    error_message: str
    traceback:     str
    analysis:      str
    suggestions:   list[dict]   # [{label, description, operation}]
    failing_rows:  Optional[str] = None  # formatted sample of failing rows


class EventOut(BaseModel):
    id:            str
    pipeline_name: str
    error_type:    str
    error_message: str
    traceback:     str
    analysis:      str
    suggestions:   list[dict]
    status:        str
    operation:     Optional[dict] = None
    scope:         Optional[str]  = None
    created_at:    str


class ResolveIn(BaseModel):
    operation: dict   # the full operation spec chosen by the user
    scope:     str    # 'once' | 'this_error' | 'global'
    label:     str    # human-readable label for the rule ("Remove rows", etc.)


class ResolutionOut(BaseModel):
    id:            int
    error_type:    str
    error_fragment: str
    pipeline_name: Optional[str] = None
    operation:     dict
    label:         str
    scope:         str
    applied_count: int
    created_at:    str
