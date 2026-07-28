from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol


JsonDict = dict[str, Any]


@dataclass(frozen=True)
class SimplificationInstructions:
    category: str = "illustration"
    target_palette_size: int = 24
    preserve_elements: list[str] = field(default_factory=list)
    simplify_elements: list[str] = field(default_factory=list)
    prompt_guidance: str = ""
    preserve_composition: bool = True
    preserve_identity: bool = True
    output_width: int = 1024
    output_height: int = 1024


@dataclass(frozen=True)
class SimplificationResult:
    provider: str
    model: str
    output_path: Path
    metadata: JsonDict = field(default_factory=dict)


class ImageSimplificationProvider(Protocol):
    def simplify(
        self,
        source_image: Path,
        output_path: Path,
        instructions: SimplificationInstructions,
    ) -> SimplificationResult:
        ...


@dataclass(frozen=True)
class PreparedSource:
    source_path: Path
    composition_path: Path
    width: int
    height: int
    fit_mode: str
    original_width: int
    original_height: int
    content_box: tuple[int, int, int, int]


@dataclass(frozen=True)
class RegionRecord:
    region_id: int
    color_id: int
    area: int
    bbox: tuple[int, int, int, int]
    perimeter: int
    estimated_thickness: float
    representative_color: tuple[int, int, int]
    neighbours: list[int]
    holes: int = 0
    components: int = 1


@dataclass(frozen=True)
class ValidationIssue:
    code: str
    severity: str
    message: str
    region_id: int | None = None


@dataclass(frozen=True)
class ValidationReport:
    status: str
    metrics: JsonDict
    issues: list[ValidationIssue]
    suggested_actions: list[str]

    def to_dict(self) -> JsonDict:
        return {
            "status": self.status,
            "metrics": self.metrics,
            "issues": [
                {
                    "code": issue.code,
                    "severity": issue.severity,
                    "message": issue.message,
                    "region_id": issue.region_id,
                }
                for issue in self.issues
            ],
            "suggested_actions": self.suggested_actions,
        }


class ProviderConfigurationError(RuntimeError):
    pass


class ProviderRequestError(RuntimeError):
    def __init__(
        self,
        message: str,
        *,
        status_code: int | None = None,
        error_type: str | None = None,
        code: str | None = None,
        request_id: str | None = None,
        moderation_details: JsonDict | None = None,
        retryable: bool = True,
    ) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.error_type = error_type
        self.code = code
        self.request_id = request_id
        self.moderation_details = moderation_details
        self.retryable = retryable

    def to_detail(self) -> JsonDict:
        detail: JsonDict = {"error": str(self)}
        if self.error_type:
            detail["type"] = self.error_type
        if self.code:
            detail["code"] = self.code
        if self.request_id:
            detail["request_id"] = self.request_id
        if self.moderation_details:
            detail["moderation_details"] = self.moderation_details
        return detail


class ProviderResponseError(RuntimeError):
    pass


class ProcessingDiagnosticError(ValueError):
    """A deterministic pipeline failure with JSON-serializable diagnostics."""

    def __init__(
        self,
        message: str,
        diagnostics: JsonDict,
        *,
        diagnostic_region_map: Any | None = None,
    ) -> None:
        super().__init__(message)
        self.diagnostics = diagnostics
        self.diagnostic_region_map = diagnostic_region_map
