# Technical Reference

## Main Modules

- `markdown_web.app`: FastAPI app, routes, and templates.
- `markdown_web.service`: extraction and publishing service functions.
- `markdown_web.jobs`: Redis-backed Telegraph job state.
- `markdown_web.assets`: uploaded image validation and storage.
- `markdown_web.transcription`: OpenAI-compatible file transcription provider.
- `markdown_web.bookmarklet`: browser capture helpers.
- `markdown_web.telegram`: best-effort Telegram notifications.

## Boundaries

The web app may orchestrate extraction, publishing, uploads, and notifications.
Reusable extraction and conversion logic belongs in `markdown-this`,
`md-to-telegraph`, or `md-to-epub`.
