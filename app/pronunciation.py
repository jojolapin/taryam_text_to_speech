"""Non-destructive pronunciation substitutions for narration.

A *pronunciation rule* rewrites how a word or phrase is **spoken** without ever
touching the text the user sees in the editor. Rules are applied to the string
that is handed to the TTS engine (Piper or OpenAI), right after markdown/HTML
normalization, so both live playback and file export stay consistent.

Rule shape (plain dict, JSON-friendly so it round-trips through QSettings and the
per-document workspace snapshot)::

    {
        "from": "Dr.",          # what to look for (required, non-empty)
        "to": "Doctor",         # what to speak instead (may be empty = delete)
        "whole_word": true,     # match on word boundaries only (default true)
        "match_case": false,    # case-sensitive match (default false)
        "is_regex": false,      # treat ``from`` as a regular expression
        "enabled": true         # inactive rules are skipped (default true)
    }

Design goals:

* Zero external dependencies.
* Deterministic and order-preserving (rules apply top to bottom).
* Defensive: a malformed or catastrophic rule is skipped, never crashes TTS.
* Literal ``to`` by default (a plain replacement never interprets ``\\1`` etc.);
  back-references are only honoured for explicit ``is_regex`` rules.

(C) 2026 JojoLapin Inc.
"""
from __future__ import annotations

import re
from typing import Any, Iterable, List, Mapping, Optional, Tuple

__all__ = ("compile_rules", "apply", "MAX_RULES")


# A generous ceiling so a corrupted settings blob can never lock up the worker
# thread by compiling tens of thousands of patterns.
MAX_RULES = 500

# Cap on total input length a single regex rule is run against unbounded; the
# real text is chunked upstream so this is only a guard for pathological calls.
_CompiledRule = Tuple[re.Pattern[str], Any]


def _as_bool(value: Any, default: bool) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "on"}
    return default


def _boundary_wrap(escaped: str) -> str:
    """Wrap a (already escaped) needle so it only matches as a whole word.

    Uses look-arounds instead of ``\\b`` so multi-word phrases and needles that
    start/end with non-word characters (e.g. ``C++``) still behave sensibly.
    """
    left = r"(?<!\w)" if escaped[:1].isalnum() or escaped[:1] == "_" else ""
    right = r"(?!\w)" if escaped[-1:].isalnum() or escaped[-1:] == "_" else ""
    return f"{left}{escaped}{right}"


def _compile_one(rule: Mapping[str, Any]) -> Optional[_CompiledRule]:
    """Compile a single rule dict into ``(pattern, replacement)`` or ``None``."""
    if not isinstance(rule, Mapping):
        return None
    if not _as_bool(rule.get("enabled", True), True):
        return None

    needle = rule.get("from", "")
    if not isinstance(needle, str) or not needle:
        return None
    repl = rule.get("to", "")
    if not isinstance(repl, str):
        repl = ""

    is_regex = _as_bool(rule.get("is_regex", False), False)
    whole_word = _as_bool(rule.get("whole_word", True), True)
    match_case = _as_bool(rule.get("match_case", False), False)

    flags = re.UNICODE | (0 if match_case else re.IGNORECASE)

    try:
        if is_regex:
            pattern = re.compile(needle, flags)
            # Regex rules may use back-references in the replacement.
            replacement: Any = repl
        else:
            escaped = re.escape(needle)
            if whole_word:
                escaped = _boundary_wrap(escaped)
            pattern = re.compile(escaped, flags)
            # Literal replacement: a function avoids interpreting ``\1`` / ``\g``.
            replacement = (lambda r: (lambda _m: r))(repl)
    except re.error:
        return None
    return pattern, replacement


def compile_rules(rules: Optional[Iterable[Mapping[str, Any]]]) -> List[_CompiledRule]:
    """Compile an iterable of rule dicts, skipping any that are invalid."""
    compiled: List[_CompiledRule] = []
    if not rules:
        return compiled
    for i, rule in enumerate(rules):
        if i >= MAX_RULES:
            break
        one = _compile_one(rule)
        if one is not None:
            compiled.append(one)
    return compiled


def apply(text: str, rules: Optional[Iterable[Mapping[str, Any]]]) -> str:
    """Return ``text`` with every enabled rule applied, in order.

    ``rules`` may be raw dicts (they are compiled on the fly) or a pre-compiled
    list from :func:`compile_rules`. Invalid rules are ignored. The input is
    returned unchanged when there is nothing to do.
    """
    if not text or not rules:
        return text

    rules = list(rules)
    if rules and isinstance(rules[0], tuple):
        compiled: List[_CompiledRule] = rules  # already compiled
    else:
        compiled = compile_rules(rules)

    out = text
    for pattern, replacement in compiled:
        try:
            out = pattern.sub(replacement, out)
        except re.error:
            # A pathological back-reference in a user regex — skip that rule.
            continue
    return out
