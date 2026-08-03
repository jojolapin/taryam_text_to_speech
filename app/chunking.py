"""Semantic text chunker (Python mirror of ui/lib/semantic-chunker.js).

Splits long text at natural boundaries (paragraph -> sentence -> clause ->
whitespace) while never breaking a "protected span": decimals/numbers, dates,
times, initials, listed abbreviations, URLs, and emails. Used for OpenAI audio
export so exported audio matches in-app playback segmentation.

Keep behavior in sync with the JS version. (C) 2026 JojoLapin Inc.
"""
from __future__ import annotations

import re
from typing import Callable, List, Tuple

_ABBREV = (
    "Mr|Mrs|Ms|Dr|Prof|Sr|Jr|St|vs|etc|Inc|Ltd|Co|Corp|Fig|No|Vol|Gen|Sen|Rev|Hon|Capt|Lt|Sgt|"
    "Jan|Feb|Mar|Apr|Jun|Jul|Aug|Sept|Sep|Oct|Nov|Dec|Mon|Tue|Wed|Thu|Fri|Sat|Sun"
)

_PATTERNS = [
    (re.compile(r"https?://\S+", re.I), 0),
    (re.compile(r"www\.\S+", re.I), 0),
    (re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}"), 0),
    (re.compile(r"\d[\d.,:/-]*\d"), 0),
    (re.compile(r"\b(?:[A-Za-z]\.){2,}"), 1),
    (re.compile(r"\b(?:" + _ABBREV + r")\.\s", re.I), 0),
    (re.compile(r"\b(?:e\.g|i\.e|a\.m|p\.m|U\.S|U\.K|Ph\.D)\.?", re.I), 1),
]

_SENT_END = {".", "!", "?", "\u2026"}
_TRAIL = set(".!?\u2026\"'\u201d\u2019)]")
_PARA = re.compile(r"\n[ \t]*\n")


def _build_unsafe(text: str) -> bytearray:
    n = len(text)
    unsafe = bytearray(n + 1)
    for rx, extend in _PATTERNS:
        for m in rx.finditer(text):
            s = m.start()
            e = min(m.end() + extend, n)
            for p in range(s + 1, e):
                unsafe[p] = 1
    return unsafe


def _sentence_boundaries(text: str, is_safe: Callable[[int], bool]) -> List[int]:
    n = len(text)
    bounds = set()
    for m in _PARA.finditer(text):
        p = m.start() + 1
        if is_safe(p):
            bounds.add(p)
    i = 0
    while i < n:
        if text[i] in _SENT_END:
            j = i + 1
            while j < n and text[j] in _TRAIL:
                j += 1
            if (j >= n or text[j].isspace()) and is_safe(j):
                bounds.add(j)
        i += 1
    bounds.add(n)
    return sorted(bounds)


def _split_oversize(text: str, s: int, e: int, max_chars: int,
                    is_safe: Callable[[int], bool]) -> List[Tuple[int, int]]:
    pieces: List[Tuple[int, int]] = []
    start = s
    floor = max(1, max_chars // 4)
    while e - start > max_chars:
        limit = start + max_chars
        brk = -1
        for j in range(limit, start + floor, -1):
            if text[j - 1] in ",;:" and (j >= e or text[j].isspace()) and is_safe(j):
                brk = j
                break
        if brk < 0:
            for j in range(limit, start + floor, -1):
                if text[j].isspace() and is_safe(j):
                    brk = j
                    break
        if brk < 0:
            j = limit
            while j < e and not (text[j].isspace() and is_safe(j)):
                j += 1
            brk = j if j < e else e
        pieces.append((start, brk))
        start = brk
        while start < e and text[start].isspace():
            start += 1
    if start < e:
        pieces.append((start, e))
    return pieces


def chunk(text: str, max_chars: int = 1600) -> List[dict]:
    """Return a list of ``{"text", "start", "end"}`` sections."""
    if not text or not text.strip():
        return []
    max_chars = max(8, int(max_chars) if max_chars else 1600)
    n = len(text)
    unsafe = _build_unsafe(text)

    def is_safe(pos: int) -> bool:
        return pos <= 0 or pos >= n or not unsafe[pos]

    bounds = _sentence_boundaries(text, is_safe)
    sentences: List[Tuple[int, int]] = []
    prev = 0
    for b in bounds:
        s = prev
        while s < b and text[s].isspace():
            s += 1
        if s < b:
            sentences.append((s, b))
        prev = b

    segs: List[Tuple[int, int]] = []
    cur_s = -1
    cur_e = -1
    for (s, e) in sentences:
        if e - s > max_chars:
            if cur_s >= 0:
                segs.append((cur_s, cur_e))
                cur_s = cur_e = -1
            segs.extend(_split_oversize(text, s, e, max_chars, is_safe))
            continue
        if cur_s < 0:
            cur_s, cur_e = s, e
        elif e - cur_s <= max_chars:
            cur_e = e
        else:
            segs.append((cur_s, cur_e))
            cur_s, cur_e = s, e
    if cur_s >= 0:
        segs.append((cur_s, cur_e))

    out: List[dict] = []
    for (s, e) in segs:
        t = text[s:e].strip()
        if t:
            out.append({"text": t, "start": s, "end": e})
    return out


def find_chunk_at_position(chunks: List[dict], pos: int) -> int:
    for i, c in enumerate(chunks):
        if c["end"] > pos:
            return i
    return max(0, len(chunks) - 1)
