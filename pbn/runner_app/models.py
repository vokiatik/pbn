from typing import Any

from pydantic import BaseModel, Field


class RunStepRequest(BaseModel):
    project_id: str
    public_id: str | None = None
    params: dict[str, Any] = Field(default_factory=dict)


class RunStepResponse(BaseModel):
    ok: bool
    step: int
    project_id: str
    public_id: str | None = None
    output_dir: str
    result: dict[str, Any]


class UploadPreviewRequest(BaseModel):
    project_id: str
    public_id: str | None = None


class UploadPreviewResponse(BaseModel):
    ok: bool
    project_id: str
    public_id: str | None = None
    output_dir: str
    preview_path: str
    result: dict[str, Any]
