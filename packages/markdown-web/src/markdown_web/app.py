"""FastAPI application for Markdown extraction and Telegraph publishing."""

from __future__ import annotations

import json
import os
import re
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, JSONResponse, PlainTextResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from markdown_this import is_html_source
from md_to_epub import EpubBuildError
from md_to_telegraph import TelegraphContentError
from starlette.concurrency import run_in_threadpool
from starlette.datastructures import UploadFile

from markdown_web import assets, jobs
from markdown_web.bookmarklet import build_bookmarklets
from markdown_web.schemas import (
    ImageUploadResponse,
    SourceMetadata,
    SourceRequest,
    TelegraphJobResponse,
    TelegraphPreviewResponse,
    TelegraphResponse,
    TranscriptionResponse,
)
from markdown_web.service import (
    SourceError,
    build_epub_content,
    fetch_telegraph_preview,
    list_published_pages,
    prepare_content,
    preview_content,
    publish_content,
)
from markdown_web.transcription import (
    MAX_AUDIO_UPLOAD_BYTES,
    TranscriptionError,
    TranscriptionProviderError,
    TranscriptionUnavailableError,
    transcriber_from_environment,
)

load_dotenv()
app = FastAPI(title="Markdown Web", description="Extract Markdown and publish it to Telegraph")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["GET", "POST"], allow_headers=["*"])
PACKAGE_DIR = Path(__file__).resolve().parent
templates = Jinja2Templates(directory=str(PACKAGE_DIR / "templates"))
app.mount("/static", StaticFiles(directory=PACKAGE_DIR / "static"), name="static")
SITE_URL = os.getenv("SITE_URL", "https://markdown.fastapicloud.dev").rstrip("/")
LLMS_PATH = PACKAGE_DIR / "templates" / "llms.txt"
SERVICE_WORKER_PATH = PACKAGE_DIR / "static" / "service-worker.js"
try:
    APP_VERSION = version("markdown-web")
except PackageNotFoundError:  # pragma: no cover - the package is installed in supported environments
    APP_VERSION = "unknown"
APP_COMMIT = os.getenv("APP_COMMIT", "unknown")
AUDIO_FILE_SUFFIXES = frozenset({".flac", ".m4a", ".mp3", ".mp4", ".mpeg", ".mpga", ".ogg", ".wav", ".webm"})
HTML_FILE_SUFFIXES = frozenset({".htm", ".html"})
SHARE_GOOGLE_TEXT_URL_RE = re.compile(
    r"^(?P<text>(?:(?![a-z][a-z0-9+.-]*://)[^\r\n])+?)\s+(?P<url>https?://share\.google/[^\s<>\"']+)\s*$",
    re.IGNORECASE,
)


def _source_request_openapi() -> dict[str, object]:
    """Describe the manually parsed request formats in FastAPI's schema."""
    schema = SourceRequest.model_json_schema()
    definitions = schema.pop("$defs", {})
    if metadata_schema := definitions.get("SourceMetadata"):
        schema["properties"]["metadata"] = metadata_schema
    return {
        "requestBody": {
            "required": True,
            "content": {
                "application/json": {
                    "schema": schema,
                    "examples": {
                        "url": {"summary": "Extract a URL", "value": {"url": "https://example.com/article"}},
                        "markdown": {
                            "summary": "Publish Markdown",
                            "value": {"markdown": "# Hello\\n\\nBody"},
                        },
                    },
                },
                "text/html": {"schema": {"type": "string"}},
                "text/plain": {"schema": {"type": "string"}},
                "application/x-www-form-urlencoded": {"schema": {"type": "object"}},
                "multipart/form-data": {
                    "schema": {
                        "type": "object",
                        "required": ["file"],
                        "properties": {
                            "file": {"type": "string", "format": "binary"},
                        },
                    }
                },
            },
        }
    }


def _image_upload_openapi() -> dict[str, object]:
    """Describe the image upload request parsed manually by the route."""
    return {
        "requestBody": {
            "required": True,
            "content": {
                "multipart/form-data": {
                    "schema": {
                        "type": "object",
                        "required": ["file"],
                        "properties": {
                            "file": {
                                "type": "string",
                                "format": "binary",
                                "description": "PNG, JPEG, or WebP image up to 20 MB",
                            }
                        },
                    }
                }
            },
        }
    }


def _transcription_openapi() -> dict[str, object]:
    """Describe the audio upload accepted by the transcription route."""
    return {
        "requestBody": {
            "required": True,
            "content": {
                "multipart/form-data": {
                    "schema": {
                        "type": "object",
                        "required": ["file"],
                        "properties": {
                            "file": {
                                "type": "string",
                                "format": "binary",
                                "description": "Audio file up to 25 MB",
                            }
                        },
                    }
                }
            },
        }
    }


def _path_source(url: str, request: Request) -> str:
    if request.url.query:
        return f"{url}?{request.url.query}"
    return url


async def _request_data(request: Request) -> SourceRequest:
    content_type = request.headers.get("content-type", "").split(";", 1)[0]
    body = await request.body()
    if content_type == "application/json":
        try:
            return SourceRequest.model_validate(json.loads(body or b"{}"))
        except (json.JSONDecodeError, ValueError) as exc:
            raise HTTPException(status_code=400, detail="Invalid JSON request") from exc
    if content_type in {"text/html", "text/plain"}:
        metadata = SourceMetadata(
            title=request.headers.get("x-title", ""),
            author=request.headers.get("x-author-name", ""),
            url=request.headers.get("x-source-url", ""),
            date=request.headers.get("x-published-date", ""),
            image=request.headers.get("x-image-url", ""),
        )
        content = body.decode("utf-8")
        if content_type == "text/html" or is_html_source(content):
            return SourceRequest(html=content, metadata=metadata)
        return SourceRequest(markdown=content, metadata=metadata)
    if content_type == "application/x-www-form-urlencoded":
        values = {key: items[-1] for key, items in parse_qs(body.decode("utf-8")).items() if items}
        metadata = SourceMetadata(
            title=values.pop("title", ""),
            author=values.pop("author", ""),
            url=values.pop("source_url", ""),
            date=values.pop("date", ""),
            image=values.pop("image", ""),
        )
        return SourceRequest(**values, metadata=metadata)
    if content_type == "multipart/form-data":
        form = await request.form()
        upload = form.get("file") or form.get("document")
        if not isinstance(upload, UploadFile):
            raise HTTPException(status_code=400, detail="Include a document in the file field")
        metadata = SourceMetadata(
            title=str(form.get("title", "")),
            author=str(form.get("author", "")),
            url=str(form.get("source_url", "")),
            date=str(form.get("date", "")),
            image=str(form.get("image", "")),
        )
        content = await upload.read()
        if _is_html_upload(upload):
            return SourceRequest(html=content.decode("utf-8", errors="replace"), metadata=metadata)
        return SourceRequest(document=content, filename=upload.filename or "", metadata=metadata)
    raise HTTPException(status_code=415, detail="Use JSON, HTML, form-urlencoded, or multipart form data")


def _source_request_from_path(url: str, request: Request) -> SourceRequest:
    return SourceRequest(url=_path_source(url, request))


def _handle_source_error(exc: Exception) -> HTTPException:
    if isinstance(exc, (SourceError, TelegraphContentError, EpubBuildError)):
        return HTTPException(status_code=422, detail=str(exc))
    return HTTPException(status_code=502, detail=str(exc))


def _handle_image_error(exc: Exception) -> HTTPException:
    if isinstance(exc, assets.ImageUploadUnavailableError):
        return HTTPException(status_code=503, detail=str(exc))
    if isinstance(exc, assets.ImageUploadError):
        return HTTPException(status_code=422, detail=str(exc))
    if isinstance(exc, assets.ImageStorageError):
        return HTTPException(status_code=502, detail=str(exc))
    return HTTPException(status_code=502, detail=str(exc))


def _handle_transcription_error(exc: Exception) -> HTTPException:
    if isinstance(exc, TranscriptionUnavailableError):
        return HTTPException(status_code=503, detail=str(exc))
    if isinstance(exc, TranscriptionProviderError):
        return HTTPException(status_code=502, detail=str(exc))
    if isinstance(exc, TranscriptionError):
        return HTTPException(status_code=422, detail=str(exc))
    return HTTPException(status_code=502, detail=str(exc))


def _handle_job_error(exc: Exception) -> HTTPException:
    if isinstance(exc, jobs.JobsUnavailableError):
        return HTTPException(status_code=503, detail=str(exc))
    if isinstance(exc, jobs.JobNotFoundError):
        return HTTPException(status_code=404, detail=str(exc))
    if isinstance(exc, jobs.JobBusyError):
        return HTTPException(status_code=409, detail=str(exc))
    if isinstance(exc, jobs.JobInputError):
        return HTTPException(status_code=422, detail=str(exc))
    return _handle_source_error(exc)


def _job_response(state: jobs.JobState) -> JSONResponse:
    job_url = f"{SITE_URL}/t/jobs/{state.id}"
    payload = TelegraphJobResponse(
        id=state.id,
        status=state.status,
        completed=state.completed_steps,
        total=state.total_steps,
        status_url=job_url,
        run_url=f"{job_url}/run",
        url=state.brief_url or None,
        error=state.error or None,
        source_url=state.failed_source or None,
    )
    if state.status == "completed":
        status_code = 200
    elif state.status == "failed":
        status_code = 422
    else:
        status_code = 202
    return JSONResponse(payload.model_dump(mode="json"), status_code=status_code)


def _authorization_token(request: Request) -> str:
    value = request.headers.get("authorization", "")
    scheme, _, token = value.partition(" ")
    return token if scheme.lower() == "bearer" else ""


def _home_response(
    request: Request,
    *,
    shared_markdown: str = "",
    shared_label: str = "",
    share_error: str = "",
) -> HTMLResponse:
    return templates.TemplateResponse(
        request=request,
        name="index.html",
        context={
            "site_url": SITE_URL,
            "shared_markdown": shared_markdown,
            "shared_label": shared_label,
            "share_error": share_error,
        },
    )


def _is_audio_upload(upload: UploadFile) -> bool:
    return (upload.content_type or "").startswith("audio/") or Path(
        upload.filename or ""
    ).suffix.lower() in AUDIO_FILE_SUFFIXES


def _is_html_upload(upload: UploadFile) -> bool:
    return (upload.content_type or "").split(";", 1)[0] == "text/html" or Path(
        upload.filename or ""
    ).suffix.lower() in HTML_FILE_SUFFIXES


async def _transcribe_upload(upload: UploadFile) -> str:
    data = await upload.read(MAX_AUDIO_UPLOAD_BYTES + 1)
    if not data:
        raise HTTPException(status_code=422, detail="Audio file is empty")
    if len(data) > MAX_AUDIO_UPLOAD_BYTES:
        raise HTTPException(status_code=422, detail="Audio file exceeds the 25 MB limit")
    try:
        transcriber = transcriber_from_environment()
        return await run_in_threadpool(
            transcriber.transcribe,
            data,
            upload.filename or "audio",
            upload.content_type or "",
        )
    except Exception as exc:
        raise _handle_transcription_error(exc) from exc


async def _shared_content(request: Request) -> tuple[str, str]:
    """Process a Web Share Target payload into Markdown for the home screen."""
    form = await request.form()
    upload = form.get("file")
    if isinstance(upload, UploadFile):
        filename = upload.filename or "Shared file"
        if _is_audio_upload(upload):
            return await _transcribe_upload(upload), f"Transcript: {filename}"
        content = await upload.read()
        source = (
            SourceRequest(html=content.decode("utf-8", errors="replace"))
            if _is_html_upload(upload)
            else SourceRequest(document=content, filename=filename)
        )
        try:
            prepared = await run_in_threadpool(
                prepare_content,
                source,
            )
        except Exception as exc:
            raise _handle_source_error(exc) from exc
        return prepared.markdown, filename

    url = str(form.get("url", "")).strip()
    text = str(form.get("text", "")).strip()
    title = str(form.get("title", "")).strip()
    if not url:
        parsed_text_url = urlparse(text)
        if parsed_text_url.scheme in {"http", "https"} and parsed_text_url.netloc:
            url = text
        elif share_url := SHARE_GOOGLE_TEXT_URL_RE.fullmatch(text):
            url = share_url["url"]
    if url:
        try:
            prepared = await run_in_threadpool(
                prepare_content,
                SourceRequest(url=url, metadata=SourceMetadata(title=title)),
            )
        except Exception as exc:
            raise _handle_source_error(exc) from exc
        return prepared.markdown, title or url
    if text:
        return text, title or "Shared text"
    raise HTTPException(status_code=422, detail="Share an audio file, document, URL, or text")


@app.get("/", response_class=HTMLResponse)
def home(request: Request) -> HTMLResponse:
    return _home_response(request)


@app.post("/share", response_class=HTMLResponse, include_in_schema=False)
async def share_target(request: Request) -> HTMLResponse:
    """Receive Android and desktop PWA shares and open their result in the editor."""
    try:
        markdown, label = await _shared_content(request)
    except HTTPException as exc:
        return _home_response(request, share_error=str(exc.detail))
    return _home_response(request, shared_markdown=markdown, shared_label=label)


@app.get("/health/")
def health(response: Response) -> dict[str, str]:
    response.headers["Cache-Control"] = "no-store"
    return {"status": "ok", "commit": APP_COMMIT, "version": APP_VERSION}


@app.get("/service-worker.js", include_in_schema=False)
def service_worker() -> Response:
    return Response(
        SERVICE_WORKER_PATH.read_text(encoding="utf-8"),
        media_type="application/javascript",
        headers={"Cache-Control": "no-cache"},
    )


@app.get("/md/{url:path}", response_class=PlainTextResponse)
def markdown_from_url(url: str, request: Request) -> PlainTextResponse:
    try:
        prepared = prepare_content(_source_request_from_path(url, request))
    except Exception as exc:
        raise _handle_source_error(exc) from exc
    return PlainTextResponse(prepared.markdown, media_type="text/markdown")


@app.post("/md", response_class=PlainTextResponse, openapi_extra=_source_request_openapi())
async def markdown_from_post(request: Request) -> PlainTextResponse:
    source = await _request_data(request)
    try:
        prepared = prepare_content(source)
    except Exception as exc:
        raise _handle_source_error(exc) from exc
    return PlainTextResponse(prepared.markdown, media_type="text/markdown")


@app.post("/epub", openapi_extra=_source_request_openapi())
async def epub_from_post(request: Request) -> Response:
    source = await _request_data(request)
    try:
        data, filename = await run_in_threadpool(build_epub_content, source)
    except Exception as exc:
        raise _handle_source_error(exc) from exc
    return Response(
        content=data,
        media_type="application/epub+zip",
        headers={"Content-Disposition": f'attachment; filename="{filename}"', "Cache-Control": "no-store"},
    )


@app.post("/images", response_model=ImageUploadResponse, openapi_extra=_image_upload_openapi())
async def image_upload(request: Request) -> JSONResponse:
    content_type = request.headers.get("content-type", "").split(";", 1)[0]
    if content_type != "multipart/form-data":
        raise HTTPException(status_code=415, detail="Upload an image as multipart form data")
    form = await request.form()
    upload = form.get("file")
    if not isinstance(upload, UploadFile):
        raise HTTPException(status_code=400, detail="Include an image in the file field")
    data = await upload.read(assets.MAX_IMAGE_UPLOAD_BYTES + 1)
    try:
        target = assets.upload_image(data, request.client.host if request.client else "unknown")
    except Exception as exc:
        raise _handle_image_error(exc) from exc
    return JSONResponse({"url": target})


@app.post("/transcriptions", response_model=TranscriptionResponse, openapi_extra=_transcription_openapi())
async def transcription(request: Request) -> JSONResponse:
    content_type = request.headers.get("content-type", "").split(";", 1)[0]
    if content_type != "multipart/form-data":
        raise HTTPException(status_code=415, detail="Upload audio as multipart form data")
    form = await request.form()
    upload = form.get("file")
    if not isinstance(upload, UploadFile):
        raise HTTPException(status_code=400, detail="Include an audio file in the file field")
    text = await _transcribe_upload(upload)
    return JSONResponse({"text": text})


@app.get("/about", response_class=HTMLResponse)
def about(request: Request) -> HTMLResponse:
    return templates.TemplateResponse(request=request, name="about.html", context={"site_url": SITE_URL})


@app.get("/llms.txt", response_class=PlainTextResponse, include_in_schema=False)
def llms() -> PlainTextResponse:
    body = LLMS_PATH.read_text(encoding="utf-8").replace("{{ site_url }}", SITE_URL)
    return PlainTextResponse(body)


@app.get("/robots.txt", response_class=PlainTextResponse, include_in_schema=False)
def robots() -> PlainTextResponse:
    body = f"User-agent: *\nAllow: /\nSitemap: {SITE_URL}/sitemap.xml\n"
    return PlainTextResponse(body)


@app.get("/sitemap.xml", response_class=PlainTextResponse, include_in_schema=False)
def sitemap() -> PlainTextResponse:
    paths = ("/", "/about", "/bookmarklets/", "/t/published/")
    locations = "".join(f"  <url><loc>{SITE_URL}{path}</loc></url>\n" for path in paths)
    body = f'<?xml version="1.0" encoding="UTF-8"?>\n<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n{locations}</urlset>\n'
    return PlainTextResponse(body, media_type="application/xml")


@app.get("/t/published/", response_class=HTMLResponse)
def telegraph_published(request: Request) -> HTMLResponse:
    try:
        total_count, pages = list_published_pages()
    except Exception as exc:
        raise _handle_source_error(exc) from exc
    return templates.TemplateResponse(
        request=request,
        name="log.html",
        context={"pages": pages, "total_count": total_count, "site_url": SITE_URL},
    )


@app.post(
    "/t/jobs",
    response_model=TelegraphJobResponse,
    status_code=202,
    responses={200: {"model": TelegraphJobResponse}},
    openapi_extra=_source_request_openapi(),
)
async def create_telegraph_job(request: Request) -> JSONResponse:
    source = await _request_data(request)
    if not source.access_token:
        source = source.model_copy(update={"access_token": _authorization_token(request) or None})
    try:
        state = jobs.create_job(source)
    except Exception as exc:
        raise _handle_job_error(exc) from exc
    return _job_response(state)


@app.get(
    "/t/jobs/{job_id}",
    response_model=TelegraphJobResponse,
    status_code=202,
    responses={200: {"model": TelegraphJobResponse}},
)
def telegraph_job_status(job_id: str) -> JSONResponse:
    try:
        state = jobs.get_job(job_id)
    except Exception as exc:
        raise _handle_job_error(exc) from exc
    return _job_response(state)


@app.post(
    "/t/jobs/{job_id}/run",
    response_model=TelegraphJobResponse,
    status_code=202,
    responses={200: {"model": TelegraphJobResponse}},
)
def run_telegraph_job(job_id: str) -> JSONResponse:
    try:
        state = jobs.run_job(job_id)
    except Exception as exc:
        raise _handle_job_error(exc) from exc
    return _job_response(state)


@app.post("/t/preview", response_model=TelegraphPreviewResponse, openapi_extra=_source_request_openapi())
async def telegraph_preview(request: Request) -> JSONResponse:
    source = await _request_data(request)
    if not source.access_token:
        source = source.model_copy(update={"access_token": _authorization_token(request) or None})
    try:
        preview_id, target = preview_content(source)
    except Exception as exc:
        raise _handle_source_error(exc) from exc
    return JSONResponse({"preview_id": preview_id, "url": target})


@app.get("/t/preview-frame", response_class=HTMLResponse, include_in_schema=False)
def telegraph_preview_frame(url: str) -> HTMLResponse:
    """Proxy Telegraph HTML because Telegraph disallows cross-origin iframe embedding."""
    try:
        page = fetch_telegraph_preview(url)
    except Exception as exc:
        raise _handle_source_error(exc) from exc
    return HTMLResponse(page, headers={"Cache-Control": "no-store"})


@app.get("/t/{url:path}")
def telegraph_from_url(url: str, request: Request) -> RedirectResponse:
    try:
        source_url = _path_source(url, request)
        target = publish_content(SourceRequest(url=source_url), cache_key=source_url)
    except Exception as exc:
        raise _handle_source_error(exc) from exc
    return RedirectResponse(
        target,
        status_code=303,
        headers={"Cache-Control": "public, max-age=86400"},
    )


@app.post("/t", response_model=TelegraphResponse, openapi_extra=_source_request_openapi())
async def telegraph_from_post(request: Request) -> JSONResponse:
    source = await _request_data(request)
    if not source.access_token:
        source = source.model_copy(update={"access_token": _authorization_token(request) or None})
    try:
        target = publish_content(source)
    except Exception as exc:
        raise _handle_source_error(exc) from exc
    return JSONResponse({"url": target})


@app.post("/t/bookmarklet")
async def telegraph_from_bookmarklet(request: Request) -> RedirectResponse:
    source = await _request_data(request)
    if not source.access_token:
        source = source.model_copy(update={"access_token": _authorization_token(request) or None})
    try:
        target = publish_content(source)
    except Exception as exc:
        raise _handle_source_error(exc) from exc
    return RedirectResponse(target, status_code=303)


@app.get("/bookmarklet/capture", response_class=HTMLResponse, include_in_schema=False)
def bookmarklet_capture(request: Request, action: str) -> HTMLResponse:
    """Receive an X bookmarklet capture after its cross-origin page traversal."""
    if action not in {"md", "t"}:
        raise HTTPException(status_code=404, detail="Unknown bookmarklet action")
    target = "/md" if action == "md" else "/t/bookmarklet"
    return templates.TemplateResponse(
        request=request,
        name="bookmarklet_capture.html",
        context={"target": target},
    )


@app.get("/bookmarklet/", response_class=HTMLResponse)
def bookmarklet_form(request: Request) -> HTMLResponse:
    try:
        bookmarks = build_bookmarklets(str(request.base_url).rstrip("/"))
    except Exception as exc:
        raise _handle_source_error(exc) from exc
    return templates.TemplateResponse(
        request=request,
        name="bookmarklet.html",
        context={"bookmarklets": bookmarks, "site_url": SITE_URL},
    )


@app.get("/bookmarklets/", response_class=HTMLResponse, include_in_schema=False)
def bookmarklets_form(request: Request) -> HTMLResponse:
    return bookmarklet_form(request)
