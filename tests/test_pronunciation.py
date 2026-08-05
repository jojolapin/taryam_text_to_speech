"""Tests for the non-destructive pronunciation layer (app/pronunciation.py).

Run:  .venv\\Scripts\\python -m pytest -q tests/test_pronunciation.py

(C) 2026 JojoLapin Inc.
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app import pronunciation as pr  # noqa: E402


def test_empty_inputs_are_noops():
    assert pr.apply("", [{"from": "a", "to": "b"}]) == ""
    assert pr.apply("hello", []) == "hello"
    assert pr.apply("hello", None) == "hello"


def test_basic_literal_substitution():
    out = pr.apply("Call Dr Smith", [{"from": "Dr", "to": "Doctor"}])
    assert out == "Call Doctor Smith"


def test_case_insensitive_by_default():
    out = pr.apply("WIFI wifi WiFi", [{"from": "wifi", "to": "why-fye"}])
    assert out == "why-fye why-fye why-fye"


def test_case_sensitive_when_requested():
    rules = [{"from": "US", "to": "United States", "match_case": True}]
    out = pr.apply("The US and us", rules)
    assert out == "The United States and us"


def test_whole_word_does_not_touch_substrings():
    rules = [{"from": "cat", "to": "feline", "whole_word": True}]
    out = pr.apply("the cat in concatenation", rules)
    assert out == "the feline in concatenation"


def test_non_whole_word_matches_substrings():
    rules = [{"from": "cat", "to": "X", "whole_word": False}]
    out = pr.apply("concatenate", rules)
    assert out == "conXenate"


def test_phrase_substitution_with_spaces():
    rules = [{"from": "New York", "to": "the Big Apple"}]
    assert pr.apply("I love New York!", rules) == "I love the Big Apple!"


def test_literal_replacement_does_not_interpret_backrefs():
    # A plain (non-regex) rule must treat "\1" in the replacement literally.
    rules = [{"from": "x", "to": r"\1", "whole_word": False}]
    assert pr.apply("x", rules) == r"\1"


def test_regex_rule_with_backreference():
    rules = [{"from": r"(\d+)h(\d+)", "to": r"\1 hours \2", "is_regex": True}]
    assert pr.apply("It is 3h30 now", rules) == "It is 3 hours 30 now"


def test_disabled_rule_is_skipped():
    rules = [{"from": "a", "to": "b", "enabled": False}]
    assert pr.apply("aaa", rules) == "aaa"


def test_rules_apply_in_order():
    rules = [
        {"from": "one", "to": "two"},
        {"from": "two", "to": "three"},
    ]
    # First turns one->two, second then turns that two->three.
    assert pr.apply("one", rules) == "three"


def test_invalid_regex_is_ignored_not_raised():
    rules = [{"from": "(", "to": "x", "is_regex": True}, {"from": "b", "to": "B"}]
    # Bad regex skipped; the following valid (whole-word) rule still runs.
    assert pr.apply("a b", rules) == "a B"


def test_empty_replacement_deletes():
    rules = [{"from": "um", "to": "", "whole_word": True}]
    assert pr.apply("well um yes", rules).replace("  ", " ").strip() == "well yes"


def test_accented_whole_word_boundaries():
    rules = [{"from": "café", "to": "coffee shop"}]
    assert pr.apply("le café ouvre", rules) == "le coffee shop ouvre"


def test_special_needle_edges_like_cpp():
    rules = [{"from": "C++", "to": "C plus plus", "whole_word": True}]
    assert pr.apply("I code in C++.", rules) == "I code in C plus plus."


def test_compile_rules_skips_invalid_and_respects_cap():
    good = [{"from": f"w{i}", "to": "x"} for i in range(3)]
    good.append({"from": "", "to": "nope"})   # invalid: empty needle
    good.append({"from": 123, "to": "nope"})  # invalid: non-string
    compiled = pr.compile_rules(good)
    assert len(compiled) == 3


def test_apply_accepts_precompiled_rules():
    compiled = pr.compile_rules([{"from": "hi", "to": "hello"}])
    assert pr.apply("hi there", compiled) == "hello there"


def test_more_than_max_rules_are_capped():
    rules = [{"from": f"a{i}", "to": "b"} for i in range(pr.MAX_RULES + 50)]
    compiled = pr.compile_rules(rules)
    assert len(compiled) == pr.MAX_RULES
