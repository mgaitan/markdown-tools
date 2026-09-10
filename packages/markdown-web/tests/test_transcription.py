import pytest
import requests
from markdown_web import transcription


def test_openai_compatible_transcriber_posts_model_and_audio(monkeypatch: pytest.MonkeyPatch) -> None:
    seen: dict[str, object] = {}

    class Response:
        def raise_for_status(self) -> None:
            return None

        def json(self) -> dict[str, str]:
            return {"text": "  Transcript  "}

    def fake_post(*args: object, **kwargs: object) -> Response:
        seen.update(url=args[0], **kwargs)
        return Response()

    monkeypatch.setattr(transcription.requests, "post", fake_post)

    result = transcription.OpenAICompatibleTranscriber("test-key").transcribe(b"audio", "recording.webm", "audio/webm")

    assert result == "Transcript"
    assert seen["url"] == transcription.DEFAULT_API_URL
    assert seen["headers"] == {"Authorization": "Bearer test-key"}
    assert seen["data"] == {"model": "whisper-large-v3-turbo", "response_format": "json"}
    assert seen["files"] == {"file": ("recording.webm", b"audio", "audio/webm")}


def test_transcriber_from_environment_uses_generic_configuration(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TRANSCRIPTION_API_KEY", "key")
    monkeypatch.setenv("TRANSCRIPTION_API_URL", "https://provider.example/transcriptions")
    monkeypatch.setenv("TRANSCRIPTION_MODEL", "other-whisper")

    result = transcription.transcriber_from_environment()

    assert result == transcription.OpenAICompatibleTranscriber(
        api_key="key", api_url="https://provider.example/transcriptions", model="other-whisper"
    )


def test_transcriber_from_environment_uses_groq_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("TRANSCRIPTION_API_KEY", raising=False)
    monkeypatch.setenv("GROQ_API_KEY", "groq-key")

    result = transcription.transcriber_from_environment()

    assert result == transcription.OpenAICompatibleTranscriber(api_key="groq-key")


def test_transcriber_raises_provider_error(monkeypatch: pytest.MonkeyPatch) -> None:
    response = requests.Response()
    response.status_code = 401
    response._content = b'{"error":{"message":"Invalid API Key"}}'
    error = requests.HTTPError(response=response)

    def fail_post(*_args: object, **_kwargs: object) -> requests.Response:
        raise error

    monkeypatch.setattr(transcription.requests, "post", fail_post)

    with pytest.raises(transcription.TranscriptionProviderError, match="Invalid API Key"):
        transcription.OpenAICompatibleTranscriber("test-key").transcribe(b"audio", "audio.wav", "audio/wav")
