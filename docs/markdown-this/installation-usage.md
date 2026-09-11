# Installation And Usage

## Installation

```bash
uv add markdown-this
```

## Python API

```python
from markdown_this import extract_main_content

title, markdown, fallback_text, intro = extract_main_content(
    "https://example.com/article"
)
```

The source can be a URL, `Path`, path string, or raw HTML string.

`is_html_source` identifies raw HTML that starts with a complete document or a
structural fragment: `article`, `body`, `main`, `section`, or `div`. It returns
false for Markdown or prose that merely contains HTML later in the text.

## CLI

```bash
uvx markdown-this https://example.com/article
uvx markdown-this article.html
cat article.html | uvx markdown-this -
```

The command writes Markdown to stdout.

## Development

```bash
uv run pytest packages/markdown-this/tests
uv run ruff check packages/markdown-this
```
