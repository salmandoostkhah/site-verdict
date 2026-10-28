from seo_core.engine import _sanitize_list
from seo_core.formatting import to_fa_digits, to_latin_digits


def test_to_fa_digits_converts_latin_only():
    assert to_fa_digits("70/100 و 3.5%") == "۷۰/۱۰۰ و ۳.۵%"


def test_to_latin_digits_accepts_persian_input():
    assert to_latin_digits("https://example.com/۱۲") == "https://example.com/12"


def test_engine_messages_use_persian_digits():
    assert _sanitize_list(["طول عنوان 70 کاراکتر"]) == ["طول عنوان ۷۰ کاراکتر"]


def test_cli_raw_keeps_user_content_digits(capsys):
    import cli
    cli._raw("  Title         : Top 10 tips 2024 https://a.com/p/123")
    cli.print("  Word Count    : 965")
    out = capsys.readouterr().out
    assert "Top 10 tips 2024 https://a.com/p/123" in out
    assert "۹۶۵" in out