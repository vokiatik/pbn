from __future__ import annotations

from dataclasses import dataclass
from math import sqrt


PAGE_MM = {
    "a3": (297.0, 420.0),
    "a4": (210.0, 297.0),
}


@dataclass(frozen=True)
class PrintSpec:
    page_size: str = "a3"
    orientation: str = "portrait"
    dpi: int = 300
    margin_mm: float = 10.0

    def __post_init__(self) -> None:
        if self.page_size not in PAGE_MM:
            raise ValueError("page_size must be a3 or a4")
        if self.orientation not in {"portrait", "landscape"}:
            raise ValueError("orientation must be portrait or landscape")

    @property
    def page_mm(self) -> tuple[float, float]:
        width, height = PAGE_MM[self.page_size]
        return (height, width) if self.orientation == "landscape" else (width, height)

    @property
    def page_px(self) -> tuple[int, int]:
        width, height = self.page_mm
        return mm_to_px(width, self.dpi), mm_to_px(height, self.dpi)

    @property
    def content_mm(self) -> tuple[float, float]:
        width, height = self.page_mm
        return width - 2 * self.margin_mm, height - 2 * self.margin_mm

    @property
    def aspect_ratio(self) -> float:
        return sqrt(2.0) if self.orientation == "landscape" else 1.0 / sqrt(2.0)

    @property
    def composition_px(self) -> tuple[int, int]:
        if self.orientation == "landscape":
            return 1448, 1024
        return 1024, 1448

    @property
    def provider_canvas_px(self) -> tuple[int, int]:
        if self.orientation == "landscape":
            return 1536, 1024
        return 1024, 1536

    @property
    def region_budget(self) -> int:
        return 600 if self.page_size == "a3" else 450


def mm_to_px(mm: float, dpi: int) -> int:
    return int(round(mm / 25.4 * dpi))
