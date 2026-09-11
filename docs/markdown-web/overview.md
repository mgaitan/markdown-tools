# Overview

`markdown-web` is the browser-facing service in Markdown Tools. It combines
`markdown-this` for extraction with `md-to-telegraph` for Telegraph conversion
and `md-to-epub` for ebook export, and exposes the workflows through an HTTP
API, a small web interface, and bookmarklets.

## What It Does

The service can:

- Extract readable content from public URLs as Markdown.
- Accept pasted Markdown, raw HTML, local files, and uploaded documents.
- Extract browser-captured HTML when a source needs JavaScript or cannot be
  reached by the server.
- Convert Markdown into Telegraph pages, including long documents split across
  linked pages.
- Show a Telegraph preview before publication and let the user return to edit.
- Publish Markdown directly to Telegraph from the web editor.
- Export one Markdown document or a bulletin with article cards as an EPUB 3.
- Upload PNG, JPEG, and WebP images, optimize them to WebP, and return public
  URLs suitable for Markdown.
- Send an optional Telegraph link notification to Telegram users or channels.
- Publish long Markdown briefs as Redis-backed jobs.

The service does not replace the reusable packages. Extraction belongs to
`markdown-this`; Markdown-to-Telegraph conversion and Telegraph API calls
belong to `md-to-telegraph`; web orchestration, uploads, jobs, and Telegram
notifications stay here.

## Web Interface

The home page accepts a URL, Markdown, or a file. A selected or dropped file
starts processing automatically. Markdown can be edited before conversion, and
the draft is kept in the browser while the page remains open.

HTML uploads with `.html` or `.htm` extensions are extracted as HTML. Pasted
HTML is extracted when it starts with a complete document or a structural
fragment (`article`, `body`, `main`, `section`, or `div`); Markdown and prose
that contain HTML later in the text remain Markdown.

The source action is remembered per browser:

- **Process** extracts or converts the source and opens the result for review.
- **Publish** performs the same preparation and publishes directly to
  Telegraph.

The preview uses a same-origin frame served by `/t/preview-frame`. This avoids
embedding Telegraph directly, which browsers may reject with an iframe
connection error, while keeping the preview isolated from the parent page.

Other browser pages are available from the footer:

- `/about` describes the service and its supported workflows.
- `/bookmarklets/` provides bookmarklets for rendered-page capture.
- `/t/published/` lists pages published through the service.
- `/docs` exposes the OpenAPI documentation.
- `/llms.txt` provides a machine-readable description for agents.

## HTTP API

### Markdown

Extract a URL with:

```text
GET /md/{url}
```

For URLs, raw HTML, Markdown, local files, or browser captures, send a source
request to:

```text
POST /md
```

The response is Markdown text. Browser-supplied HTML should include its
original `source_url` so relative links and images can be normalized against
the source document.

### Telegraph

Publish a URL directly:

```text
GET /t/{url}
```

Publish a URL, Markdown document, raw HTML, or uploaded document:

```text
POST /t
```

Create or update a preview:

```text
POST /t/preview
```

The response includes a preview identifier and page URL. Send that identifier
back when publishing so the service can update the preview pages instead of
creating a second set of pages.

### EPUB

Export a URL, Markdown document, raw HTML, or uploaded document as an EPUB 3:

```text
POST /epub
```

The endpoint accepts the same source request as `POST /md`. A Markdown brief
with `![card](https://example.com/article)` markers becomes a book with the
brief and its extracted child articles as navigable chapters. Remote images are
embedded in the EPUB, and source URLs remain visible in each chapter.

For a rendered browser capture, use:

```text
POST /t/bookmarklet
```

### Images

Upload an image with:

```text
POST /images
```

The service validates the image type, converts it to WebP when possible, and
returns a public URL. R2-backed storage is enabled when the R2 environment
variables are configured.

### Long jobs

For a long Markdown brief, create a job with:

```text
POST /t/jobs
GET /t/jobs/{job_id}
POST /t/jobs/{job_id}/run
```

Redis is optional. When `REDIS_URL` is configured, the job state and staged
publishing flow survive individual requests.

## Telegram Notifications

Extracted Markdown may contain a `notify_telegram` front-matter field with
comma-separated user or channel IDs. After publication, the configured
Telegram bot sends the Telegraph link to those recipients. The bot must be
started by a private user, or added with permission to post in a group or
channel.

Telegram is an external service, just like Telegraph. The web package sends
notifications through its integration but does not own either service or its
content.

## Deployment Configuration

The minimum configuration for URL-to-Telegraph publication is:

- `TELEGRAPH_API_TOKEN`: an existing Telegraph account token.

Optional integrations use:

- `REDIS_URL` for durable publishing jobs.
- `TELEGRAM_WEB_BOT_TOKEN` for notifications.
- `R2_ACCOUNT_ID`, `R2_BUCKET_NAME`, `R2_ACCESS_KEY_ID`,
  `R2_SECRET_ACCESS_KEY`, and `R2_PUBLIC_BASE_URL` for image storage.

Run the service locally with:

```bash
uv run --package markdown-web markdown-web
```

Then open <http://127.0.0.1:8000/>. For API details, use the generated
Swagger UI at `/docs` or ReDoc at `/redoc`.
