from pathlib import Path

import markdown_web.app as app_module
import pytest
from fastapi.testclient import TestClient
from markdown_web.schemas import SourceMetadata, SourceRequest
from markdown_web.service import PreparedContent
from md_to_telegraph import TelegraphContentError
from starlette.status import (
    HTTP_200_OK,
    HTTP_202_ACCEPTED,
    HTTP_303_SEE_OTHER,
    HTTP_404_NOT_FOUND,
    HTTP_422_UNPROCESSABLE_CONTENT,
    HTTP_503_SERVICE_UNAVAILABLE,
)

client = TestClient(app_module.app)


@pytest.mark.parametrize("template_name", ["index.html", "about.html", "bookmarklet.html", "log.html", "drafts.html"])
def test_footers_link_to_drafts_before_bookmarklets(template_name: str) -> None:
    template = (Path(app_module.__file__).parent / "templates" / template_name).read_text(encoding="utf-8")

    assert 'href="/drafts/">Drafts</a>\n      <a href="/bookmarklets/">Bookmarklets</a>' in template


@pytest.mark.parametrize(("action", "target"), [("md", "/md"), ("t", "/t/bookmarklet")])
def test_bookmarklet_capture_receiver_accepts_x_messages(action: str, target: str) -> None:
    response = client.get("/bookmarklet/capture", params={"action": action})

    assert response.status_code == HTTP_200_OK
    assert f'form.action = "{target}"' in response.text
    assert "event.source !== window.opener" in response.text
    assert 'capture?.type !== "markdown-bookmarklet"' in response.text


def test_bookmarklet_capture_receiver_rejects_unknown_action() -> None:
    assert client.get("/bookmarklet/capture", params={"action": "epub"}).status_code == HTTP_404_NOT_FOUND


def _prepared(markdown: str = "# Title\n\nBody") -> PreparedContent:
    return PreparedContent("Title", markdown, "Fallback", SourceMetadata())


def _job_state(status: app_module.jobs.JobStatus = "queued") -> app_module.jobs.JobState:
    state = app_module.jobs.JobState(
        id="a" * 32,
        status=status,
        request=SourceRequest(markdown="# Brief"),
        created_at=1,
        updated_at=1,
    )
    if status == "completed":
        state.brief_url = "https://telegra.ph/brief"
    if status == "failed":
        state.error = "source failed"
        state.failed_source = "https://example.com/article"
    return state


def test_home_and_static_assets() -> None:  # noqa: PLR0915
    response = client.get("/")
    assert response.status_code == HTTP_200_OK
    assert "Write, convert, and publish Markdown" in response.text
    assert ">markdown-web<" not in response.text
    assert 'href="/bookmarklets/">Bookmarklets</a>' in response.text
    assert 'href="/t/published/">Published</a>' in response.text
    assert 'href="/docs">API</a>' in response.text
    assert "Edit source" not in response.text
    assert 'id="new-button"' in response.text
    assert 'id="new-button" class="button button-secondary" type="button" hidden' in response.text
    assert 'id="publish-status" class="status publish-status"' in response.text
    assert "publishButton.disabled = true" in response.text
    assert 'id="preview-button"' in response.text
    assert 'id="result-action-menu-button" class="source-action-menu-button" type="button"' in response.text
    assert 'data-result-action="epub">Download EPUB</button>' in response.text
    assert 'data-result-action="markdown">Download Markdown</button>' in response.text
    assert 'id="preview-pane" class="preview-pane" hidden' in response.text
    assert 'id="preview-frame" class="preview-frame"' in response.text
    assert "Back to edit" in response.text
    assert 'fetch("/t/preview"' in response.text
    assert "window.open" not in response.text
    assert "payload.preview_id = previewId" in response.text
    assert 'id="markdown-toolbar" class="markdown-toolbar"' in response.text
    assert "@codemirror/lang-markdown@6.5.2" in response.text
    assert "@codemirror/language@6.12.4" in response.text
    assert "@codemirror/commands@6.11.0" in response.text
    assert "@codemirror/search@6.7.2" in response.text
    assert "commands.indentWithTab" in response.text
    assert "autocomplete.closeBrackets()" in response.text
    assert "language.syntaxHighlighting(language.defaultHighlightStyle" in response.text
    assert "search.search({top: true})" in response.text
    assert "lineNumbers" not in response.text
    assert 'data-markdown-action="bold"' in response.text
    assert 'data-markdown-action="image"' in response.text
    assert 'data-markdown-action="code-block"' in response.text
    assert 'id="metadata-button"' in response.text
    assert 'id="toolbar-record-button"' in response.text
    assert 'aria-label="Record audio into document"' in response.text
    assert 'id="metadata-dialog"' in response.text
    assert '<select id="metadata-type" name="type">' in response.text
    assert 'id="metadata-telegram"' in response.text
    assert 'id="expand-editor"' in response.text
    assert "editor-fullscreen" in response.text
    assert 'id="new-dialog"' in response.text
    assert "localStorage" in response.text
    assert 'placeholder="Paste a URL, drop a file or insert markdown content"' in response.text
    assert 'submitSource("", file)' in response.text
    assert "showMarkdownEditor(value)" in response.text
    assert "SOURCE_ACTION_KEY" in response.text
    assert all(
        value in response.text
        for value in (
            'document.addEventListener("paste"',
            "getAsFile()",
            "setSelectedFile(file)",
            'showMarkdownEditor(text, "Pasted Markdown")',
        )
    )
    assert 'aria-label="Choose a file"' in response.text
    assert 'id="record-button"' in response.text
    assert 'aria-label="Record audio"' in response.text
    assert 'src="/static/microphone.svg"' in response.text
    assert "audio/*" in response.text
    assert 'fetch("/transcriptions"' in response.text
    assert "navigator.mediaDevices.getUserMedia" in response.text
    assert "insertTranscription(result.text)" in response.text
    assert "function downloadMarkdown()" in response.text
    assert 'id="editor-image-file"' in response.text
    assert 'fetch("/images"' in response.text
    assert 'property="og:title" content="Write, convert, and publish Markdown"' in response.text
    assert (
        'property="og:description" content="Write Markdown, convert web pages and documents, and publish to Telegraph."'
        in response.text
    )
    assert 'name="twitter:card" content="summary_large_image"' in response.text
    assert 'property="og:image" content="https://markdown.fastapicloud.dev/static/social-card.png?v=2"' in response.text
    assert (
        'name="twitter:image" content="https://markdown.fastapicloud.dev/static/social-card.png?v=2"' in response.text
    )
    assert 'rel="icon" href="/static/favicon.svg" type="image/svg+xml"' in response.text
    assert 'rel="manifest" href="/static/manifest.webmanifest?v=2"' in response.text
    assert 'navigator.serviceWorker.register("/service-worker.js?v=3")' in response.text
    assert 'id="install-prompt"' in response.text
    assert 'id="install-button"' in response.text
    assert 'window.addEventListener("beforeinstallprompt"' in response.text
    assert "deferredInstallPrompt.prompt()" in response.text
    assert "const sharedMarkdown" in response.text
    assert client.get("/static/favicon.svg").status_code == HTTP_200_OK
    assert client.get("/static/microphone.svg").status_code == HTTP_200_OK
    assert client.get("/static/logo.png").status_code == HTTP_200_OK
    assert client.get("/static/social-card.png").status_code == HTTP_200_OK
    assert client.get("/static/styles.css").status_code == HTTP_200_OK
    manifest = client.get("/static/manifest.webmanifest")
    assert manifest.status_code == HTTP_200_OK
    assert manifest.json()["share_target"]["action"] == "/share"
    assert "audio/*" in manifest.json()["share_target"]["params"]["files"][0]["accept"]
    assert "application/pdf" in manifest.json()["share_target"]["params"]["files"][0]["accept"]
    service_worker = client.get("/service-worker.js")
    assert service_worker.status_code == HTTP_200_OK
    assert service_worker.headers["cache-control"] == "no-cache"
    assert 'const CACHE_NAME = "markdown-web-shell-v6";' in service_worker.text


def test_home_places_editor_control_in_toolbar() -> None:
    response = client.get("/")

    assert (
        'id="metadata-button" type="button" aria-label="Publication metadata" '
        'title="Publication metadata">Meta</button>\n'
        '                <button id="expand-editor"' in response.text
    )


def test_home_offers_bounded_local_draft_management() -> None:
    response = client.get("/")

    assert 'id="toolbar-save-draft"' in response.text
    assert 'href="/drafts/">Drafts</a>\n      <a href="/bookmarklets/">Bookmarklets</a>' in response.text
    assert 'id="save-before-replace"' in response.text
    assert 'const SAVED_DRAFTS_KEY = "markdown-web-saved-drafts";' in response.text
    assert "const MAX_SAVED_DRAFTS = 20;" in response.text
    assert "function requestReplacement(action, label)" in response.text
    assert "function openSavedDraft(id)" in response.text
    assert 'new URLSearchParams(window.location.search).get("draft")' in response.text
    assert "requestReplacement(() => {" in response.text


def test_drafts_page_lists_local_draft_management() -> None:
    response = client.get("/drafts/")

    assert response.status_code == HTTP_200_OK
    assert 'id="draft-list" class="draft-list"' in response.text
    assert 'const SAVED_DRAFTS_KEY = "markdown-web-saved-drafts";' in response.text
    assert 'href="/bookmarklets/">Bookmarklets</a>' in response.text


def test_share_target_transcribes_audio(monkeypatch: pytest.MonkeyPatch) -> None:
    class FakeTranscriber:
        def transcribe(self, data: bytes, filename: str, content_type: str) -> str:
            assert data == b"audio"
            assert filename == "note.webm"
            assert content_type == "audio/webm"
            return "Shared transcript"

    monkeypatch.setattr(app_module, "transcriber_from_environment", lambda: FakeTranscriber())

    response = client.post("/share", files={"file": ("note.webm", b"audio", "audio/webm")})

    assert response.status_code == HTTP_200_OK
    assert 'const sharedMarkdown = "Shared transcript"' in response.text
    assert 'const sharedLabel = "Transcript: note.webm"' in response.text


def test_share_target_converts_document(monkeypatch: pytest.MonkeyPatch) -> None:
    seen: dict[str, object] = {}

    def fake_prepare(source: SourceRequest) -> PreparedContent:
        seen["source"] = source
        return _prepared("# Shared document\n\nBody")

    monkeypatch.setattr(app_module, "prepare_content", fake_prepare)

    response = client.post("/share", files={"file": ("report.pdf", b"document", "application/pdf")})

    assert response.status_code == HTTP_200_OK
    assert seen["source"].document == b"document"
    assert seen["source"].filename == "report.pdf"
    assert "Shared document" in response.text


def test_share_target_opens_shared_text() -> None:
    response = client.post("/share", data={"title": "Note", "text": "# Shared note\n\nBody"})

    assert response.status_code == HTTP_200_OK
    assert "Shared note" in response.text
    assert 'const sharedLabel = "Note"' in response.text


def test_share_target_extracts_url_sent_as_text(monkeypatch: pytest.MonkeyPatch) -> None:
    seen: dict[str, object] = {}

    def fake_prepare(source: SourceRequest) -> PreparedContent:
        seen["source"] = source
        return _prepared("# Extracted article\n\nBody")

    monkeypatch.setattr(app_module, "prepare_content", fake_prepare)

    response = client.post(
        "/share",
        data={"title": "Article", "text": "https://example.com/article"},
    )

    assert response.status_code == HTTP_200_OK
    assert seen["source"].url == "https://example.com/article"
    assert seen["source"].metadata.title == "Article"
    assert "Extracted article" in response.text


def test_share_target_extracts_share_google_url_from_android_text(monkeypatch: pytest.MonkeyPatch) -> None:
    seen: dict[str, object] = {}

    def fake_prepare(source: SourceRequest) -> PreparedContent:
        seen["source"] = source
        return _prepared("# Extracted article\n\nBody")

    monkeypatch.setattr(app_module, "prepare_content", fake_prepare)

    response = client.post(
        "/share",
        data={
            "text": "Article title - A short article description https://share.google/abc123?hl=en  ",
        },
    )

    assert response.status_code == HTTP_200_OK
    assert seen["source"].url == "https://share.google/abc123?hl=en"
    assert "Extracted article" in response.text


@pytest.mark.parametrize(
    "text",
    (
        "Article title - Description https://example.com/related https://share.google/abc123",
        "First paragraph.\n\nArticle title - Description https://share.google/abc123",
    ),
)
def test_share_target_keeps_nonstandard_share_google_text_as_text(monkeypatch: pytest.MonkeyPatch, text: str) -> None:
    called = False

    def fake_prepare(_source: SourceRequest) -> PreparedContent:
        nonlocal called
        called = True
        return _prepared()

    monkeypatch.setattr(app_module, "prepare_content", fake_prepare)

    response = client.post("/share", data={"text": text})

    assert response.status_code == HTTP_200_OK
    assert not called


def test_home_has_source_action_dropdown() -> None:
    response = client.get("/")

    assert all(
        value in response.text
        for value in (
            'id="source-action-button" class="source-action-button button button-primary" '
            'type="submit" name="action" value="process">Process</button>',
            'id="source-action-menu-button" class="source-action-menu-button" type="button"',
            'data-source-action="process">Process</button>',
            'data-source-action="publish">Publish</button>',
            'data-source-action="epub">Export EPUB</button>',
            'id="submit-publish" class="source-action-button button button-primary" type="submit">Publish</button>',
            'id="result-action-menu-button" class="source-action-menu-button" type="button"',
            'data-result-action="epub">Download EPUB</button>',
            'data-result-action="markdown">Download Markdown</button>',
        )
    )


def test_home_limits_install_prompt_to_mobile_viewports() -> None:
    response = client.get("/")

    assert "function isMobileViewport() {" in response.text
    assert 'window.matchMedia("(max-width: 560px)").matches' in response.text
    assert "isMobileViewport() && !isInstalledApp()" in response.text


def test_home_guards_direct_publication() -> None:
    response = client.get("/")

    assert "if (sourceSubmitting) return;" in response.text
    assert "sourceActionButton.disabled = true" in response.text
    assert "sourceActionMenuButton.disabled = true" in response.text


def test_home_sandboxes_preview_frame() -> None:
    response = client.get("/")

    assert 'id="preview-frame" class="preview-frame" title="Telegraph preview" loading="eager" sandbox' in response.text


def test_health_returns_application_version() -> None:
    response = client.get("/health/")

    assert response.status_code == HTTP_200_OK
    assert response.json() == {
        "status": "ok",
        "commit": app_module.APP_COMMIT,
        "version": app_module.APP_VERSION,
    }
    assert response.headers["cache-control"] == "no-store"


def test_about_describes_routes_and_cli() -> None:
    response = client.get("/about")

    assert response.status_code == HTTP_200_OK
    assert "/md/&lt;url&gt;" in response.text
    assert "/t/published/" in response.text
    assert "/t/jobs" in response.text
    assert "Write Markdown, convert web pages and documents, or publish to Telegraph." in response.text
    assert 'href="/llms.txt">llms.txt</a>' in response.text
    assert 'href="/docs">API documentation</a>' in response.text
    assert "notify_telegram" in response.text
    assert "POST /images" in response.text
    assert "t.me/MarkdownTelegraphBot" in response.text
    assert "uvx markdown-this" in response.text
    assert "github.com/mgaitan" in response.text
    assert "Is this site useful to you?" in response.text
    assert 'href="https://cafecito.app/tin_nqn_">cafecito</a>' in response.text
    assert 'property="og:image" content="https://markdown.fastapicloud.dev/static/logo.png"' in response.text


def test_llms_describes_agent_contract() -> None:
    response = client.get("/llms.txt")

    assert response.status_code == HTTP_200_OK
    assert "POST /t" in response.text
    assert "POST /images" in response.text
    assert "`title`, `author`, `url`, `date`, `image`, `type`, and `notify_telegram`" in response.text
    assert "![card](https://example.com/article)" in response.text
    assert "POST /t/jobs" in response.text
    assert "POST <run_url>" in response.text
    assert "https://markdown.fastapicloud.dev/openapi.json" in response.text
    assert "notify_telegram" in response.text
    assert "MarkdownTelegraphBot" in response.text


def test_openapi_describes_post_bodies_and_publish_response() -> None:
    schema = client.get("/openapi.json").json()

    markdown_post = schema["paths"]["/md"]["post"]
    assert "application/json" in markdown_post["requestBody"]["content"]
    assert "multipart/form-data" in markdown_post["requestBody"]["content"]
    assert "markdown" in markdown_post["requestBody"]["content"]["application/json"]["schema"]["properties"]
    assert "$defs" not in markdown_post["requestBody"]["content"]["application/json"]["schema"]
    metadata_properties = markdown_post["requestBody"]["content"]["application/json"]["schema"]["properties"][
        "metadata"
    ]["properties"]
    assert "notify_telegram" in metadata_properties

    image_post = schema["paths"]["/images"]["post"]
    assert image_post["responses"]["200"]["content"]["application/json"]["schema"]["$ref"] == (
        "#/components/schemas/ImageUploadResponse"
    )

    publish_post = schema["paths"]["/t"]["post"]
    assert publish_post["responses"]["200"]["content"]["application/json"]["schema"]["$ref"] == (
        "#/components/schemas/TelegraphResponse"
    )
    preview_post = schema["paths"]["/t/preview"]["post"]
    assert preview_post["responses"]["200"]["content"]["application/json"]["schema"]["$ref"] == (
        "#/components/schemas/TelegraphPreviewResponse"
    )
    assert (
        schema["paths"]["/t/jobs"]["post"]["responses"]["202"]["content"]["application/json"]["schema"]["$ref"]
        == "#/components/schemas/TelegraphJobResponse"
    )
    assert schema["paths"]["/epub"]["post"]["requestBody"]["content"]["application/json"]


def test_search_engine_discovery_metadata() -> None:
    about_response = client.get("/about")
    bookmarklet_response = client.get("/bookmarklets/")
    sitemap_response = client.get("/sitemap.xml")
    robots_response = client.get("/robots.txt")

    assert 'name="robots" content="index,follow"' in about_response.text
    assert 'rel="canonical" href="https://markdown.fastapicloud.dev/about"' in about_response.text
    assert 'rel="canonical" href="https://markdown.fastapicloud.dev/bookmarklets/"' in bookmarklet_response.text
    assert "https://markdown.fastapicloud.dev/about" in sitemap_response.text
    assert "https://markdown.fastapicloud.dev/bookmarklets/" in sitemap_response.text
    assert "Sitemap: https://markdown.fastapicloud.dev/sitemap.xml" in robots_response.text


def test_get_markdown_uses_jina_style_path_and_preserves_query(monkeypatch: pytest.MonkeyPatch) -> None:
    seen: list[str] = []

    def fake_prepare(source: SourceRequest) -> PreparedContent:
        seen.append(source.url)
        return _prepared()

    monkeypatch.setattr(app_module, "prepare_content", fake_prepare)

    response = client.get("/md/https://example.com/article?edition=mobile")

    assert response.status_code == HTTP_200_OK
    assert response.text == "# Title\n\nBody"
    assert seen == ["https://example.com/article?edition=mobile"]


def test_post_markdown_accepts_json(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(app_module, "prepare_content", lambda source: _prepared("# From JSON"))

    response = client.post("/md", json={"url": "https://example.com"})

    assert response.status_code == HTTP_200_OK
    assert response.text == "# From JSON"
    assert response.headers["content-type"].startswith("text/markdown")


def test_post_epub_returns_download(monkeypatch: pytest.MonkeyPatch) -> None:
    seen: dict[str, SourceRequest] = {}

    def fake_build(source: SourceRequest) -> tuple[bytes, str]:
        seen["source"] = source
        return b"epub-bytes", "my-book.epub"

    monkeypatch.setattr(app_module, "build_epub_content", fake_build)

    response = client.post("/epub", json={"markdown": "# Title"})

    assert response.status_code == HTTP_200_OK
    assert response.content == b"epub-bytes"
    assert response.headers["content-type"] == "application/epub+zip"
    assert response.headers["content-disposition"] == 'attachment; filename="my-book.epub"'
    assert response.headers["cache-control"] == "no-store"
    assert seen["source"].markdown == "# Title"


def test_post_markdown_accepts_raw_html_metadata(monkeypatch: pytest.MonkeyPatch) -> None:
    seen: dict[str, SourceRequest] = {}

    def fake_prepare(source: SourceRequest) -> PreparedContent:
        seen["source"] = source
        return _prepared("# From HTML")

    monkeypatch.setattr(app_module, "prepare_content", fake_prepare)

    response = client.post(
        "/md",
        content="<h1>From HTML</h1>",
        headers={"content-type": "text/html", "x-source-url": "https://example.com"},
    )

    assert response.status_code == HTTP_200_OK
    assert seen["source"].html == "<h1>From HTML</h1>"
    assert seen["source"].metadata.url == "https://example.com"


def test_post_markdown_detects_structural_html_fragment_in_plain_text(monkeypatch: pytest.MonkeyPatch) -> None:
    seen: dict[str, SourceRequest] = {}

    def fake_prepare(source: SourceRequest) -> PreparedContent:
        seen["source"] = source
        return _prepared("# From HTML")

    monkeypatch.setattr(app_module, "prepare_content", fake_prepare)

    response = client.post("/md", content="<article><p>From HTML</p></article>", headers={"content-type": "text/plain"})

    assert response.status_code == HTTP_200_OK
    assert seen["source"].html == "<article><p>From HTML</p></article>"
    assert seen["source"].markdown is None


def test_post_markdown_keeps_plain_text_with_embedded_html_as_markdown(monkeypatch: pytest.MonkeyPatch) -> None:
    seen: dict[str, SourceRequest] = {}

    def fake_prepare(source: SourceRequest) -> PreparedContent:
        seen["source"] = source
        return _prepared("# Markdown")

    monkeypatch.setattr(app_module, "prepare_content", fake_prepare)

    response = client.post(
        "/md",
        content="# Heading\n\n<article>Embedded HTML</article>",
        headers={"content-type": "text/plain"},
    )

    assert response.status_code == HTTP_200_OK
    assert seen["source"].markdown == "# Heading\n\n<article>Embedded HTML</article>"
    assert seen["source"].html is None


def test_post_markdown_accepts_document_upload(monkeypatch: pytest.MonkeyPatch) -> None:
    seen: dict[str, SourceRequest] = {}

    def fake_prepare(source: SourceRequest) -> PreparedContent:
        seen["source"] = source
        return _prepared("# From document")

    monkeypatch.setattr(app_module, "prepare_content", fake_prepare)

    response = client.post("/md", files={"file": ("report.epub", b"document", "application/epub+zip")})

    assert response.status_code == HTTP_200_OK
    assert response.text == "# From document"
    assert seen["source"].document == b"document"
    assert seen["source"].filename == "report.epub"


def test_post_markdown_accepts_html_upload(monkeypatch: pytest.MonkeyPatch) -> None:
    seen: dict[str, SourceRequest] = {}

    def fake_prepare(source: SourceRequest) -> PreparedContent:
        seen["source"] = source
        return _prepared("# From HTML file")

    monkeypatch.setattr(app_module, "prepare_content", fake_prepare)

    response = client.post("/md", files={"file": ("article.html", b"<h1>From HTML</h1>", "text/html")})

    assert response.status_code == HTTP_200_OK
    assert response.text == "# From HTML file"
    assert seen["source"].html == "<h1>From HTML</h1>"
    assert seen["source"].document is None


def test_post_image_upload_returns_public_url(monkeypatch: pytest.MonkeyPatch) -> None:
    seen: dict[str, object] = {}

    def fake_upload(data: bytes, client_ip: str) -> str:
        seen["data"] = data
        seen["client_ip"] = client_ip
        return "https://media.example/images/photo.webp"

    monkeypatch.setattr(app_module.assets, "upload_image", fake_upload)

    response = client.post("/images", files={"file": ("photo.jpg", b"image-bytes", "image/jpeg")})

    assert response.status_code == HTTP_200_OK
    assert response.json() == {"url": "https://media.example/images/photo.webp"}
    assert seen["data"] == b"image-bytes"
    assert isinstance(seen["client_ip"], str)


def test_post_transcription_returns_text(monkeypatch: pytest.MonkeyPatch) -> None:
    seen: dict[str, object] = {}

    class FakeTranscriber:
        def transcribe(self, data: bytes, filename: str, content_type: str) -> str:
            seen.update(data=data, filename=filename, content_type=content_type)
            return "A transcribed recording"

    monkeypatch.setattr(app_module, "transcriber_from_environment", lambda: FakeTranscriber())

    response = client.post("/transcriptions", files={"file": ("recording.webm", b"audio", "audio/webm")})

    assert response.status_code == HTTP_200_OK
    assert response.json() == {"text": "A transcribed recording"}
    assert seen == {"data": b"audio", "filename": "recording.webm", "content_type": "audio/webm"}


def test_post_transcription_requires_configured_provider(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        app_module,
        "transcriber_from_environment",
        lambda: (_ for _ in ()).throw(app_module.TranscriptionUnavailableError()),
    )

    response = client.post("/transcriptions", files={"file": ("recording.webm", b"audio", "audio/webm")})

    assert response.status_code == HTTP_503_SERVICE_UNAVAILABLE
    assert response.json() == {"detail": "Audio transcription is not configured"}


def test_post_transcription_rejects_empty_and_large_files() -> None:
    empty = client.post("/transcriptions", files={"file": ("recording.webm", b"", "audio/webm")})
    too_large = client.post(
        "/transcriptions",
        files={"file": ("recording.webm", b"x" * (app_module.MAX_AUDIO_UPLOAD_BYTES + 1), "audio/webm")},
    )

    assert empty.status_code == HTTP_422_UNPROCESSABLE_CONTENT
    assert empty.json() == {"detail": "Audio file is empty"}
    assert too_large.status_code == HTTP_422_UNPROCESSABLE_CONTENT
    assert too_large.json() == {"detail": "Audio file exceeds the 25 MB limit"}


def test_post_telegraph_returns_json_and_accepts_bearer_token(monkeypatch: pytest.MonkeyPatch) -> None:
    seen: dict[str, SourceRequest] = {}

    def fake_publish(
        source: SourceRequest,
        cache_key: str | None = None,
    ) -> str:
        seen["source"] = source
        seen["cache_key"] = cache_key
        return "https://telegra.ph/page"

    monkeypatch.setattr(app_module, "publish_content", fake_publish)

    response = client.post(
        "/t",
        json={"markdown": "# Title"},
        headers={"authorization": "Bearer request-token"},
    )

    assert response.status_code == HTTP_200_OK
    assert response.json() == {"url": "https://telegra.ph/page"}
    assert seen["source"].access_token == "request-token"


def test_post_preview_returns_json_and_accepts_preview_id(monkeypatch: pytest.MonkeyPatch) -> None:
    seen: dict[str, SourceRequest] = {}

    def fake_preview(source: SourceRequest) -> tuple[str, str]:
        seen["source"] = source
        return "signed-preview-id", "https://telegra.ph/preview"

    monkeypatch.setattr(app_module, "preview_content", fake_preview)

    response = client.post(
        "/t/preview",
        json={"markdown": "# Title", "preview_id": "old-preview-id"},
        headers={"authorization": "Bearer request-token"},
    )

    assert response.status_code == HTTP_200_OK
    assert response.json() == {
        "preview_id": "signed-preview-id",
        "url": "https://telegra.ph/preview",
    }
    assert seen["source"].preview_id == "old-preview-id"
    assert seen["source"].access_token == "request-token"


def test_preview_frame_proxies_telegraph_html(monkeypatch: pytest.MonkeyPatch) -> None:
    seen: list[str] = []

    def fake_fetch(url: str) -> str:
        seen.append(url)
        return "<html><head><title>Preview</title></head><body>Draft</body></html>"

    monkeypatch.setattr(app_module, "fetch_telegraph_preview", fake_fetch)

    response = client.get("/t/preview-frame", params={"url": "https://telegra.ph/preview"})

    assert response.status_code == HTTP_200_OK
    assert response.text.startswith("<html>")
    assert "Draft" in response.text
    assert seen == ["https://telegra.ph/preview"]
    assert response.headers["cache-control"] == "no-store"


def test_create_telegraph_job_returns_polling_urls(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(app_module.jobs, "create_job", lambda _source: _job_state())

    response = client.post("/t/jobs", json={"markdown": "# Brief"})

    assert response.status_code == HTTP_202_ACCEPTED
    assert response.json() == {
        "id": "a" * 32,
        "status": "queued",
        "completed": 0,
        "total": 1,
        "status_url": f"https://markdown.fastapicloud.dev/t/jobs/{'a' * 32}",
        "run_url": f"https://markdown.fastapicloud.dev/t/jobs/{'a' * 32}/run",
        "url": None,
        "error": None,
        "source_url": None,
    }


def test_job_status_returns_completed_url_before_catch_all_route(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(app_module.jobs, "get_job", lambda _job_id: _job_state("completed"))

    response = client.get(f"/t/jobs/{'a' * 32}")

    assert response.status_code == HTTP_200_OK
    assert response.json()["status"] == "completed"
    assert response.json()["url"] == "https://telegra.ph/brief"


def test_run_job_reports_failure_and_source(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(app_module.jobs, "run_job", lambda _job_id: _job_state("failed"))

    response = client.post(f"/t/jobs/{'a' * 32}/run")

    assert response.status_code == HTTP_422_UNPROCESSABLE_CONTENT
    assert response.json()["error"] == "source failed"
    assert response.json()["source_url"] == "https://example.com/article"


@pytest.mark.parametrize(
    ("error", "status_code"),
    [
        (app_module.jobs.JobsUnavailableError(), HTTP_503_SERVICE_UNAVAILABLE),
        (app_module.jobs.JobNotFoundError("missing"), HTTP_404_NOT_FOUND),
    ],
)
def test_job_routes_map_storage_errors(
    monkeypatch: pytest.MonkeyPatch,
    error: Exception,
    status_code: int,
) -> None:
    def fail(_job_id: str) -> app_module.jobs.JobState:
        raise error

    monkeypatch.setattr(app_module.jobs, "get_job", fail)

    response = client.get(f"/t/jobs/{'a' * 32}")

    assert response.status_code == status_code


def test_bookmarklet_post_redirects_without_fetch_or_cors(monkeypatch: pytest.MonkeyPatch) -> None:
    seen: dict[str, SourceRequest] = {}

    def fake_publish(source: SourceRequest, cache_key: str | None = None) -> str:
        seen["source"] = source
        return "https://telegra.ph/page"

    monkeypatch.setattr(app_module, "publish_content", fake_publish)

    response = client.post(
        "/t/bookmarklet",
        data={
            "html": "<h1>Title</h1><p>Body</p>",
            "title": "Title",
            "source_url": "https://chatgpt.com/c/example",
        },
        follow_redirects=False,
    )

    assert response.status_code == HTTP_303_SEE_OTHER
    assert response.headers["location"] == "https://telegra.ph/page"
    assert seen["source"].html == "<h1>Title</h1><p>Body</p>"
    assert seen["source"].metadata.url == "https://chatgpt.com/c/example"


def test_post_telegraph_rejects_non_document_sources(monkeypatch: pytest.MonkeyPatch) -> None:
    def reject_source(source: SourceRequest, cache_key: str | None = None) -> str:
        raise TelegraphContentError("website")

    monkeypatch.setattr(app_module, "publish_content", reject_source)

    response = client.post("/t", json={"markdown": "---\ntype: website\n---\n\nHome"})

    assert response.status_code == HTTP_422_UNPROCESSABLE_CONTENT
    assert response.json() == {"detail": "Refusing to publish non-document page (type: website)"}


def test_get_telegraph_redirects(monkeypatch: pytest.MonkeyPatch) -> None:
    seen: dict[str, object] = {}

    def fake_publish(
        source: SourceRequest,
        cache_key: str | None = None,
    ) -> str:
        seen["source"] = source
        seen["cache_key"] = cache_key
        return "https://telegra.ph/page"

    monkeypatch.setattr(app_module, "publish_content", fake_publish)

    response = client.get("/t/https://example.com/article", follow_redirects=False)

    assert response.status_code == HTTP_303_SEE_OTHER
    assert response.headers["location"] == "https://telegra.ph/page"
    assert response.headers["cache-control"] == "public, max-age=86400"
    assert seen["cache_key"] == "https://example.com/article"


def test_telegraph_published_lists_pages(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        app_module,
        "list_published_pages",
        lambda: (
            1,
            [
                {
                    "url": "https://telegra.ph/Article-08-07",
                    "title": "Article",
                    "author_url": "https://example.com/article",
                    "views": 12,
                }
            ],
        ),
    )

    response = client.get("/t/published/")

    assert response.status_code == HTTP_200_OK
    assert "Published pages" in response.text
    assert 'href="https://telegra.ph/Article-08-07"' in response.text
    assert 'href="https://example.com/article"' in response.text
    assert "12 views" in response.text


def test_bookmarklet_form_does_not_expose_token(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TELEGRAPH_API_TOKEN", "secret-token")

    response = client.get("/bookmarklet/")

    assert response.status_code == HTTP_200_OK
    assert "Save as Markdown" in response.text
    assert "javascript:" in response.text
    assert "secret-token" not in response.text
    assert "Generate bookmarklets" not in response.text
    assert "Drag either link" in response.text


def test_invalid_post_source_returns_client_error() -> None:
    response = client.post("/md", json={})
    assert response.status_code == HTTP_422_UNPROCESSABLE_CONTENT
