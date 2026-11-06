"""Network-free image-understanding contracts for the OCR-first MVP."""

from __future__ import annotations

import hashlib
from collections.abc import Mapping
from pathlib import Path
from typing import Any, Literal, Protocol, runtime_checkable

from pydantic import BaseModel, ConfigDict, Field, model_validator

from jupjup.domain.errors import VisionProviderError
from jupjup.ingest.extract import tidy_snapshot_text


class ImageInput(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    path: Path | None = None
    ocr_text: str | None = None

    @model_validator(mode="after")
    def _has_input(self) -> ImageInput:
        if self.path is None and self.ocr_text is None:
            raise ValueError("path 또는 ocr_text가 필요합니다")
        return self


class ImageDescription(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    ocr_text: str
    caption: str | None = None
    objects: list[str] = Field(default_factory=list)
    source: Literal["ocr", "vision"]


@runtime_checkable
class ImageUnderstander(Protocol):
    def describe(self, image: ImageInput) -> ImageDescription: ...


def image_key(image: ImageInput) -> str:
    path = "" if image.path is None else str(image.path)
    ocr_text = image.ocr_text or ""
    return hashlib.sha256(f"{path}\x00{ocr_text}".encode()).hexdigest()


class OcrOnlyUnderstander:
    """Clean caller-supplied OCR text without opening the image or using a network."""

    def describe(self, image: ImageInput) -> ImageDescription:
        cleaned = tidy_snapshot_text(image.ocr_text or "")
        if not cleaned:
            raise VisionProviderError("이미지 분석에 사용할 OCR 텍스트가 없습니다", {"reason": "no_text"})
        return ImageDescription(ocr_text=cleaned, source="ocr")


class MockImageUnderstander:
    """Return deterministic fixtures, falling back to the OCR-only behavior."""

    def __init__(self, fixtures: Mapping[str, ImageDescription | Mapping[str, Any]] | None = None) -> None:
        self._fixtures = dict(fixtures or {})
        self._ocr = OcrOnlyUnderstander()
        self.calls: list[str] = []

    def describe(self, image: ImageInput) -> ImageDescription:
        key = image_key(image)
        self.calls.append(key)
        candidates = [key]
        if image.path is not None:
            candidates.append(str(image.path))
        candidates.append("default")
        for candidate in candidates:
            value = self._fixtures.get(candidate)
            if value is not None:
                if isinstance(value, ImageDescription):
                    return value.model_copy(deep=True)
                return ImageDescription.model_validate(value)
        return self._ocr.describe(image)
