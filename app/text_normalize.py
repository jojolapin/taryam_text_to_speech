"""Speech-friendly text normalization.

This module turns markdown (and a subset of inline HTML) into plain text that
a TTS engine can read without pronouncing the syntax. Paragraphs, list items
and headings are kept separated by sentence-ending punctuation so Piper
produces natural prosody pauses.

Design goals:

* Zero external dependencies (ordered regex pipeline).
* Deterministic and idempotent: ``clean_markdown(clean_markdown(x)) == clean_markdown(x)``.
* Safe on non-markdown input: plain text passes through untouched.
* Configurable: code blocks, URLs and tables behavior are opt-in/out.

(C) 2026 JojoLapin Inc.
"""
from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable


# ---------------------------------------------------------------------------
# Options
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class NormalizeOptions:
    """Feature flags controlling how markdown is turned into speech text."""

    read_code: bool = False
    """Read fenced code blocks verbatim. When False, they are announced once."""

    read_urls: bool = False
    """Read the URL part of ``[label](url)`` links. When False, only ``label``."""

    read_tables: bool = True
    """Read table rows as sentences. When False, tables are dropped entirely."""

    code_announce_en: str = "Code block omitted."
    code_announce_fr: str = "Bloc de code omis."

    image_prefix_en: str = "image"
    image_prefix_fr: str = "image"

    lang: str = "en"
    """Used only for the localized 'Code block omitted' / 'image:' announcements."""

    def code_announce(self) -> str:
        return self.code_announce_fr if self.lang == "fr" else self.code_announce_en

    def image_prefix(self) -> str:
        return self.image_prefix_fr if self.lang == "fr" else self.image_prefix_en


DEFAULT_OPTIONS = NormalizeOptions()


# ---------------------------------------------------------------------------
# Regex pipeline
# ---------------------------------------------------------------------------

# Fenced code blocks (``` or ~~~). Matched first so inner content never
# interferes with the other rules.
_RE_FENCE = re.compile(
    r"(?P<fence>^[ \t]{0,3}(```+|~~~+)[^\n]*\n.*?^[ \t]{0,3}\2[ \t]*$)",
    re.M | re.S,
)

# Inline code: `foo`  (but not triple-backtick: already consumed above)
_RE_INLINE_CODE = re.compile(r"`+([^`\n]+?)`+")

# HTML tags -> dropped (we keep inner text)
_RE_HTML_TAG = re.compile(r"<[^<>\n]{1,200}>")
# HTML entities decoded below via a small table

# Images:  ![alt](url)   ->  "image: alt"
_RE_IMAGE = re.compile(r"!\[([^\]\n]*)\]\(\s*([^)\s]+)(?:\s+\"[^\"]*\")?\s*\)")

# Links:  [label](url)   ->  label (or "label (url)" when read_urls is True)
_RE_LINK = re.compile(r"\[([^\]\n]+)\]\(\s*([^)\s]+)(?:\s+\"[^\"]*\")?\s*\)")

# Reference-style links: [label][ref]  or  [label]
_RE_REF_LINK = re.compile(r"\[([^\]\n]+)\](?:\[[^\]\n]*\])?")

# Autolink  <http://...>  /  <mailto:...>
_RE_AUTOLINK = re.compile(r"<((?:https?|mailto|ftp)://?[^\s<>]+)>", re.I)

# Bold: **text** or __text__
_RE_BOLD = re.compile(r"(\*\*|__)(?=\S)(.+?)(?<=\S)\1", re.S)

# Emphasis: *text* or _text_ — guarded so underscores inside identifiers
# like `some_var_name` survive.
_RE_EMPH_STAR = re.compile(r"(?<![*\w])\*(?=\S)([^*\n]+?)(?<=\S)\*(?![*\w])")
_RE_EMPH_UNDERSCORE = re.compile(r"(?<![_\w])_(?=\S)([^_\n]+?)(?<=\S)_(?![_\w])")

# Strikethrough ~~text~~
_RE_STRIKE = re.compile(r"~~(?=\S)(.+?)(?<=\S)~~", re.S)

# ATX headings:  # Heading ...   (up to 6 #). Trailing closing #s are allowed.
_RE_HEADING = re.compile(r"^[ \t]{0,3}(#{1,6})[ \t]+(.+?)[ \t]*#*[ \t]*$", re.M)

# Setext headings:  "Heading\n=====" or "Heading\n-----"
_RE_SETEXT = re.compile(r"^(?P<title>[^\n]+?)\n[ \t]{0,3}(?P<kind>=+|-+)[ \t]*$", re.M)

# Horizontal rules: ---, ***, ___
_RE_HR = re.compile(r"^[ \t]{0,3}(?:[-*_][ \t]*){3,}[ \t]*$", re.M)

# Blockquote marker  >
_RE_BQ = re.compile(r"^[ \t]{0,3}>[ \t]?", re.M)

# List items (unordered + ordered)
_RE_LIST = re.compile(r"^[ \t]{0,8}(?:[-*+]|\d{1,3}[.)])[ \t]+", re.M)

# Task list checkbox  - [x] / - [ ]
_RE_TASK = re.compile(r"^([ \t]*)(?:[-*+]|\d+[.)])[ \t]+\[[ xX]\][ \t]+", re.M)

# Table separator row (|---|:---:|---:|)
_RE_TABLE_SEP = re.compile(r"^[ \t]{0,3}\|?[ \t]*(?::?-{3,}:?[ \t]*\|[ \t]*)+:?-{3,}:?[ \t]*\|?[ \t]*$", re.M)

# Table content row (detect | x | y | ...): captured lazily
_RE_TABLE_ROW = re.compile(r"^[ \t]{0,3}\|(.+?)\|[ \t]*$", re.M)

# Simple HTML entities
_HTML_ENTITIES = {
    "&amp;": "&", "&lt;": "<", "&gt;": ">", "&quot;": '"', "&apos;": "'",
    "&nbsp;": " ", "&ndash;": "\u2013", "&mdash;": "\u2014",
    "&hellip;": "\u2026", "&copy;": "\u00a9", "&trade;": "\u2122",
    "&reg;": "\u00ae", "&laquo;": "\u00ab", "&raquo;": "\u00bb",
}

# Emoji shortcodes: :smile: :fire:
_RE_EMOJI_CODE = re.compile(r":[a-z0-9_+\-]{2,30}:")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _strip_html_entities(s: str) -> str:
    for k, v in _HTML_ENTITIES.items():
        if k in s:
            s = s.replace(k, v)
    # Numeric HTML entities: &#169; / &#x00A9;
    def _num(m: re.Match[str]) -> str:
        try:
            raw = m.group(1)
            cp = int(raw[1:], 16) if raw.startswith(("x", "X")) else int(raw)
            return chr(cp)
        except (ValueError, OverflowError):
            return m.group(0)
    return re.sub(r"&#([0-9]+|[xX][0-9a-fA-F]+);", _num, s)


def _is_emoji(ch: str) -> bool:
    """True for characters in common emoji-ish Unicode ranges."""
    if not ch:
        return False
    cp = ord(ch)
    return (
        0x1F300 <= cp <= 0x1FAFF
        or 0x2600 <= cp <= 0x27BF
        or 0x1F1E6 <= cp <= 0x1F1FF  # regional indicators
        or cp == 0xFE0F  # variation selector-16
    )


def _strip_emoji(s: str) -> str:
    return "".join("" if _is_emoji(c) else c for c in s)


def _ends_with_punct(s: str) -> bool:
    s = s.rstrip()
    return bool(s) and s[-1] in ".!?\u2026:;,"


def _ensure_sentence(s: str) -> str:
    s = s.strip()
    if not s:
        return s
    return s if _ends_with_punct(s) else s + "."


def _detokenize_emphasis(segment: str) -> str:
    """Run the inline-level replacements on a single line or block."""
    # Images first (so their ! isn't swallowed by link rule)
    segment = _RE_IMAGE.sub(_image_replace, segment)
    segment = _RE_LINK.sub(_link_replace, segment)
    segment = _RE_AUTOLINK.sub(_autolink_replace, segment)
    segment = _RE_INLINE_CODE.sub(r"\1", segment)
    segment = _RE_BOLD.sub(r"\2", segment)
    segment = _RE_EMPH_STAR.sub(r"\1", segment)
    segment = _RE_EMPH_UNDERSCORE.sub(r"\1", segment)
    segment = _RE_STRIKE.sub(r"\1", segment)
    # Reference-style links like [label] -> label (after real links are gone)
    segment = _RE_REF_LINK.sub(r"\1", segment)
    return segment


# Replacers are built as closures over options at run time in clean_markdown.
_image_replace = None  # type: ignore[assignment]
_link_replace = None  # type: ignore[assignment]
_autolink_replace = None  # type: ignore[assignment]


# ---------------------------------------------------------------------------
# Main entry
# ---------------------------------------------------------------------------

def clean_markdown(text: str, options: NormalizeOptions | None = None) -> str:
    """Return a TTS-friendly plain string derived from markdown ``text``."""
    global _image_replace, _link_replace, _autolink_replace
    if not text:
        return ""
    opts = options or DEFAULT_OPTIONS

    # -- Build closure-based replacers once per call (cheap; keeps fn pure) --
    def image_replace(m: re.Match[str]) -> str:
        alt = (m.group(1) or "").strip()
        if not alt:
            return ""
        return f"{opts.image_prefix()}: {alt}."

    def link_replace(m: re.Match[str]) -> str:
        label = (m.group(1) or "").strip()
        url = (m.group(2) or "").strip()
        if opts.read_urls and url:
            return f"{label} ({url})"
        return label

    def autolink_replace(m: re.Match[str]) -> str:
        url = (m.group(1) or "").strip()
        return url if opts.read_urls else ""

    _image_replace = image_replace
    _link_replace = link_replace
    _autolink_replace = autolink_replace

    s = text

    # 1) Normalize newlines
    s = s.replace("\r\n", "\n").replace("\r", "\n")

    # 2) Extract fenced code blocks FIRST. They become either verbatim content
    #    or a single announcement sentence.
    def fence_sub(m: re.Match[str]) -> str:
        if opts.read_code:
            body = m.group(0)
            body = re.sub(r"^[ \t]{0,3}(```+|~~~+)[^\n]*\n", "", body)
            body = re.sub(r"\n[ \t]{0,3}(```+|~~~+)[ \t]*$", "", body)
            return "\n\n" + body.strip() + "\n\n"
        return "\n\n" + opts.code_announce() + "\n\n"

    s = _RE_FENCE.sub(fence_sub, s)

    # 3) Setext headings -> ATX-style, then handle ATX
    def setext_sub(m: re.Match[str]) -> str:
        return m.group("title").strip()
    s = _RE_SETEXT.sub(lambda m: _ensure_sentence(setext_sub(m)) + "\n", s)

    s = _RE_HEADING.sub(lambda m: _ensure_sentence(m.group(2)) + "\n", s)

    # 4) Horizontal rules -> paragraph break
    s = _RE_HR.sub("\n", s)

    # 5) Tables
    if opts.read_tables:
        s = _RE_TABLE_SEP.sub("", s)

        def table_row_sub(m: re.Match[str]) -> str:
            cells = [c.strip() for c in m.group(1).split("|")]
            cells = [c for c in cells if c]
            if not cells:
                return ""
            return " ".join(_ensure_sentence(c) for c in cells)
        s = _RE_TABLE_ROW.sub(table_row_sub, s)
    else:
        # Drop every line that looks like a pipe table
        s = re.sub(r"^[ \t]{0,3}\|.*$", "", s, flags=re.M)
        s = _RE_TABLE_SEP.sub("", s)

    # 6) Blockquotes -> strip marker
    s = _RE_BQ.sub("", s)

    # 7) Task-list checkboxes -> rewrite as a plain list item; list_strip below
    #    will drop the bullet and ensure the item ends with punctuation so the
    #    TTS pauses between checklist entries.
    s = _RE_TASK.sub(r"\1- ", s)

    # 8) List markers -> drop; ensure each list item ends with a period so
    #    Piper pauses between items.
    def list_strip(line: str) -> str:
        stripped = _RE_LIST.sub("", line, count=1)
        return _ensure_sentence(stripped) if stripped != line else line

    s = "\n".join(list_strip(ln) for ln in s.split("\n"))

    # 9) Inline: links, bold, italic, strikethrough, inline code
    s = _detokenize_emphasis(s)

    # 10) HTML entities + tag strip
    s = _strip_html_entities(s)
    s = _RE_HTML_TAG.sub(" ", s)

    # 11) Emoji (shortcodes + unicode)
    s = _RE_EMOJI_CODE.sub("", s)
    s = _strip_emoji(s)

    # 12) Collapse whitespace
    s = re.sub(r"[ \t]+", " ", s)
    s = re.sub(r"\n{3,}", "\n\n", s)
    s = re.sub(r"[ \t]*\n[ \t]*", "\n", s)

    # 13) Collapse repeated punctuation: ".. . ." -> "." etc.
    s = re.sub(r"(?:\.\s*){2,}", ". ", s)
    s = re.sub(r"\s+([.!?;:,])", r"\1", s)

    # 14) Normalize Unicode (NFC) so diacritics are well-formed for the TTS
    s = unicodedata.normalize("NFC", s)

    return s.strip()


# ---------------------------------------------------------------------------
# Format detection
# ---------------------------------------------------------------------------

_SIGNAL_HEADING = re.compile(r"^[ \t]{0,3}#{1,6}\s+\S", re.M)
_SIGNAL_LIST = re.compile(r"^[ \t]{0,8}(?:[-*+]|\d{1,3}[.)])[ \t]+\S", re.M)
_SIGNAL_FENCE = re.compile(r"^[ \t]{0,3}(?:```+|~~~+)", re.M)
_SIGNAL_EMPH = re.compile(r"\*\*\S|__\S|(?<!\w)\*\S|(?<!\w)_\S")
_SIGNAL_LINK = re.compile(r"\[[^\]\n]+\]\([^)\s]+\)")
_SIGNAL_TABLE = re.compile(r"^[ \t]{0,3}\|?[ \t]*:?-{3,}:?[ \t]*\|", re.M)


def detect_format(source: str | Path, text: str | None = None) -> str:
    """Return ``"markdown" | "html" | "plain"`` for the given file path or text.

    When both are given, ``text`` wins; when only a path is given, the extension
    is used and ``text`` is loaded from disk (utf-8, replacement on errors).
    """
    # Resolve path hint
    ext = ""
    if isinstance(source, Path) or (isinstance(source, str) and "\n" not in source and len(source) < 260):
        try:
            p = Path(source)
            ext = p.suffix.lower()
        except (TypeError, ValueError, OSError):
            ext = ""
    if ext in {".md", ".markdown", ".mdown", ".mkd"}:
        return "markdown"
    if ext in {".html", ".htm", ".xhtml"}:
        return "html"
    if text is None and isinstance(source, str) and "\n" in source:
        text = source

    if not text:
        return "plain"

    if _looks_like_html(text):
        return "html"
    if _looks_like_markdown(text):
        return "markdown"
    return "plain"


def _looks_like_html(text: str) -> bool:
    sample = text[:4000]
    if re.search(r"<\s*(html|body|head|div|p|span|h[1-6]|table|ul|ol|li|article)\b", sample, re.I):
        return True
    # Any close-tag density > 2 in a small sample
    return len(re.findall(r"</\s*[a-z]+\s*>", sample, re.I)) >= 3


def _looks_like_markdown(text: str) -> bool:
    sample = text[:8000]
    signals = 0
    for rx in (_SIGNAL_HEADING, _SIGNAL_LIST, _SIGNAL_FENCE, _SIGNAL_EMPH,
               _SIGNAL_LINK, _SIGNAL_TABLE):
        if rx.search(sample):
            signals += 1
            if signals >= 2:
                return True
    return False


# ---------------------------------------------------------------------------
# Convenience
# ---------------------------------------------------------------------------

def normalize(text: str, fmt: str = "auto", *,
              lang: str = "en",
              read_code: bool = False,
              read_urls: bool = False,
              read_tables: bool = True) -> str:
    """Return a TTS-friendly plain string.

    ``fmt`` is one of ``"auto" | "markdown" | "html" | "plain"``. "auto" uses
    :func:`detect_format` on ``text``.
    """
    if not text:
        return ""
    if fmt == "auto":
        fmt = detect_format("<memory>", text=text)

    opts = NormalizeOptions(
        read_code=read_code,
        read_urls=read_urls,
        read_tables=read_tables,
        lang=lang if lang in {"en", "fr"} else "en",
    )

    if fmt == "markdown":
        return clean_markdown(text, opts)
    if fmt == "html":
        stripped = _strip_html_entities(text)
        stripped = _RE_HTML_TAG.sub(" ", stripped)
        # Also run the markdown pass in case HTML is embedded with markdown
        return clean_markdown(stripped, opts)
    # Plain: still drop emoji + collapse whitespace (same feel)
    s = _RE_EMOJI_CODE.sub("", text)
    s = _strip_emoji(s)
    s = re.sub(r"[ \t]+", " ", s)
    s = re.sub(r"\n{3,}", "\n\n", s)
    return unicodedata.normalize("NFC", s).strip()


def has_markdown_signals(text: str) -> bool:
    """Cheap probe used by the UI auto-detection."""
    return _looks_like_markdown(text or "")


__all__: Iterable[str] = (
    "NormalizeOptions",
    "DEFAULT_OPTIONS",
    "clean_markdown",
    "detect_format",
    "normalize",
    "has_markdown_signals",
)
