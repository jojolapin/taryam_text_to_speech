"""Tests for speaking-style presets (app/speaking_styles.py).

Run:  .venv\\Scripts\\python -m pytest -q tests/test_speaking_styles.py

(C) 2026 JojoLapin Inc.
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app import speaking_styles as ss  # noqa: E402


def test_default_style_exists_and_is_neutral():
    assert ss.DEFAULT_STYLE == "neutral"
    assert ss.is_valid("neutral")
    assert ss.get("neutral")["instructions"] == ""


def test_all_presets_have_required_fields_and_both_labels():
    presets = ss.all_presets()
    assert len(presets) >= 5
    ids = set()
    for p in presets:
        assert p["id"] and p["id"] not in ids
        ids.add(p["id"])
        assert p["label_en"].strip()
        assert p["label_fr"].strip()
        assert "instructions" in p


def test_all_presets_returns_copies():
    presets = ss.all_presets()
    presets[0]["label_en"] = "MUTATED"
    # Mutating the returned list must not corrupt the source table.
    assert ss.STYLES[ss.DEFAULT_STYLE]["label_en"] != "MUTATED"


def test_get_falls_back_to_default_for_unknown():
    assert ss.get("does-not-exist")["id"] == ss.DEFAULT_STYLE
    assert ss.get(None)["id"] == ss.DEFAULT_STYLE


def test_is_valid():
    assert ss.is_valid("calm") is True
    assert ss.is_valid("nope") is False
    assert ss.is_valid("") is False
    assert ss.is_valid(None) is False


def test_instruction_for_preset():
    assert "news" in ss.instruction_for("newscaster").lower()
    assert ss.instruction_for("neutral") == ""


def test_instruction_for_custom_overrides_preset():
    out = ss.instruction_for("newscaster", custom="  pirate voice  ")
    assert out == "pirate voice"


def test_instruction_for_blank_custom_uses_preset():
    assert ss.instruction_for("calm", custom="   ") == ss.get("calm")["instructions"]
