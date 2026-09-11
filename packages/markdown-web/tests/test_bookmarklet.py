from markdown_web.bookmarklet import build_bookmarklets


def test_build_bookmarklets_use_server_endpoints_without_expiring_keys() -> None:
    result = build_bookmarklets("https://markdown.example/")

    assert result["markdown"].startswith("javascript:")
    assert result["telegraph"].startswith("javascript:")
    assert "https://markdown.example/md" in result["markdown"]
    assert "https://markdown.example/t/bookmarklet" in result["telegraph"]
    assert "fetch(" not in result["markdown"]
    assert "X-Bookmarklet-Key" not in result["markdown"]
    assert "TELEGRAPH_API_TOKEN" not in result["markdown"]
    assert 'article[data-testid="tweet"]' in result["markdown"]
    assert "scrollBy(0,innerHeight*.8)" in result["markdown"]
    assert "new Map()" in result["markdown"]
