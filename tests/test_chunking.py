"""Tests for app/chunking.py (Python mirror of the semantic chunker).

Keeps parity with tests/js/semantic-chunker.test.js. (C) 2026 JojoLapin Inc.
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.chunking import chunk, find_chunk_at_position  # noqa: E402


def _never_split(text, needle, max_chars):
    chunks = chunk(text, max_chars)
    start = 0
    seen = 0
    while True:
        idx = text.find(needle, start)
        if idx == -1:
            break
        seen += 1
        s, e = idx, idx + len(needle)
        assert any(c["start"] <= s and c["end"] >= e for c in chunks), (
            f'"{needle}" @{s} was split: {[(c["start"], c["end"]) for c in chunks]}'
        )
        start = idx + len(needle)
    assert seen > 0, f'needle "{needle}" not present'


def test_empty_and_whitespace():
    assert chunk("", 100) == []
    assert chunk("   \n\t ", 100) == []


def test_sentence_split_and_offsets():
    text = "Alpha beta gamma. Delta epsilon zeta. Eta theta iota."
    chunks = chunk(text, 25)
    assert chunks[0]["text"] == "Alpha beta gamma."
    last = 0
    for c in chunks:
        assert c["start"] >= last
        assert text[c["start"]:c["end"]].strip() == c["text"]
        last = c["start"]


def test_max_chars_respected():
    text = "The quick brown fox jumps over the lazy dog. " * 60
    for c in chunk(text, 200):
        assert c["end"] - c["start"] <= 200


def test_decimals_not_split():
    text = "The value is 3.14159 today. Pi matters. It equals 2.71828 elsewhere."
    _never_split(text, "3.14159", 16)
    _never_split(text, "2.71828", 16)


def test_thousands_not_split():
    text = "We sold 1,234,567 units. Revenue rose. Costs were 89,000 dollars."
    _never_split(text, "1,234,567", 14)
    _never_split(text, "89,000", 14)


def test_dates_and_times_not_split():
    text = "Meet on 2026-08-03 sharp. Then again. Or 12/25/2026 at 3:30 works fine."
    for m in ("2026-08-03", "12/25/2026", "3:30"):
        _never_split(text, m, 12)


def test_initials_not_split():
    text = "The author J.R.R. Tolkien wrote it. Fans agree. So did E.B. White surely."
    _never_split(text, "J.R.R.", 14)
    _never_split(text, "E.B.", 14)


def test_abbreviations_no_false_break():
    text = "Dr. Smith met Mr. Brown today. They talked. See Fig. 4 and Vol. 2 later."
    chunks = chunk(text, 200)
    assert any("Dr. Smith met Mr. Brown today." in c["text"] for c in chunks), [c["text"] for c in chunks]


def test_urls_and_emails_not_split():
    text = "Visit https://example.com/path?q=1&x=2 now. Great. Email a.b@c.co.uk please today."
    _never_split(text, "https://example.com/path?q=1&x=2", 20)
    _never_split(text, "a.b@c.co.uk", 18)


def test_oversized_url_kept_whole():
    long_url = "https://example.com/" + "a" * 300
    text = f"Start here. {long_url} End here."
    chunks = chunk(text, 50)
    assert any(long_url in text[c["start"]:c["end"]] for c in chunks)


def test_small_paragraphs_merge():
    text = "Para one.\n\nPara two.\n\nPara three."
    assert len(chunk(text, 500)) == 1


def test_find_chunk_at_position():
    text = "Alpha beta gamma. Delta epsilon zeta. Eta theta iota kappa."
    chunks = chunk(text, 20)
    assert find_chunk_at_position(chunks, 0) == 0
    assert find_chunk_at_position(chunks, len(text) - 1) == len(chunks) - 1
    assert find_chunk_at_position([], 5) == 0


def test_large_document_corpus():
    unit = "On 2026-08-03, Dr. Smith paid 1,234.56 to a.b@c.io via https://x.io/p. "
    text = unit * 700
    chunks = chunk(text, 1600)
    assert len(chunks) > 20
    for c in chunks:
        assert c["end"] - c["start"] <= 1600 + 80
    for m in ("2026-08-03", "1,234.56", "a.b@c.io", "https://x.io/p"):
        _never_split(text, m, 1600)
