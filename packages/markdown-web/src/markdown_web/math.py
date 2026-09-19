"""Turn the math markers emitted by some web pages into PNG-backed Markdown."""

from __future__ import annotations

import base64
import io
import re
from dataclasses import dataclass
from urllib.parse import quote

import requests
from PIL import Image, ImageDraw

LATEX_RENDER_URL = "https://latex.codecogs.com/png.image"
MATH_RENDER_TIMEOUT = 20
MAX_FORMULA_LENGTH = 4_000
MIN_MARKED_FORMULA_LENGTH = 3
MATH_BLOCK_RE = re.compile(r"\$\$(?P<formula>.*?)\$\$", re.DOTALL)
MATH_INLINE_RE = re.compile(r"(?<!\\)\$(?!\$)m(?P<formula>[^$\n]*?)m\$(?!\$)")
FENCED_CODE_RE = re.compile(r"(?ms)^[ \t]*(?P<fence>`{3,}|~{3,})[^\n]*\n.*?^[ \t]*(?P=fence)[ \t]*$")
INLINE_CODE_RE = re.compile(r"(?P<fence>`+)[^\n]*?(?P=fence)")
LATEX_SYNTAX_RE = re.compile(r"[\\_^{}]")
FORMULA_CACHE_CONTROL = "public, max-age=31536000, immutable"
FALLBACK_CACHE_CONTROL = "no-store"


class MathFormulaError(ValueError):
    """Raised when a formula cannot be represented by the math endpoint."""

    def __init__(self) -> None:
        super().__init__("Invalid or oversized formula")


@dataclass(frozen=True)
class FormulaImage:
    """PNG bytes and whether they are a temporary local fallback."""

    content: bytes
    is_fallback: bool = False


def _marked_formula(value: str) -> str | None:
    """Return a Cloudflare-style ``m ... m`` formula, without its markers."""
    formula = value.strip()
    if not formula.startswith("m") or not formula.endswith("m"):
        return None
    if len(formula) < MIN_MARKED_FORMULA_LENGTH or not formula[1].isspace() or not formula[-2].isspace():
        return None
    formula = formula[1:-1].strip()
    if not formula or len(formula) > MAX_FORMULA_LENGTH:
        return None
    return _normalize_formula(formula)


def _normalize_formula(formula: str) -> str:
    """Use the AMS ``aligned`` environment supported by the PNG renderer."""
    return re.sub(r"\\(begin|end)\{align\*?\}", r"\\\1{aligned}", formula)


def encode_formula(formula: str) -> str:
    """Encode a bounded formula for an immutable URL path."""
    if not formula or len(formula) > MAX_FORMULA_LENGTH:
        raise MathFormulaError
    return base64.urlsafe_b64encode(formula.encode("utf-8")).decode("ascii").rstrip("=")


def decode_formula(token: str) -> str:
    """Decode and validate a formula token supplied to the public endpoint."""
    if not re.fullmatch(r"[A-Za-z0-9_-]+", token):
        raise MathFormulaError
    try:
        formula = base64.urlsafe_b64decode(token + "=" * (-len(token) % 4)).decode("utf-8")
    except (UnicodeDecodeError, ValueError) as exc:
        raise MathFormulaError from exc
    if not formula or len(formula) > MAX_FORMULA_LENGTH:
        raise MathFormulaError
    return formula


def math_image_url(formula: str, site_url: str) -> str:
    """Return the service URL that exposes *formula* as a PNG."""
    return f"{site_url.rstrip('/')}/math/{encode_formula(formula)}.png"


def replace_marked_math(markdown: str, site_url: str) -> str:
    """Replace extracted ``$m ... m$`` and ``$$m ... m$$`` markers with images."""

    protected: list[str] = []

    def protect(match: re.Match[str]) -> str:
        protected.append(match.group(0))
        return f"\x00math-protected-{len(protected) - 1}\x00"

    def replace_block(match: re.Match[str]) -> str:
        formula = _marked_formula(match.group("formula"))
        return f"![Formula]({math_image_url(formula, site_url)})" if formula else match.group(0)

    def replace_inline(match: re.Match[str]) -> str:
        raw_formula = match.group("formula")
        formula = raw_formula.strip()
        has_sentinel_whitespace = bool(raw_formula) and raw_formula[0].isspace() and raw_formula[-1].isspace()
        if (
            not formula
            or len(formula) > MAX_FORMULA_LENGTH
            or not (has_sentinel_whitespace or LATEX_SYNTAX_RE.search(formula))
        ):
            return match.group(0)
        return f"![Formula]({math_image_url(_normalize_formula(formula), site_url)})"

    markdown = FENCED_CODE_RE.sub(protect, markdown)
    markdown = INLINE_CODE_RE.sub(protect, markdown)
    markdown = MATH_INLINE_RE.sub(replace_inline, MATH_BLOCK_RE.sub(replace_block, markdown))
    for index, content in enumerate(protected):
        markdown = markdown.replace(f"\x00math-protected-{index}\x00", content)
    return markdown


def render_formula_png(formula: str) -> FormulaImage:
    """Render one formula with CodeCogs, falling back to a local readable PNG."""
    if not formula or len(formula) > MAX_FORMULA_LENGTH:
        raise MathFormulaError
    url = f"{LATEX_RENDER_URL}?{quote(r'\dpi{120} ' + formula, safe='')}"
    try:
        response = requests.get(url, timeout=MATH_RENDER_TIMEOUT)
        response.raise_for_status()
    except requests.RequestException:
        return FormulaImage(_fallback_formula_png(formula), is_fallback=True)
    if not response.headers.get("content-type", "").startswith("image/png"):
        return FormulaImage(_fallback_formula_png(formula), is_fallback=True)
    return FormulaImage(response.content)


def _fallback_formula_png(formula: str) -> bytes:
    """Keep formulas visible when the optional external renderer is unavailable."""
    text = " ".join(formula.split()).encode("ascii", "replace").decode("ascii")[:512]
    image = Image.new("RGB", (max(200, len(text) * 7 + 20), 32), "white")
    ImageDraw.Draw(image).text((10, 10), text, fill="black")
    output = io.BytesIO()
    image.save(output, format="PNG")
    return output.getvalue()
