"""Request models accepted by the web service."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


class SourceMetadata(BaseModel):
    """Optional metadata supplied alongside raw HTML or Markdown."""

    title: str = ""
    author: str = ""
    url: str = ""
    date: str = ""
    image: str = ""
    type: str = ""
    extraction_scope: str = ""
    notify_telegram: str = ""

    def values(self) -> dict[str, str]:
        return {key: value for key, value in self.model_dump().items() if value}


class SourceRequest(BaseModel):
    """A URL, raw HTML, or already extracted Markdown document."""

    url: str | None = None
    html: str | None = None
    markdown: str | None = None
    document: bytes | None = None
    filename: str = ""
    metadata: SourceMetadata = Field(default_factory=SourceMetadata)
    access_token: str | None = None
    preview_id: str | None = None


class TelegraphResponse(BaseModel):
    """Response returned after a page is published."""

    url: str


class ImageUploadResponse(BaseModel):
    """Response returned after an image is optimized and stored."""

    url: str


class TranscriptionResponse(BaseModel):
    """Response returned after transcribing an audio file."""

    text: str


class TelegraphPreviewResponse(BaseModel):
    """Response returned after creating or updating a Telegraph preview."""

    preview_id: str
    url: str


class TelegraphJobResponse(BaseModel):
    """Public progress returned by optional Redis-backed publishing jobs."""

    id: str
    status: Literal[
        "queued",
        "publishing_articles",
        "publishing_brief",
        "adding_navigation",
        "completed",
        "failed",
    ]
    completed: int
    total: int
    status_url: str
    run_url: str
    url: str | None = None
    error: str | None = None
    source_url: str | None = None
