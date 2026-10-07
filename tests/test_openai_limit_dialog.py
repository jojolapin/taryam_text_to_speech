"""The OpenAI 429 dialog shows the reset time and clickable fix links."""
from __future__ import annotations

from datetime import datetime, timezone

from PySide6.QtWidgets import QLabel, QWidget

from app.openai_limit_dialog import OpenAILimitDialog


class _Settings:
    def __init__(self, language):
        self.language = language

    def get(self, key, default=None):
        if key == "language":
            return self.language
        return default


def _report(**limit):
    base = {
        "kind": "credits",
        "status": 429,
        "code": "credit_balance_exhausted",
        "error_type": "insufficient_quota",
        "message": "You exceeded your current quota, please check your plan and billing details.",
        "request_id": "req_credit1",
        "checked_at": datetime(2026, 10, 5, 20, 9, tzinfo=timezone.utc).timestamp(),
        "resets_at": None,
        "reset_source": "",
        "reset_seconds": None,
        "buckets": [],
    }
    base.update(limit)
    return {"summary": "OpenAI quota exceeded. (credit_balance_exhausted)", "limit": base}


def _texts(dialog):
    return "\n".join(label.text() for label in dialog.findChildren(QLabel))


def test_credit_dialog_shows_proof_and_billing_link():
    window = QWidget()
    window.settings = _Settings("en")
    dialog = OpenAILimitDialog(window, _report())
    text = _texts(dialog)
    assert "credit_balance_exhausted" in text
    assert "req_credit1" in text
    assert "HTTP 429" in text
    assert "https://platform.openai.com/settings/organization/billing/overview" in text
    assert "https://platform.openai.com/usage" in text
    assert "Add prepaid credits" in text
    assert "There is no return date." in text
    assert "openai.limit." not in text
    dialog.close()


def test_french_credit_dialog_is_translated():
    window = QWidget()
    window.settings = _Settings("fr")
    dialog = OpenAILimitDialog(window, _report())
    assert dialog.windowTitle() == "OpenAI a bloqué cette demande"
    text = _texts(dialog)
    assert "Ajouter des crédits" in text
    assert "https://platform.openai.com/settings/organization/billing/overview" in text
    assert "openai.limit." not in text
    dialog.close()


def test_spend_limit_dialog_shows_the_utc_month_reset():
    window = QWidget()
    window.settings = _Settings("en")
    resets = datetime(2026, 11, 1, tzinfo=timezone.utc).timestamp()
    dialog = OpenAILimitDialog(window, _report(
        kind="org_spend",
        code="organization_spend_limit_exceeded",
        resets_at=resets,
        reset_source="monthly-utc",
        reset_seconds=resets - datetime(2026, 10, 5, tzinfo=timezone.utc).timestamp(),
    ))
    text = _texts(dialog)
    assert "2026-11-01 00:00 UTC" in text
    assert "https://platform.openai.com/settings/organization/limits" in text
    assert "https://developers.openai.com/api/docs/guides/spend-limits" in text
    assert "openai.limit." not in text
    dialog.close()


def test_rate_limit_dialog_names_the_header_that_set_the_time():
    window = QWidget()
    window.settings = _Settings("en")
    now = datetime(2026, 10, 5, 20, 9, tzinfo=timezone.utc).timestamp()
    dialog = OpenAILimitDialog(window, _report(
        kind="rate_limit",
        code="rate_limit_exceeded",
        error_type="tokens",
        message="Rate limit reached for tokens.",
        resets_at=now + 360,
        reset_source="x-ratelimit-reset-tokens",
        reset_seconds=360,
        buckets=[{
            "name": "tokens",
            "limit": "200000",
            "remaining": "0",
            "reset_seconds": 360,
            "resets_at": now + 360,
            "reset_header": "x-ratelimit-reset-tokens",
        }],
    ))
    text = _texts(dialog)
    assert "x-ratelimit-reset-tokens" in text
    assert "0 of 200000" in text
    assert "https://developers.openai.com/api/docs/guides/rate-limits" in text
    assert "openai.limit." not in text
    dialog.close()
