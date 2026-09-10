"""Audio transcription providers used by the web application."""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Protocol

import requests

DEFAULT_API_URL = "https://api.groq.com/openai/v1/audio/transcriptions"
DEFAULT_MODEL = "whisper-large-v3-turbo"
MAX_AUDIO_UPLOAD_BYTES = 25 * 1024 * 1024
TRANSCRIPTION_TIMEOUT = 120


class TranscriptionError(ValueError):
    """Raised when an audio file cannot be transcribed."""


class TranscriptionUnavailableError(TranscriptionError):
    """Raised when no provider credentials are configured."""

    def __init__(self) -> None:
        super().__init__("Audio transcription is not configured")


class TranscriptionProviderError(TranscriptionError):
    """Raised when a configured provider rejects a transcription request."""

    def __init__(self, detail: str = "Audio transcription failed") -> None:
        super().__init__(detail)


class InvalidTranscriptionResponseError(TranscriptionProviderError):
    """Raised when a provider returns a response without a usable transcript."""

    def __init__(self) -> None:
        super().__init__("Audio transcription returned an invalid response")


class EmptyTranscriptionError(TranscriptionProviderError):
    """Raised when a provider returns no transcript text."""

    def __init__(self) -> None:
        super().__init__("Audio transcription returned no text")


class AudioTranscriber(Protocol):
    """Interface for file-based speech-to-text providers."""

    def transcribe(self, data: bytes, filename: str, content_type: str) -> str:
        """Return the transcript for an uploaded audio file."""


@dataclass(frozen=True)
class OpenAICompatibleTranscriber:
    """A file transcription client for OpenAI-compatible APIs."""

    api_key: str
    api_url: str = DEFAULT_API_URL
    model: str = DEFAULT_MODEL

    def transcribe(self, data: bytes, filename: str, content_type: str) -> str:
        try:
            response = requests.post(
                self.api_url,
                headers={"Authorization": f"Bearer {self.api_key}"},
                data={"model": self.model, "response_format": "json"},
                files={"file": (filename, data, content_type or "application/octet-stream")},
                timeout=TRANSCRIPTION_TIMEOUT,
            )
            response.raise_for_status()
            payload = response.json()
        except requests.RequestException as exc:
            detail = _provider_error_detail(exc.response) if exc.response is not None else "Audio transcription failed"
            raise TranscriptionProviderError(detail) from exc
        except ValueError as exc:
            raise InvalidTranscriptionResponseError from exc

        text = payload.get("text") if isinstance(payload, dict) else None
        if not isinstance(text, str) or not text.strip():
            raise EmptyTranscriptionError
        return text.strip()


def transcriber_from_environment() -> AudioTranscriber:
    """Build the configured provider, keeping provider details in environment variables."""
    api_key = os.getenv("TRANSCRIPTION_API_KEY") or os.getenv("GROQ_API_KEY") or ""
    if not api_key:
        raise TranscriptionUnavailableError
    return OpenAICompatibleTranscriber(
        api_key=api_key,
        api_url=os.getenv("TRANSCRIPTION_API_URL", DEFAULT_API_URL),
        model=os.getenv("TRANSCRIPTION_MODEL", DEFAULT_MODEL),
    )


def _provider_error_detail(response: requests.Response | None) -> str:
    if response is None:
        return "Audio transcription failed"
    try:
        payload = response.json()
    except ValueError:
        return "Audio transcription failed"
    if isinstance(payload, dict):
        detail = payload.get("error") or payload.get("detail")
        if isinstance(detail, dict):
            detail = detail.get("message")
        if isinstance(detail, str) and detail:
            return detail
    return "Audio transcription failed"
