# Markdown-web

Minimal FastAPI service around [`markdown-this`](../markdown-this/) and
[`md-to-telegraph`](../md-to-telegraph/), with EPUB export through
[`md-to-epub`](../md-to-epub/).

## Run

```bash
uv run --package markdown-web markdown-web
```

Open <http://127.0.0.1:8000/>. Set `TELEGRAPH_API_TOKEN` to use an existing
Telegraph account. When it is absent, the service creates one lazily and keeps
the token in memory for the lifetime of the process. Set `REDIS_URL` to enable
durable publishing jobs; without it, synchronous publishing continues to work.

## HTTP API

The URL is a path, in the style of `r.jina.ai`:

```bash
curl http://127.0.0.1:8000/md/https://example.com/article
curl -L http://127.0.0.1:8000/t/https://example.com/article
```

GET `/t/<url>` reuses the Telegraph page already created for that source URL
by this running service. POST `/t` always publishes the supplied content.
GET `/t/published/` lists the pages published by the configured Telegraph account.
The original source is shown when Telegraph has it in the page's author URL.

The home page also accepts document uploads. The web package uses
[`firecrawl-anydoc`](https://github.com/firecrawl/anydoc) to convert PDF, Word,
PowerPoint, Excel, OpenDocument, RTF, EPUB, and CSV files to Markdown. Uploads
are limited to 50 MB. URLs ending in one of those document extensions are
converted through the same path.

Document conversion is local by default. When AnyDoc detects that a PDF needs
OCR and `FIRECRAWL_API_KEY` is configured, the service sends that PDF to
Firecrawl Parse with the PDF parser in `auto` mode, which keeps text extraction
as the default and uses hosted OCR where necessary. Firecrawl's API receives
the complete PDF: it cannot receive only the scanned pages. Documents that
convert locally never leave the service. Without the key, PDFs with a mixture
of readable and scanned pages keep their readable pages and include a visible
Markdown warning listing the omitted pages.

The target URL should be URL-encoded when it contains characters that have a
meaning to the web server. POST endpoints accept JSON with a URL, raw HTML, or
Markdown:

```bash
curl -X POST http://127.0.0.1:8000/md \
  -H 'content-type: application/json' \
  -d '{"html":"<h1>Hello</h1><p>Body</p>","metadata":{"url":"https://example.com"}}'

curl -X POST http://127.0.0.1:8000/t \
  -H 'content-type: application/json' \
  -d '{"markdown":"# Hello\n\nBody"}'

curl -X POST http://127.0.0.1:8000/epub \
  -H 'content-type: application/json' \
  -d '{"markdown":"# Hello\n\nBody"}' \
  -o hello.epub
```

`POST /epub` returns an EPUB 3 download. A Markdown brief using
`![card](https://example.com/article)` markers becomes a book with the brief
as its first chapter and one chapter per linked article.

Raw HTML can also be posted as `text/html`. Optional metadata is supplied with
`X-Source-URL`, `X-Title`, `X-Author-Name`, `X-Published-Date`, and `X-Image-URL`.
An `access_token` JSON field or `Authorization` header can select a Telegraph
account; otherwise the server token is used.

Documents can be posted as multipart form data using the `file` field:

```bash
curl -X POST http://127.0.0.1:8000/md \
  -F 'file=@report.epub'
```

PNG, JPEG, and WebP images use `POST /images` instead of AnyDoc. The service
validates them, resizes the longest side to 1280 pixels, converts them to WebP,
and returns a public URL suitable for `![](url)` in Markdown. Input images are
limited to 20 MB; Redis-backed quotas allow up to 10 uploads per IP per hour
and 50 MB globally per UTC day. Image uploads also require the R2 settings
`R2_ACCOUNT_ID`, `R2_BUCKET_NAME`, `R2_ACCESS_KEY_ID`, `R2_SECRET_ACCESS_KEY`,
and `R2_PUBLIC_BASE_URL`.

Audio files can be uploaded from the home page or recorded with its microphone
button. `POST /transcriptions` returns `{"text": "..."}` and accepts files up
to 25 MB. By default it uses Groq's OpenAI-compatible transcription endpoint
with `whisper-large-v3-turbo`; set `GROQ_API_KEY` to enable it. To use another
compatible provider or model, configure `TRANSCRIPTION_API_KEY`,
`TRANSCRIPTION_API_URL`, and `TRANSCRIPTION_MODEL` instead.

Install the home page as a PWA to use it as an Android share target. Sharing an
audio file transcribes it into the editor; sharing a supported document converts
it to Markdown. Shared text and URLs open in the editor too. The PWA needs an
internet connection to process shared content.

The editor action menu can download the current document as Markdown or EPUB.

```bash
curl -X POST http://127.0.0.1:8000/transcriptions \
  -F 'file=@recording.webm'
```

Markdown front matter can also set `notify_telegram` to a comma-separated list
of Telegram user or channel IDs. After the Telegraph URL is created, the web
bot sends only that URL to each recipient. Notifications are best effort and
use the `TELEGRAM_WEB_BOT_TOKEN` environment variable. A private user must
start a conversation with [@MarkdownTelegraphBot](https://t.me/MarkdownTelegraphBot)
first; in a group the bot must be added with permission to send messages, and
in a channel it must be an administrator allowed to post messages.

To publish a brief with linked article pages, place exact lowercase card markers
in the Markdown:

```markdown
# Weekend brief

Editorial context.

![card](https://example.com/article)
```

`POST /t` publishes each marked source to Telegraph, replaces the marker with a
linked image, title, introduction, and Telegraph link, and adds navigation back
to the brief plus the previous and next curated articles. Marker order controls
navigation, and a repeated URL is published once within the brief.

### Optional jobs

For a long brief, `POST /t/jobs` accepts the same Markdown JSON body and returns
HTTP `202` with a job `id`, `status_url`, and `run_url`. Call `POST <run_url>`
until it returns HTTP `200` with `status: completed` and the final Telegraph
`url`. Each call advances one bounded publishing stage. `GET <status_url>` reads
progress without changing it.

Job state and locks are stored in Redis for 48 hours. Sending the same Markdown
and metadata during that period returns the same job. A failed stage returns
HTTP `422` with its error and source URL and can be retried by posting to the
same `run_url`. Jobs use the service's configured Telegraph account and reject
client access tokens. When `REDIS_URL` is absent, only the job endpoints return
HTTP `503`; `POST /t` continues to work synchronously.

```bash
curl -X POST http://127.0.0.1:8000/t/jobs \
  -H 'content-type: application/json' \
  -d '{"markdown":"# Weekend brief\n\n![card](https://example.com/article)"}'
```

Agents can read `/llms.txt` for the endpoint contract, accepted YAML front
matter, and examples. The machine-readable contract is FastAPI's existing
OpenAPI document at `/openapi.json`; there is no separate `openschema.json`.

Long Markdown is split into Telegraph pages at paragraph or line boundaries
before publication. The first page URL is returned, and continuation pages
include links to the previous and next page. This also applies to article
pages created inside a brief.

## Bookmarklets

Visit `/bookmarklet/` to get two permanent bookmarklets. Drag either link to
your browser's bookmarks bar, then click it while reading a page. They capture
the current document HTML in the browser, so they also work with pages rendered
by JavaScript or pages the server cannot access itself. Publishing uses the
server's `TELEGRAPH_API_TOKEN` (or its automatically created account); the raw
token is never included in the bookmarklet.

On an X/Twitter status page, the bookmarklet progressively scrolls and keeps
the rendered posts from the status author's thread before X virtualizes them
away. This uses no X API or credentials. It is best-effort: it can only retain
the posts X serves to the browser, and cannot prove that a same-author post is
part of the requested reply chain.

## Development

```bash
uv run pytest packages/markdown-web/tests
uv run ruff check packages/markdown-web
```

For FastAPI Cloud, add the key as a secret from `packages/markdown-web/`:

```bash
printf '%s' "$GROQ_API_KEY" |
  uv run fastapi cloud env set GROQ_API_KEY --value-stdin --secret .

printf '%s' "$FIRECRAWL_API_KEY" |
  uv run fastapi cloud env set FIRECRAWL_API_KEY --value-stdin --secret .
```

MIT
