# Technical Reference

## Current Pipeline

`extract_main_content` returns `(title, markdown, fallback_text, intro)`.

URL acquisition can use the existing GitHub, arXiv and YouTube integrations
or the shared oEmbed client. Otherwise it downloads HTML once.

Downloaded HTML, local files and supplied HTML share this pipeline:

1. Read metadata and the source URL.
2. Extract embedded Arc Fusion article data when present, on any hostname.
3. Select a body using a declarative domain rule when one matches.
4. Use Readability, with schema.org article text as a fallback for short or
   missing content. Nested nodes and multiple declared types are supported.
5. Normalize images, figures and relative links and remove structural chrome.
6. Convert to Markdown, add front matter and derive preview text.

Pass `source_url=` with supplied HTML to resolve its relative links. The web
service forwards the URL from request metadata for bookmarklet extraction.

Rules in `markdown_this.rules` declare hostnames, ordered body selectors and
selectors to strip inside the body. The first nonempty body wins; nested
selectors do not duplicate content. Each default rule needs an offline fixture.
Unmarked `aside` elements are preserved because they may contain article notes.

## Captured Post Collections

A rule can also declare an `item_selector`, `permalink_selector` and
`boundary_selector`. The shared collector deduplicates post IDs and selects
the contiguous author sequence containing the requested post. A boundary
outside the posts stops collection before recommendations. X and Twitter
use this rule mechanism; no X-specific fetcher or DOM parser is registered.

Supply rendered HTML with `source_url=` (the bookmarklet does this already).
On an X/Twitter status page it progressively scrolls and retains same-author
post cards before the virtualized page removes them. This requires neither an
X API token nor a server-side browser. It is best-effort: the capture can only
include posts delivered to that browser and author identity cannot prove a
reply relationship. Images, video/audio URLs and video posters pass through
common normalization. Browser-local `blob:` URLs are not portable; their
posters and post permalinks remain available instead.

The output declares `extraction_scope: captured-posts`. It contains only the
posts available in that HTML snapshot, not a verified complete thread. The
collector does not scroll the browser, fetch missing replies or infer reply
relationships from author identity alone. Consecutive author posts are a
presentation heuristic, not proof of a conversation graph.

## Public Rich oEmbed

Public X/Twitter URLs use the shared oEmbed client without API credentials.
Rich responses pass through the same HTML cleanup and media conversion as
documents; widget scripts are removed. Failed requests fall back to HTML
acquisition through the existing extractor registry.

The result declares `extraction_scope: oembed`: it contains the post content
returned by the provider, not a complete thread. Supplied HTML bypasses URL
acquisition, so an oEmbed response cannot replace a captured collection.
For a saved capture, retain the original post URL:

```bash
uvx markdown-this thread.html --source-url https://x.com/alice/status/1002
```

## Main Modules

- `markdown_this.extractor`: public pipeline orchestration.
- `markdown_this.fetchers`: HTTP fetchers and special URL handlers.
- `markdown_this.html`: HTML cleanup before Markdown conversion.
- `markdown_this.markdown`: Markdown normalization and preview text helpers.
- `markdown_this.metadata`: YAML front matter and HTML metadata extraction.
- `markdown_this.structured`: embedded article formats, independent of hostnames.
- `markdown_this.rules`: declarative domain selectors for known high-value
  sites.

## Testing Notes

The root pytest configuration enforces 100% coverage for `markdown-this` and
`md-to-telegraph`. New extraction behavior should add narrow offline fixtures
before using live URLs.
