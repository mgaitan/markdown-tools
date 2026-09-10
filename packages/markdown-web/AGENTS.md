# markdown-web

## Purpose

This package is the FastAPI service at https://markdown.fastapicloud.dev/. It
extracts URLs or HTML with `markdown-this`, publishes Markdown to Telegraph with
`md-to-telegraph`, and optionally advances long briefs through Redis jobs.

## Important boundaries

- Keep HTTP routes and request parsing in `src/markdown_web/app.py`.
- Keep publication orchestration and content preparation in `service.py`.
- Keep Redis job state and stage advancement in `jobs.py`.
- Keep Telegram delivery in `telegram.py`. It sends only the Telegraph URL and
  must remain best effort so a Telegram outage does not turn a successful
  Telegraph publication into a duplicate on retry.
- Do not commit `.env` or `.fastapicloud/`; both contain local credentials or
  deployment identifiers.

## Telegram notifications

Markdown can start with YAML front matter such as:

```yaml
---
title: An article
notify_telegram: 123456789, -1001234567890
---
```

`notify_telegram` is a comma-separated list. One `sendMessage` request is made
per unique recipient, with the published Telegraph URL as the complete message
text. The bot token comes from `TELEGRAM_WEB_BOT_TOKEN`. A missing token or a
Telegram API failure is logged and does not fail the Telegraph request. Durable
jobs persist whether their final URL notification was attempted.

The private recipient must first open
https://t.me/MarkdownTelegraphBot and send `/start`. In a group, add the bot and
give it permission to send messages. In a channel, add it as an administrator
with the `can_post_messages` right.

## Image uploads

`POST /images` accepts only PNG, JPEG, and WebP files up to 20 MB. Pillow
transposes EXIF orientation, limits the longest side to 1280 pixels, and stores
the result as WebP in R2. Redis enforces a limit of 10 uploads per IP per UTC
hour and 50 MB of input per UTC day. The endpoint requires
`R2_ACCOUNT_ID`, `R2_BUCKET_NAME`, `R2_ACCESS_KEY_ID`, `R2_SECRET_ACCESS_KEY`,
`R2_PUBLIC_BASE_URL`, and `REDIS_URL`. The public R2 URL must serve the stored
objects so they can be embedded by Telegraph. Never commit those credentials.

## Local checks

Run from the repository root:

```bash
uv run pytest packages/markdown-web/tests
uv run ruff check packages/markdown-web
uv run ruff format --check packages/markdown-web
```

The full workspace checks are `uv run pytest -q`, `uv run ruff check .`, and
`uv build --all-packages`.

## FastAPI Cloud deployment

The package is linked to FastAPI Cloud through `.fastapicloud/cloud.json`.
Deploy from `packages/markdown-web/` with:

```bash
uv run fastapi cloud deploy .
```

Set the production secret through the CLI, never in git:

```bash
printf '%s' "$TELEGRAM_WEB_BOT_TOKEN" |
  uv run fastapi cloud env set TELEGRAM_WEB_BOT_TOKEN --value-stdin --secret
```

Audio transcription uses `GROQ_API_KEY` by default. The provider endpoint and
model can be changed with `TRANSCRIPTION_API_KEY`, `TRANSCRIPTION_API_URL`, and
`TRANSCRIPTION_MODEL`.

Document conversion uses AnyDoc locally. Set `FIRECRAWL_API_KEY` to use
Firecrawl Parse as an OCR fallback only when a PDF cannot be read locally. The
hosted API receives the complete PDF because it does not support page selection.

The web app is installable as a PWA. Its Web Share Target receives audio and
supported documents through `POST /share`; the route processes the share before
rendering the editor, so do not persist shared content in browser storage.

After changing a cloud environment variable, deploy again if the platform does
not automatically restart the app. Check the public URL and deployment logs
after each deploy.
