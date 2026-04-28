"""Tests for the TTS-friendly markdown normalizer.

Run with:   py -3.13 -m pytest -q tests/test_text_normalize.py

(C) 2026 JojoLapin Inc.
"""
from __future__ import annotations

import sys
from pathlib import Path

# Make the project root importable when pytest is launched from elsewhere
ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.text_normalize import (  # noqa: E402
    NormalizeOptions,
    clean_markdown,
    detect_format,
    has_markdown_signals,
    normalize,
)


# ---------------------------------------------------------------------------
# Inline emphasis
# ---------------------------------------------------------------------------

def test_bold_asterisks_are_stripped() -> None:
    assert clean_markdown("This is **very important** text.") == "This is very important text."


def test_bold_underscores_are_stripped() -> None:
    assert clean_markdown("This is __loud__.") == "This is loud."


def test_italic_asterisks_are_stripped() -> None:
    assert clean_markdown("He said *hello* there.") == "He said hello there."


def test_italic_underscores_are_stripped_outside_identifiers() -> None:
    # _word_ is stripped, but some_var_name is preserved as an identifier.
    assert clean_markdown("_hi_ and some_var_name") == "hi and some_var_name"


def test_strikethrough_is_stripped() -> None:
    assert clean_markdown("This is ~~wrong~~ bad") == "This is wrong bad"


def test_inline_code_kept_without_backticks() -> None:
    assert clean_markdown("Use the `print()` function") == "Use the print() function"


def test_nested_emphasis_is_stripped() -> None:
    assert clean_markdown("**bold _and italic_**") == "bold and italic"


# ---------------------------------------------------------------------------
# Headings / horizontal rules
# ---------------------------------------------------------------------------

def test_atx_heading_becomes_sentence() -> None:
    out = clean_markdown("# Title\n\nBody text")
    assert out.startswith("Title.")


def test_setext_heading_becomes_sentence() -> None:
    out = clean_markdown("Title\n=====\n\nBody")
    assert out.startswith("Title.")


def test_horizontal_rule_is_dropped() -> None:
    out = clean_markdown("Alpha\n\n---\n\nBeta")
    assert "---" not in out and "Alpha" in out and "Beta" in out


# ---------------------------------------------------------------------------
# Lists
# ---------------------------------------------------------------------------

def test_unordered_list_markers_are_stripped() -> None:
    md = "- Apple\n- Banana\n- Cherry"
    out = clean_markdown(md)
    assert "-" not in out.splitlines()[0]
    assert "Apple." in out and "Banana." in out and "Cherry." in out


def test_ordered_list_markers_are_stripped() -> None:
    out = clean_markdown("1. first\n2. second\n3. third")
    for num in ("1.", "2.", "3."):
        assert num not in out
    assert "first." in out and "second." in out and "third." in out


def test_task_list_checkboxes_are_dropped() -> None:
    out = clean_markdown("- [ ] todo item\n- [x] done item")
    assert "[" not in out and "]" not in out
    assert "todo item." in out and "done item." in out


# ---------------------------------------------------------------------------
# Links / images / autolinks
# ---------------------------------------------------------------------------

def test_link_label_is_kept_url_is_dropped_by_default() -> None:
    out = clean_markdown("See the [docs](https://example.com) for details.")
    assert "https://example.com" not in out
    assert "docs" in out


def test_link_url_is_read_when_enabled() -> None:
    opts = NormalizeOptions(read_urls=True)
    out = clean_markdown("See the [docs](https://example.com).", opts)
    assert "https://example.com" in out


def test_image_becomes_alt_text_announcement() -> None:
    out = clean_markdown("![A cat sitting on a mat](cat.png)")
    assert "image" in out.lower() and "cat sitting on a mat" in out.lower()


def test_autolink_dropped_by_default() -> None:
    out = clean_markdown("Visit <https://example.com> now.")
    assert "example.com" not in out
    assert "Visit" in out and "now" in out


def test_reference_style_link_keeps_label() -> None:
    out = clean_markdown("See [the guide][guide] for more.\n\n[guide]: https://example.com")
    assert "the guide" in out


# ---------------------------------------------------------------------------
# Code blocks
# ---------------------------------------------------------------------------

def test_code_block_is_announced_by_default_en() -> None:
    md = "Before.\n\n```python\nprint('hi')\n```\n\nAfter."
    out = clean_markdown(md, NormalizeOptions(lang="en"))
    assert "Code block omitted." in out
    assert "print('hi')" not in out


def test_code_block_is_announced_by_default_fr() -> None:
    md = "Avant.\n\n```\nsecret\n```\n\nApres."
    out = clean_markdown(md, NormalizeOptions(lang="fr"))
    assert "Bloc de code omis." in out
    assert "secret" not in out


def test_code_block_is_kept_when_read_code_true() -> None:
    md = "```\nhello world\n```"
    out = clean_markdown(md, NormalizeOptions(read_code=True))
    assert "hello world" in out


# ---------------------------------------------------------------------------
# Tables
# ---------------------------------------------------------------------------

def test_table_rows_are_read_as_sentences() -> None:
    md = (
        "| Name | Age |\n"
        "|------|-----|\n"
        "| Alice | 30 |\n"
        "| Bob   | 42 |\n"
    )
    out = clean_markdown(md, NormalizeOptions(read_tables=True))
    assert "Alice" in out and "30" in out
    assert "Bob" in out and "42" in out
    assert "|" not in out
    assert "---" not in out


def test_table_is_dropped_when_read_tables_false() -> None:
    md = (
        "| Name | Age |\n"
        "|------|-----|\n"
        "| Alice | 30 |\n"
        "| Bob   | 42 |\n"
        "\n"
        "Trailing paragraph."
    )
    out = clean_markdown(md, NormalizeOptions(read_tables=False))
    assert "Alice" not in out and "Bob" not in out
    assert "Trailing paragraph." in out


# ---------------------------------------------------------------------------
# Blockquotes / HTML / entities / emoji
# ---------------------------------------------------------------------------

def test_blockquote_marker_is_stripped() -> None:
    out = clean_markdown("> Wise words\n> go here")
    assert ">" not in out
    assert "Wise words" in out and "go here" in out


def test_html_tags_are_stripped_entities_decoded() -> None:
    out = clean_markdown("<b>Bold</b> &amp; <i>italic</i>")
    assert "<" not in out and ">" not in out
    assert "Bold" in out and "italic" in out
    assert "&amp;" not in out and "&" in out


def test_numeric_html_entities_are_decoded() -> None:
    out = clean_markdown("Copyright &#169; 2026")
    assert "\u00a9" in out


def test_emoji_characters_are_stripped() -> None:
    out = clean_markdown("Party \U0001f389 time")
    assert "\U0001f389" not in out
    assert "Party" in out and "time" in out


def test_emoji_shortcodes_are_stripped() -> None:
    out = clean_markdown("Party :tada: time")
    assert ":tada:" not in out
    assert "Party" in out and "time" in out


# ---------------------------------------------------------------------------
# Whitespace / idempotence / empty inputs
# ---------------------------------------------------------------------------

def test_clean_markdown_on_empty_string() -> None:
    assert clean_markdown("") == ""


def test_clean_markdown_is_idempotent() -> None:
    md = "# Title\n\nThis is **bold** text with a [link](https://example.com)."
    once = clean_markdown(md)
    twice = clean_markdown(once)
    assert once == twice


def test_plain_text_passes_through_unchanged() -> None:
    txt = "A simple sentence without any markdown."
    assert clean_markdown(txt) == txt


def test_multiple_blank_lines_collapse_to_one_separator() -> None:
    md = "Para one.\n\n\n\n\nPara two."
    out = clean_markdown(md)
    assert "\n\n\n" not in out


# ---------------------------------------------------------------------------
# Format detection
# ---------------------------------------------------------------------------

def test_detect_markdown_by_extension() -> None:
    assert detect_format("notes.md") == "markdown"
    assert detect_format("notes.markdown") == "markdown"
    assert detect_format(Path("x.MD")) == "markdown"


def test_detect_html_by_extension() -> None:
    assert detect_format("page.html") == "html"
    assert detect_format("page.htm") == "html"


def test_detect_plain_by_extension() -> None:
    assert detect_format("notes.txt", text="just plain text") == "plain"


def test_detect_markdown_by_content() -> None:
    md = "# Heading\n\n- one\n- two\n"
    assert detect_format("unknown.dat", text=md) == "markdown"


def test_detect_html_by_content() -> None:
    html = "<!doctype html><html><body><p>hi</p></body></html>"
    assert detect_format("unknown.dat", text=html) == "html"


def test_has_markdown_signals_returns_true_on_markdown() -> None:
    assert has_markdown_signals("# Heading\n\n- list")


def test_has_markdown_signals_returns_false_on_plain() -> None:
    assert not has_markdown_signals("Just a normal sentence.")


# ---------------------------------------------------------------------------
# High-level normalize() with auto mode
# ---------------------------------------------------------------------------

def test_normalize_auto_detects_markdown() -> None:
    md = "# Hello\n\nThis is **bold**."
    out = normalize(md, "auto")
    assert "**" not in out and "#" not in out
    assert "Hello" in out and "bold" in out


def test_normalize_auto_leaves_plain_text_intact() -> None:
    txt = "Nothing special here, just a sentence."
    out = normalize(txt, "auto")
    assert out == txt


def test_normalize_explicit_plain_format_skips_parsing() -> None:
    md = "# Heading"
    out = normalize(md, "plain")
    # In "plain" mode we do not strip markdown (intentional — user opted out)
    assert out == "# Heading"


def test_normalize_html_fmt_strips_tags() -> None:
    out = normalize("<p>Hello <b>world</b>.</p>", "html")
    assert "<" not in out and ">" not in out
    assert "Hello" in out and "world" in out


# ---------------------------------------------------------------------------
# The full README gauntlet (smoke test on the bundled README)
# ---------------------------------------------------------------------------

def test_readme_smoke_produces_asterisk_free_text() -> None:
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    out = clean_markdown(readme)
    # Explicit forbidden markdown syntax should never appear
    for forbidden in ("**", "##", "```", "| ---"):
        assert forbidden not in out, f"README residue: {forbidden!r}"
    # But recognizable content should remain
    assert "TextSpeak Pro" in out
    assert "Piper" in out
