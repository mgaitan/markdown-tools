from markdown_web.bookmarklet import build_bookmarklets


def test_build_bookmarklets_use_server_endpoints_without_expiring_keys() -> None:
    result = build_bookmarklets("https://markdown.example/")

    assert result["markdown"].startswith("javascript:")
    assert result["edit"].startswith("javascript:")
    assert result["telegraph"].startswith("javascript:")
    assert "https://markdown.example/md" in result["markdown"]
    assert "https://markdown.example/bookmarklet/edit" in result["edit"]
    assert "https://markdown.example/t/bookmarklet" in result["telegraph"]
    assert "fetch(" not in result["markdown"]
    assert "X-Bookmarklet-Key" not in result["markdown"]
    assert "TELEGRAPH_API_TOKEN" not in result["markdown"]
    assert "document.querySelectorAll('article')" in result["markdown"]
    assert "scrollBy(0,innerHeight*.8)" in result["markdown"]
    assert "new Map()" in result["markdown"]
    assert "window.open('https://markdown.example/bookmarklet/capture?action=md','_blank')" in result["markdown"]
    assert "window.open('https://markdown.example/bookmarklet/capture?action=edit','_blank')" in result["edit"]
    assert "postMessage({type:'markdown-bookmarklet'" in result["markdown"]
