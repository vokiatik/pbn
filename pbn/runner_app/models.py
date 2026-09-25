from typing import Any, Literal

from pydantic import BaseModel, Field


class RunAIPipelineRequest(BaseModel):
    project_id: str
    public_id: str | None = None
    input_path: str | None = None
    settings: dict[str, Any] = Field(default_factory=dict)
    force_regenerate: bool = False
    callback_base: str | None = None
    callback_secret: str | None = None


class GenerateAIImageRequest(RunAIPipelineRequest):
    pass


class ContinueAIPipelineRequest(RunAIPipelineRequest):
    pass


class FinalizePBNOptionRequest(RunAIPipelineRequest):
    difficulty: Literal["hard"]


class RunAIPipelineResponse(BaseModel):
    ok: bool
    project_id: str
    public_id: str | None = None
    output_dir: str
    result: dict[str, Any]


class GenerateAIImageResponse(RunAIPipelineResponse):
    pass


class ContinueAIPipelineResponse(RunAIPipelineResponse):
    pass


class FinalizePBNOptionResponse(RunAIPipelineResponse):
    pass


class UploadPreviewRequest(BaseModel):
    project_id: str
    public_id: str | None = None
    input_path: str | None = None


class UploadPreviewResponse(BaseModel):
    ok: bool
    project_id: str
    public_id: str | None = None
    output_dir: str
    preview_path: str
    result: dict[str, Any]
