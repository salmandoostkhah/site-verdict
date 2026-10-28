from seo_core.analyzers import on_page
from seo_core.html_utils import parse_html

HTML = "<html><head><title>T</title><script>x</script></head><body><p>hi</p></body></html>"


def test_same_html_returns_independent_copies():
    first = parse_html(HTML)
    second = parse_html(HTML)
    assert first is not second
    assert str(first) == str(second)


def test_mutating_returned_soup_does_not_leak_into_cache():
    mutated = parse_html(HTML)
    mutated.find("script").decompose()
    assert parse_html(HTML).find("script") is not None


def test_none_and_empty_are_safe():
    assert parse_html(None).find("html") is None


def test_on_page_text_decompose_does_not_touch_shared_soup():
    shared = parse_html(HTML)
    on_page.analyze(HTML)
    assert shared.find("script") is not None
    assert parse_html(HTML).find("script") is not None