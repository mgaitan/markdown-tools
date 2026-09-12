"""Application services shared by HTTP routes and bookmarklets."""

from __future__ import annotations

import base64
import binascii
import hashlib
import hmac
import io
import json
import os
import re
import secrets
import threading
import time
from collections.abc import Mapping
from dataclasses import dataclass, replace
from pathlib import Path
from urllib.parse import urlparse

import anydoc
import requests
import yaml
from markdown_this import add_front_matter, extract_main_content, markdown_to_text, split_front_matter
from md_to_epub import Book, Chapter, build_epub
from md_to_telegraph import (
    TELEGRAPH_PAGE_MAX_CHARS,
    TelegraphPages,
    create_account,
    create_page,
    create_pages,
    edit_page,
    page_navigation,
    split_markdown_pages,
)
from md_to_telegraph.markdown import extract_leading_title
from PIL import Image, ImageOps
from PIL.Image import UnidentifiedImageError
from pypdf import PdfReader, PdfWriter

from markdown_web.schemas import SourceMetadata, SourceRequest
from markdown_web.telegram import send_telegram_notifications

DEFAULT_ACCOUNT_NAME = "page-to-telegraph"
DEFAULT_AUTHOR_NAME = "page-to-telegraph"
TELEGRAPH_API_URL = "https://api.telegra.ph"
TELEGRAPH_PAGE_LIST_LIMIT = 200
TELEGRAPH_REQUEST_TIMEOUT = 20
TELEGRAPH_PAGE_HOST = "telegra.ph"
FIRECRAWL_PARSE_URL = "https://api.firecrawl.dev/v2/parse"
FIRECRAWL_PARSE_TIMEOUT = 300
PREVIEW_TITLE_PREFIX = "[Preview] "
PREVIEW_TTL_SECONDS = 7 * 24 * 60 * 60
MAX_DOCUMENT_BYTES = 50 * 1024 * 1024
DOCUMENT_EXTENSIONS = frozenset(
    {
        "doc",
        "docx",
        "docm",
        "ppt",
        "pptx",
        "pptm",
        "xls",
        "xlsx",
        "xlsm",
        "odt",
        "ods",
        "odp",
        "rtf",
        "epub",
        "csv",
        "pdf",
    }
)
CARD_DIRECTIVE_RE = re.compile(r"!\[card\]\(\s*(https?://[^)\s]+)\s*\)")
CONTINUATION_PAGE_RE = re.compile(r"\s+\((\d+)/(\d+)\)$")
OCR_ERROR_RE = re.compile(r"pages?\s+(.+?)\s+of\s+\d+\s+need OCR", re.IGNORECASE)
OCR_ERROR_TYPES = tuple(
    error_type
    for error_type in (anydoc.UnsupportedError, getattr(anydoc, "NeedsOcrError", None))
    if error_type is not None
)


def _front_matter_notify_telegram(markdown: str) -> str:
    """Read the app-specific notification setting from Markdown front matter."""
    lines = markdown.splitlines()
    if not lines or lines[0].strip() != "---":
        return ""
    try:
        end = lines.index("---", 1)
        loaded = yaml.safe_load("\n".join(lines[1:end])) or {}
    except (ValueError, yaml.YAMLError):
        return ""
    if not isinstance(loaded, Mapping):
        return ""
    value = loaded.get("notify_telegram")
    return str(value).strip() if value is not None and not isinstance(value, (dict, list)) else ""


class SourceError(ValueError):
    """Raised when a request does not contain a usable source."""


class MissingSourceError(SourceError):
    """Raised when a request contains no URL, HTML, or Markdown."""

    def __init__(self) -> None:
        super().__init__("Provide one of url, html, or markdown")


class InvalidURLSourceError(SourceError):
    """Raised when a URL source is not an HTTP(S) URL."""

    def __init__(self) -> None:
        super().__init__("URL sources must use http or https")


class InvalidPreviewError(SourceError):
    """Raised when a preview identifier is expired or not signed by this service."""

    def __init__(self) -> None:
        super().__init__("Preview expired or invalid")


class InvalidPreviewURLError(SourceError):
    """Raised when an inline preview target is not a Telegraph page."""

    def __init__(self) -> None:
        super().__init__("Preview URL must be a Telegraph page")


class PreviewIdRequiredError(SourceError):
    """Raised when final publication is requested without a preview identifier."""

    def __init__(self) -> None:
        super().__init__("Preview id is required")


class PreviewUnsupportedError(SourceError):
    """Raised when preview is requested for a bulletin with article cards."""

    def __init__(self) -> None:
        super().__init__("Previews for bulletins are not supported yet")


class DocumentSourceError(SourceError):
    """Raised when a document cannot be converted to Markdown."""


class EmptyDocumentError(DocumentSourceError):
    def __init__(self) -> None:
        super().__init__("Uploaded document is empty")


class DocumentTooLargeError(DocumentSourceError):
    def __init__(self) -> None:
        super().__init__("Documents must be 50 MB or smaller")


class DocumentConversionError(DocumentSourceError):
    def __init__(self, detail: Exception) -> None:
        super().__init__(f"Could not convert document: {detail}")


class EmptyDocumentContentError(DocumentSourceError):
    def __init__(self) -> None:
        super().__init__("Document did not contain readable content")


class DocumentDownloadError(DocumentSourceError):
    def __init__(self) -> None:
        super().__init__("Could not download document")


class SourceHTTPError(SourceError):
    """Raised when a source responds with an HTTP error."""

    def __init__(self, status: int) -> None:
        if status in {401, 403}:
            message = f"Source denied server access (HTTP {status}). Send the page HTML through /bookmarklet/ instead."
        else:
            message = f"Source returned HTTP {status}"
        super().__init__(message)


class TelegraphAPIError(RuntimeError):
    """Raised when Telegraph cannot return a valid API response."""

    def __init__(self) -> None:
        super().__init__("Could not read the Telegraph page list")


class TelegraphPreviewError(RuntimeError):
    """Raised when the server cannot load a Telegraph page for an inline preview."""

    def __init__(self) -> None:
        super().__init__("Could not load the Telegraph preview")


@dataclass(frozen=True)
class PreparedContent:
    """Normalized content ready for Markdown output or Telegraph."""

    title: str
    markdown: str
    fallback_text: str
    metadata: SourceMetadata
    intro: str = ""


@dataclass(frozen=True)
class PublishedBriefArticle:
    """An extracted article and the Telegraph page created for this brief."""

    source_url: str
    content: PreparedContent
    telegraph_url: str
    telegraph_urls: tuple[str, ...] = ()
    page_markdowns: tuple[str, ...] = ()


def _is_preview_page(page: dict[str, object]) -> bool:
    title = page.get("title")
    return isinstance(title, str) and title.startswith(PREVIEW_TITLE_PREFIX)


def list_published_pages() -> tuple[int, list[dict[str, object]]]:
    """Return all pages published by the configured Telegraph account."""
    token = telegraph_tokens.resolve()
    pages: list[dict[str, object]] = []
    offset = 0
    total_count = 0

    while True:
        try:
            response = requests.get(
                f"{TELEGRAPH_API_URL}/getPageList",
                params={
                    "access_token": token,
                    "offset": offset,
                    "limit": TELEGRAPH_PAGE_LIST_LIMIT,
                },
                timeout=TELEGRAPH_REQUEST_TIMEOUT,
            )
            response.raise_for_status()
            payload = response.json()
        except (requests.RequestException, ValueError) as exc:
            raise TelegraphAPIError from exc

        if not isinstance(payload, dict) or not payload.get("ok"):
            raise TelegraphAPIError
        result = payload.get("result")
        if not isinstance(result, dict):
            raise TelegraphAPIError

        raw_total = result.get("total_count", 0)
        raw_pages = result.get("pages", [])
        if not isinstance(raw_total, int) or not isinstance(raw_pages, list):
            raise TelegraphAPIError
        total_count = raw_total
        pages.extend(page for page in raw_pages if isinstance(page, dict))

        if not raw_pages or len(pages) >= total_count:
            visible_pages = [page for page in pages if not _is_continuation_page(page) and not _is_preview_page(page)]
            return len(visible_pages), visible_pages
        offset += len(raw_pages)


def _is_continuation_page(page: dict[str, object]) -> bool:
    title = page.get("title")
    if not isinstance(title, str):
        return False
    match = CONTINUATION_PAGE_RE.search(title)
    return bool(match and int(match.group(1)) > 1 and int(match.group(2)) >= int(match.group(1)))


class TelegraphTokenStore:
    """Resolve tokens without putting Telegraph bearer tokens in bookmarklets."""

    def __init__(self) -> None:
        self._token = ""
        self._lock = threading.Lock()

    def resolve(self, explicit_token: str | None = None) -> str:
        if explicit_token:
            return explicit_token
        if environment_token := os.getenv("TELEGRAPH_API_TOKEN"):
            return environment_token
        if self._token:
            return self._token

        with self._lock:
            if not self._token:
                self._token = create_account(
                    short_name=os.getenv("TELEGRAPH_ACCOUNT_SHORT_NAME", DEFAULT_ACCOUNT_NAME)[:32],
                    author_name=os.getenv("TELEGRAPH_ACCOUNT_AUTHOR", DEFAULT_AUTHOR_NAME),
                    author_url=os.getenv("TELEGRAPH_ACCOUNT_AUTHOR_URL", ""),
                )
        return self._token


telegraph_tokens = TelegraphTokenStore()
published_urls: dict[str, str] = {}
published_urls_lock = threading.Lock()


def _require_source(request: SourceRequest) -> str:
    if request.url:
        parsed = urlparse(request.url)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            raise InvalidURLSourceError
        return request.url
    if request.html is not None:
        return request.html
    if request.markdown is not None:
        return request.markdown
    raise MissingSourceError


def _is_document_url(url: str) -> bool:
    suffix = Path(urlparse(url).path).suffix.lower().lstrip(".")
    return suffix in DOCUMENT_EXTENSIONS


IMAGE_EXTENSIONS = frozenset({"bmp", "gif", "heic", "heif", "jpeg", "jpg", "png", "tif", "tiff", "webp"})


def _image_to_pdf(data: bytes) -> bytes:
    try:
        with Image.open(io.BytesIO(data)) as source_image:
            image = ImageOps.exif_transpose(source_image).convert("RGB")
            output = io.BytesIO()
            image.save(output, format="PDF")
            return output.getvalue()
    except (OSError, UnidentifiedImageError, ValueError) as exc:
        raise DocumentConversionError(exc) from exc


def ocr_image(data: bytes, filename: str) -> str:
    """Extract text from an uploaded image through the configured OCR fallback."""
    if not os.getenv("FIRECRAWL_API_KEY"):
        raise DocumentConversionError(RuntimeError("Image OCR requires FIRECRAWL_API_KEY"))
    pdf = _image_to_pdf(data)
    pdf_filename = f"{Path(filename).stem or 'image'}.pdf"
    return _convert_pdf_with_hosted_ocr(pdf, pdf_filename)


def _convert_document(data: bytes, filename: str) -> str:
    if not data:
        raise EmptyDocumentError
    if len(data) > MAX_DOCUMENT_BYTES:
        raise DocumentTooLargeError
    extension = Path(filename).suffix.lower().lstrip(".")
    document_format = anydoc.format_from_extension(extension) if extension else None
    try:
        markdown = anydoc.to_markdown_bytes(data, document_format)
    except (anydoc.ConvertError, OSError, ValueError) as exc:
        if document_format == "pdf" and _is_ocr_error(exc):
            if os.getenv("FIRECRAWL_API_KEY"):
                return _convert_pdf_with_hosted_ocr(data, filename)
            return _convert_pdf_pages(data, exc)
        raise DocumentConversionError(exc) from exc
    if not markdown.strip():
        raise EmptyDocumentContentError
    return markdown


def _convert_pdf_with_hosted_ocr(data: bytes, filename: str) -> str:
    """Convert an OCR-required PDF with Firecrawl Parse after local AnyDoc fails."""
    api_key = os.environ["FIRECRAWL_API_KEY"]
    options = {
        "formats": ["markdown"],
        "parsers": [{"type": "pdf", "mode": "auto"}],
    }
    try:
        response = requests.post(
            os.getenv("FIRECRAWL_PARSE_URL", FIRECRAWL_PARSE_URL),
            headers={"Authorization": f"Bearer {api_key}"},
            data={"options": json.dumps(options)},
            files={"file": (filename, data, "application/pdf")},
            timeout=FIRECRAWL_PARSE_TIMEOUT,
        )
        response.raise_for_status()
        payload = response.json()
    except (requests.RequestException, ValueError) as exc:
        raise DocumentConversionError(exc) from exc

    markdown = payload.get("data", {}).get("markdown") if isinstance(payload, dict) else None
    if not isinstance(markdown, str) or not markdown.strip():
        raise DocumentConversionError(ValueError("Firecrawl did not return Markdown"))
    return markdown


def _convert_pdf_pages(data: bytes, original_error: Exception) -> str:
    """Keep readable PDF pages when AnyDoc rejects scanned pages that need OCR."""
    try:
        reader = PdfReader(io.BytesIO(data))
        converted: list[tuple[int, str]] = []
        skipped: list[int] = []
        for page_number, page in enumerate(reader.pages, 1):
            writer = PdfWriter()
            writer.add_page(page)
            page_data = io.BytesIO()
            writer.write(page_data)
            try:
                page_markdown = anydoc.to_markdown_bytes(page_data.getvalue(), "pdf")
            except OCR_ERROR_TYPES as exc:
                if _is_ocr_error(exc):
                    skipped.append(page_number)
                    continue
                raise
            if page_markdown.strip():
                converted.append((page_number, page_markdown.strip()))
            else:
                skipped.append(page_number)
    except (anydoc.ConvertError, OSError, ValueError) as exc:
        raise DocumentConversionError(exc) from exc
    except Exception as exc:
        raise DocumentConversionError(exc) from exc

    if not converted:
        raise DocumentConversionError(original_error) from original_error

    parts = [f"<!-- Page {page_number} -->\n\n{page_markdown}" for page_number, page_markdown in converted]
    if skipped:
        pages = ", ".join(str(page_number) for page_number in skipped)
        warning = f"> **Contenido incompleto:** se omitieron las páginas {pages} porque requieren OCR."
        parts.insert(0, warning)
    return "\n\n---\n\n".join(parts)


def _is_ocr_error(exc: Exception) -> bool:
    message = str(exc).lower()
    return isinstance(exc, OCR_ERROR_TYPES) and (
        OCR_ERROR_RE.search(message)
        or "ocr" in message
        or "scanned" in message
        or "imagebased" in message
        or "no extractable text" in message
    )


def _download_document(url: str) -> tuple[bytes, str]:
    try:
        response = requests.get(url, timeout=TELEGRAPH_REQUEST_TIMEOUT, headers={"User-Agent": "markdown-web"})
        response.raise_for_status()
    except requests.RequestException as exc:
        raise DocumentDownloadError from exc
    filename = Path(urlparse(url).path).name or "document"
    return response.content, filename


def fetch_telegraph_preview(url: str) -> str:
    """Fetch a Telegraph page so browsers can display it same-origin in an iframe."""
    parsed = urlparse(url)
    if parsed.scheme != "https" or parsed.netloc != TELEGRAPH_PAGE_HOST or not parsed.path:
        raise InvalidPreviewURLError
    try:
        response = requests.get(url, timeout=TELEGRAPH_REQUEST_TIMEOUT, headers={"User-Agent": "markdown-web"})
        response.raise_for_status()
    except requests.RequestException as exc:
        raise TelegraphPreviewError from exc
    page = response.text
    base_tag = '<base href="https://telegra.ph/">'
    if re.search(r"<base\b", page, re.IGNORECASE):
        return page
    return re.sub(r"(<head\b[^>]*>)", rf"\1{base_tag}", page, count=1, flags=re.IGNORECASE) or f"{base_tag}{page}"


def _merge_metadata(markdown: str, supplied: SourceMetadata) -> tuple[str, SourceMetadata]:
    existing, body = split_front_matter(markdown.strip())
    merged = {**existing, **supplied.values()}
    if notify_telegram := _front_matter_notify_telegram(markdown):
        merged.setdefault("notify_telegram", notify_telegram)
    return add_front_matter(body, merged), SourceMetadata.model_validate(merged)


def prepare_content(request: SourceRequest) -> PreparedContent:
    """Extract and normalize a request into Markdown with YAML front matter."""
    if request.url:
        _require_source(request)
    if request.document is not None or (request.url and _is_document_url(request.url)):
        document, filename = (
            (request.document, request.filename)
            if request.document is not None
            else _download_document(request.url or "")
        )
        markdown = _convert_document(document or b"", filename)
        metadata = request.metadata
        if request.url and not metadata.url:
            metadata = metadata.model_copy(update={"url": request.url})
        if not metadata.title and filename:
            metadata = metadata.model_copy(update={"title": Path(filename).stem})
        front_matter, body = split_front_matter(markdown.strip())
        title = metadata.title or front_matter.get("title", "") or Path(filename).stem or "Document"
        fallback_text = markdown_to_text(body)
        intro = ""
    elif request.url:
        try:
            title, markdown, fallback_text, intro = extract_main_content(request.url)
        except requests.HTTPError as exc:
            status = exc.response.status_code if exc.response is not None else 0
            raise SourceHTTPError(status) from exc
        metadata = request.metadata
    elif request.html is not None:
        title, markdown, fallback_text, intro = extract_main_content(
            request.html, source_url=request.metadata.url or ""
        )
        metadata = request.metadata
    else:
        source = _require_source(request)
        front_matter, body = split_front_matter(source.strip())
        title = front_matter.get("title", "")
        markdown = source
        fallback_text = markdown_to_text(body)
        metadata = request.metadata
        intro = ""

    markdown, metadata = _merge_metadata(markdown, metadata)
    title = metadata.title or title
    return PreparedContent(
        title=title,
        markdown=markdown,
        fallback_text=fallback_text,
        metadata=metadata,
        intro=intro,
    )


def _publish_prepared_pages(prepared: PreparedContent, token: str, *, warm_cache: bool = True) -> TelegraphPages:
    chunks = split_markdown_pages(prepared.markdown, max_chars=TELEGRAPH_PAGE_MAX_CHARS)
    if len(chunks) == 1:
        url = create_page(
            title=prepared.title or None,
            content_markdown=prepared.markdown,
            fallback_text=prepared.fallback_text,
            source_url=prepared.metadata.url,
            author_name=prepared.metadata.author,
            access_token=token,
            warm_cache=warm_cache,
        )
        return TelegraphPages((url,), (prepared.markdown,))
    return create_pages(
        title=prepared.title or None,
        content_markdown=prepared.markdown,
        fallback_text=prepared.fallback_text,
        source_url=prepared.metadata.url,
        author_name=prepared.metadata.author,
        access_token=token,
        max_chars=TELEGRAPH_PAGE_MAX_CHARS,
        warm_cache=warm_cache,
    )


def _preview_secret(token: str) -> bytes:
    return token.encode("utf-8")


def _encode_preview_id(urls: tuple[str, ...], token: str) -> str:
    payload = {
        "expires_at": int(time.time()) + PREVIEW_TTL_SECONDS,
        "nonce": secrets.token_urlsafe(12),
        "urls": urls,
    }
    encoded = base64.urlsafe_b64encode(json.dumps(payload, separators=(",", ":")).encode()).decode().rstrip("=")
    signature = hmac.new(_preview_secret(token), encoded.encode(), hashlib.sha256).hexdigest()
    return f"{encoded}.{signature}"


def _decode_preview_id(preview_id: str, token: str) -> tuple[str, ...]:
    try:
        encoded, signature = preview_id.rsplit(".", 1)
    except ValueError as exc:
        raise InvalidPreviewError from exc
    expected = hmac.new(_preview_secret(token), encoded.encode(), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(signature, expected):
        raise InvalidPreviewError

    padding = "=" * (-len(encoded) % 4)
    try:
        payload = json.loads(base64.urlsafe_b64decode(encoded + padding))
    except (binascii.Error, TypeError, ValueError) as exc:
        raise InvalidPreviewError from exc
    if not isinstance(payload, dict):
        raise InvalidPreviewError
    try:
        expires_at = int(payload["expires_at"])
        urls = tuple(payload["urls"])
    except (KeyError, TypeError, ValueError) as exc:
        raise InvalidPreviewError from exc
    if expires_at < int(time.time()) or not urls or any(urlparse(url).netloc != "telegra.ph" for url in urls):
        raise InvalidPreviewError
    return urls


def _preview_page_markdowns(prepared: PreparedContent) -> tuple[str, ...]:
    metadata, _body = split_front_matter(prepared.markdown.strip())
    chunks = split_markdown_pages(prepared.markdown, max_chars=TELEGRAPH_PAGE_MAX_CHARS)
    if len(chunks) == 1:
        return (prepared.markdown,)
    if not metadata:
        return tuple(chunks)
    front_matter = yaml.safe_dump(metadata, allow_unicode=True, sort_keys=False).strip()
    return tuple(f"---\n{front_matter}\n---\n\n{chunk}" for chunk in chunks)


def _prepared_page_title(prepared: PreparedContent) -> str:
    _metadata, body = split_front_matter(prepared.markdown.strip())
    return prepared.title or extract_leading_title(body) or "Document"


def _preview_page_title(title: str, *, preview: bool, index: int, total: int) -> str:
    base_title = f"{PREVIEW_TITLE_PREFIX}{title}" if preview else title
    return base_title if index == 0 else f"{base_title} ({index + 1}/{total})"


def _edit_preview_pages(
    prepared: PreparedContent,
    token: str,
    existing_urls: tuple[str, ...],
    *,
    preview: bool,
) -> TelegraphPages:
    page_markdowns = _preview_page_markdowns(prepared)
    page_title = _prepared_page_title(prepared)
    if not existing_urls and len(page_markdowns) == 1:
        url = create_page(
            title=_preview_page_title(page_title, preview=preview, index=0, total=1),
            content_markdown=page_markdowns[0],
            fallback_text=prepared.fallback_text,
            source_url=prepared.metadata.url,
            author_name=prepared.metadata.author,
            access_token=token,
        )
        return TelegraphPages((url,), page_markdowns)

    urls = list(existing_urls)
    total = len(page_markdowns)
    while len(urls) < total:
        index = len(urls)
        urls.append(
            create_page(
                title=_preview_page_title(page_title, preview=preview, index=index, total=total),
                content_markdown=page_markdowns[index],
                fallback_text=prepared.fallback_text if index == 0 else "",
                source_url=prepared.metadata.url,
                author_name=prepared.metadata.author,
                access_token=token,
                warm_cache=False,
            )
        )

    active_urls = tuple(urls[:total])
    for index, (url, page_markdown) in enumerate(zip(active_urls, page_markdowns, strict=True)):
        content = page_markdown
        if total > 1:
            content += page_navigation(active_urls, index)
        edit_page(
            path=urlparse(url).path.lstrip("/"),
            title=_preview_page_title(page_title, preview=preview, index=index, total=total),
            content_markdown=content,
            fallback_text=prepared.fallback_text if index == 0 else "",
            source_url=prepared.metadata.url,
            author_name=prepared.metadata.author,
            access_token=token,
        )
    return TelegraphPages(active_urls, page_markdowns)


def preview_content(request: SourceRequest) -> tuple[str, str]:
    """Create or update a public Telegraph preview and return its id and URL."""
    if request.markdown and CARD_DIRECTIVE_RE.search(request.markdown):
        raise PreviewUnsupportedError
    prepared = prepare_content(request)
    token = telegraph_tokens.resolve(request.access_token)
    existing_urls = _decode_preview_id(request.preview_id, token) if request.preview_id else ()
    pages = _edit_preview_pages(prepared, token, existing_urls, preview=True)
    return _encode_preview_id(pages.urls, token), pages.urls[0]


def _publish_preview(request: SourceRequest) -> str:
    if not request.preview_id:
        raise PreviewIdRequiredError
    if request.markdown and CARD_DIRECTIVE_RE.search(request.markdown):
        raise PreviewUnsupportedError
    prepared = prepare_content(request)
    token = telegraph_tokens.resolve(request.access_token)
    pages = _edit_preview_pages(prepared, token, _decode_preview_id(request.preview_id, token), preview=False)
    send_telegram_notifications(pages.urls[0], prepared.metadata.notify_telegram)
    return pages.urls[0]


def _publish_prepared(prepared: PreparedContent, token: str, *, warm_cache: bool = True) -> str:
    return _publish_prepared_pages(prepared, token, warm_cache=warm_cache).urls[0]


def _publish_content(request: SourceRequest) -> str:
    """Publish request content to Telegraph and return its public URL."""
    prepared = prepare_content(request)
    token = telegraph_tokens.resolve(request.access_token)
    target = _publish_prepared(prepared, token)
    send_telegram_notifications(target, prepared.metadata.notify_telegram)
    return target


def _escape_markdown_text(value: str) -> str:
    return value.replace("\\", "\\\\").replace("[", "\\[").replace("]", "\\]")


def _card_markdown(article: PublishedBriefArticle, link_marker: str) -> str:
    """Render a card image and leave its Telegraph link for the note's end."""
    title = _escape_markdown_text(article.content.title or article.source_url)
    parts: list[str] = []
    if image_url := article.content.metadata.image:
        parts.append(f"[![{title}]({image_url})]({article.telegraph_url})")
    parts.append(link_marker)
    return "\n\n".join(parts)


def _add_card_links_at_note_end(markdown: str, links: list[tuple[str, str]]) -> str:
    """Move generated Telegraph links below each note's editorial paragraphs."""
    for marker, url in links:
        before, found, after = markdown.partition(marker)
        if not found:
            continue
        boundary = re.search(r"\n\n---\n|\n## |\Z", after)
        end = boundary.start() if boundary else len(after)
        note = after[:end].strip()
        suffix = after[end:]
        markdown = f"{before.rstrip()}\n\n{note}\n\n[Leer en Telegraph]({url}){suffix}"
    return markdown


def _navigation_markdown(
    brief_url: str,
    previous_url: str | None,
    next_url: str | None,
) -> str:
    links: list[str] = []
    if previous_url:
        links.append(f"[Artículo anterior]({previous_url})")
    links.append(f"[Volver al boletín]({brief_url})")
    if next_url:
        links.append(f"[Artículo siguiente]({next_url})")
    return "\n\n---\n\n" + " | ".join(links)


def card_source_urls(markdown: str) -> list[str]:
    """Return unique card source URLs in their first-seen order."""
    return list(dict.fromkeys(CARD_DIRECTIVE_RE.findall(markdown)))


def build_epub_content(request: SourceRequest) -> tuple[bytes, str]:
    """Build an EPUB from one source or a brief with article cards."""
    prepared = prepare_content(request)
    source_urls = card_source_urls(prepared.markdown)
    articles = {url: prepare_content(SourceRequest(url=url)) for url in source_urls}

    def replace_card(match: re.Match[str]) -> str:
        article = articles[match.group(1)]
        title = _escape_markdown_text(article.title or match.group(1))
        return f"[{title}]({match.group(1)})"

    brief_markdown = CARD_DIRECTIVE_RE.sub(replace_card, prepared.markdown)
    chapters = [
        Chapter(
            title=prepared.title or "Document",
            markdown=brief_markdown,
            source_url=prepared.metadata.url,
        )
    ]
    chapters.extend(
        Chapter(
            title=article.title or source_url,
            markdown=article.markdown,
            source_url=article.metadata.url or source_url,
        )
        for source_url, article in articles.items()
    )
    book = Book(
        title=prepared.title or "Document",
        author=prepared.metadata.author,
        chapters=tuple(chapters),
    )
    filename = re.sub(r"[^A-Za-z0-9]+", "-", book.title).strip("-").lower() or "book"
    return build_epub(book), f"{filename}.epub"


def publish_brief_article(source_url: str, token: str, *, warm_cache: bool = True) -> PublishedBriefArticle:
    """Extract and publish one article referenced by a brief."""
    content = prepare_content(SourceRequest(url=source_url))
    pages = _publish_prepared_pages(content, token, warm_cache=warm_cache)
    return PublishedBriefArticle(
        source_url=source_url,
        content=content,
        telegraph_url=pages.urls[0],
        telegraph_urls=pages.urls,
        page_markdowns=pages.markdowns,
    )


def publish_brief_page(
    brief: PreparedContent,
    articles: list[PublishedBriefArticle],
    token: str,
    *,
    warm_cache: bool = True,
) -> str:
    """Expand article cards and publish the parent brief."""
    articles_by_source = {article.source_url: article for article in articles}
    links: list[tuple[str, str]] = []

    def expand_card(match: re.Match[str]) -> str:
        article = articles_by_source[match.group(1)]
        link_marker = f"<!-- telegraph-link-{len(links)} -->"
        links.append((link_marker, article.telegraph_url))
        return _card_markdown(article, link_marker)

    expanded_markdown = CARD_DIRECTIVE_RE.sub(
        expand_card,
        brief.markdown,
    )
    expanded_markdown = _add_card_links_at_note_end(expanded_markdown, links)
    return _publish_prepared(replace(brief, markdown=expanded_markdown), token, warm_cache=warm_cache)


def add_brief_navigation(  # noqa: PLR0913
    article: PublishedBriefArticle,
    index: int,
    articles: list[PublishedBriefArticle],
    brief_url: str,
    token: str,
    *,
    warm_cache: bool = True,
) -> str:
    """Add parent, previous, and next links to one published article."""
    previous_url = articles[index - 1].telegraph_url if index else None
    next_url = articles[index + 1].telegraph_url if index + 1 < len(articles) else None
    page_markdown = article.page_markdowns[0] if article.page_markdowns else article.content.markdown
    page_urls = article.telegraph_urls or (article.telegraph_url,)
    return edit_page(
        path=urlparse(article.telegraph_url).path.lstrip("/"),
        title=article.content.title or None,
        content_markdown=(
            page_markdown + page_navigation(page_urls, 0) + _navigation_markdown(brief_url, previous_url, next_url)
        ),
        fallback_text=markdown_to_text(page_markdown),
        source_url=article.content.metadata.url or article.source_url,
        author_name=article.content.metadata.author,
        access_token=token,
        warm_cache=warm_cache,
    )


def _publish_brief(request: SourceRequest) -> str:
    brief = prepare_content(request)
    token = telegraph_tokens.resolve(request.access_token)
    articles = [publish_brief_article(source_url, token) for source_url in card_source_urls(brief.markdown)]
    brief_url = publish_brief_page(brief, articles, token)

    for index, article in enumerate(articles):
        add_brief_navigation(article, index, articles, brief_url, token)
    send_telegram_notifications(brief_url, brief.metadata.notify_telegram)
    return brief_url


def publish_content(
    request: SourceRequest,
    cache_key: str | None = None,
) -> str:
    """Publish content, optionally reusing the Telegraph page for a source URL."""
    if request.preview_id:
        return _publish_preview(request)
    if request.markdown and CARD_DIRECTIVE_RE.search(request.markdown):
        return _publish_brief(request)
    if not cache_key:
        return _publish_content(request)

    with published_urls_lock:
        if target := published_urls.get(cache_key):
            return target
        target = _publish_content(request)
        published_urls[cache_key] = target
        return target
