from __future__ import annotations

import re

import pytest
from markdown_web import math
from markdown_web.math import MathFormulaError, decode_formula, math_image_url, replace_marked_math

EXPECTED_FORMULA_COUNT = 2


def test_replace_marked_math_turns_block_and_inline_formulas_into_images() -> None:
    markdown = """Before.

$$m
\\begin{align*}
\\text{Exp} &= \\frac{1}{N}
\\end{align*}
m$$

At $m N=100, \\text{CV} \\approx 99\\% m$.
"""

    result = replace_marked_math(markdown, "https://markdown.example")

    urls = re.findall(r"!\[Formula\]\(([^)]+)\)", result)
    assert len(urls) == EXPECTED_FORMULA_COUNT
    assert all(url.startswith("https://markdown.example/math/") and url.endswith(".png") for url in urls)
    assert "\\begin{align*}" not in decode_formula(urls[0].rsplit("/", 1)[1].removesuffix(".png"))
    assert "\\begin{aligned}" in decode_formula(urls[0].rsplit("/", 1)[1].removesuffix(".png"))
    assert decode_formula(urls[1].rsplit("/", 1)[1].removesuffix(".png")) == r"N=100, \text{CV} \approx 99\%"


def test_replace_marked_math_leaves_regular_currency_and_math_untouched() -> None:
    markdown = "A price is $10 and ordinary math is $x$."

    assert replace_marked_math(markdown, "https://markdown.example") == markdown


def test_formula_tokens_round_trip_and_reject_invalid_values() -> None:
    url = math_image_url(r"\frac{1}{N}", "https://markdown.example/")

    assert decode_formula(url.rsplit("/", 1)[1].removesuffix(".png")) == r"\frac{1}{N}"
    with pytest.raises(MathFormulaError):
        decode_formula("not a token")


def test_render_formula_png_falls_back_when_codecogs_is_unavailable(monkeypatch: pytest.MonkeyPatch) -> None:
    def timeout(*_args: object, **_kwargs: object) -> None:
        raise math.requests.Timeout

    monkeypatch.setattr(math.requests, "get", timeout)

    assert math.render_formula_png(r"\frac{1}{N}").startswith(b"\x89PNG\r\n\x1a\n")
