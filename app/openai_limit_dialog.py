"""Dialog shown when OpenAI answers HTTP 429.

The numbers, codes, and reset time come from that response. Links open the
OpenAI page that can clear the block.

(C) 2026 JojoLapin Inc.
"""
from __future__ import annotations

import html
from datetime import datetime, timezone

from PySide6.QtCore import Qt, QDateTime, QLocale, QTimeZone, QUrl
from PySide6.QtGui import QDesktopServices, QFont, QPalette
from PySide6.QtWidgets import (
    QDialog, QDialogButtonBox, QFormLayout, QFrame, QHBoxLayout, QLabel,
    QPushButton, QScrollArea, QStyle, QVBoxLayout, QWidget,
)

from .i18n import resolve_lang, t


_LINKS = {
    "billing": "https://platform.openai.com/settings/organization/billing/overview",
    "usage": "https://platform.openai.com/usage",
    "limits": "https://platform.openai.com/settings/organization/limits",
    "projects": "https://platform.openai.com/settings/organization/projects",
    "rate_docs": "https://developers.openai.com/api/docs/guides/rate-limits",
    "error_docs": "https://developers.openai.com/api/docs/guides/error-codes",
    "spend_docs": "https://developers.openai.com/api/docs/guides/spend-limits",
    "help_spend": "https://help.openai.com/en/articles/6614457-troubleshooting-api-usage-and-spend-limits",
}

_ACTIONS = {
    "credits": (
        ("openai.limit.link.add_credits", "billing"),
        ("openai.limit.link.usage", "usage"),
        ("openai.limit.link.limits", "limits"),
    ),
    "quota": (
        ("openai.limit.link.add_credits", "billing"),
        ("openai.limit.link.usage", "usage"),
        ("openai.limit.link.limits", "limits"),
        ("openai.limit.link.errors", "error_docs"),
    ),
    "unknown": (
        ("openai.limit.link.billing", "billing"),
        ("openai.limit.link.limits", "limits"),
        ("openai.limit.link.errors", "error_docs"),
    ),
    "org_spend": (
        ("openai.limit.link.raise_org", "limits"),
        ("openai.limit.link.usage", "usage"),
        ("openai.limit.link.spend_guide", "spend_docs"),
    ),
    "project_spend": (
        ("openai.limit.link.open_projects", "projects"),
        ("openai.limit.link.raise_org", "limits"),
        ("openai.limit.link.usage", "usage"),
    ),
    "usage_limit": (
        ("openai.limit.link.review_usage_limit", "limits"),
        ("openai.limit.link.spend_help", "help_spend"),
        ("openai.limit.link.usage", "usage"),
    ),
    "rate_limit": (
        ("openai.limit.link.rate_limits", "limits"),
        ("openai.limit.link.rate_guide", "rate_docs"),
        ("openai.limit.link.usage", "usage"),
    ),
}


def format_utc(timestamp: float) -> str:
    moment = datetime.fromtimestamp(float(timestamp), timezone.utc)
    return moment.strftime("%Y-%m-%d %H:%M UTC")


def format_local(timestamp: float, lang: str) -> str:
    moment = QDateTime.fromSecsSinceEpoch(int(round(float(timestamp))), QTimeZone.systemTimeZone())
    locale = QLocale(QLocale.Language.French if lang == "fr" else QLocale.Language.English)
    pattern = "dddd d MMMM yyyy, HH:mm:ss" if lang == "fr" else "dddd, MMMM d, yyyy, h:mm:ss AP"
    text = locale.toString(moment, pattern)
    name = datetime.fromtimestamp(float(timestamp)).astimezone().tzname() or ""
    return f"{text} ({name})" if name else text


def relative_wait(seconds: float, lang: str) -> str:
    remaining = max(0, int(round(seconds)))
    if remaining == 0:
        return t("openai.limit.relative.now", lang)
    if remaining < 90:
        key = "openai.limit.relative.one_second" if remaining == 1 else "openai.limit.relative.seconds"
        return t(key, lang, count=remaining)
    minutes = max(1, int(round(remaining / 60)))
    if minutes < 90:
        key = "openai.limit.relative.one_minute" if minutes == 1 else "openai.limit.relative.minutes"
        return t(key, lang, count=minutes)
    hours = max(1, int(round(remaining / 3600)))
    if hours < 36:
        key = "openai.limit.relative.one_hour" if hours == 1 else "openai.limit.relative.hours"
        return t(key, lang, count=hours)
    days = max(1, int(round(remaining / 86400)))
    key = "openai.limit.relative.one_day" if days == 1 else "openai.limit.relative.days"
    return t(key, lang, count=days)


def _source_label(source: str, lang: str) -> str:
    key = "openai.limit.source." + source
    label = t(key, lang)
    return label if label != key else source


class OpenAILimitDialog(QDialog):
    def __init__(self, window, report: dict):
        super().__init__(window)
        self._window = window
        limit = report.get("limit") or {}
        lang = resolve_lang(window.settings.get("language", "system"))
        kind = limit.get("kind") or "unknown"
        if kind not in _ACTIONS:
            kind = "unknown"
        self.setWindowTitle(t("openai.limit.title", lang))
        self.setMinimumWidth(560)
        self.resize(700, 760)

        root = QVBoxLayout(self)
        root.setContentsMargins(18, 16, 18, 14)
        root.setSpacing(10)

        header = QHBoxLayout()
        icon = QLabel()
        icon.setPixmap(self.style().standardIcon(QStyle.StandardPixmap.SP_MessageBoxWarning).pixmap(40, 40))
        header.addWidget(icon, 0, Qt.AlignmentFlag.AlignTop)
        titles = QVBoxLayout()
        headline = QLabel(t("openai.limit.title", lang))
        headline.setWordWrap(True)
        font = QFont(headline.font())
        font.setPointSize(font.pointSize() + 4)
        font.setBold(True)
        headline.setFont(font)
        titles.addWidget(headline)
        kind_line = QLabel(t(f"openai.limit.kind.{kind}", lang))
        kind_line.setWordWrap(True)
        kind_font = QFont(kind_line.font())
        kind_font.setPointSize(kind_font.pointSize() + 1)
        kind_line.setFont(kind_font)
        titles.addWidget(kind_line)
        lead = QLabel(t("openai.limit.lead", lang))
        lead.setWordWrap(True)
        lead.setObjectName("mutedLabel")
        titles.addWidget(lead)
        glance_bits = [f"HTTP {limit.get('status') or 429}"]
        if limit.get("code"):
            glance_bits.append(str(limit["code"]))
        if limit.get("request_id"):
            glance_bits.append(str(limit["request_id"]))
        glance = QLabel("  ·  ".join(glance_bits))
        glance.setWordWrap(True)
        glance.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        titles.addWidget(glance)
        header.addLayout(titles, 1)
        root.addLayout(header)

        root.addWidget(self._section(t("openai.limit.when", lang)))
        when_title, when_detail = self._when(limit, lang, kind)
        when = QLabel(when_title)
        when.setWordWrap(True)
        when_font = QFont(when.font())
        when_font.setPointSize(when_font.pointSize() + 2)
        when_font.setBold(True)
        when.setFont(when_font)
        when.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        root.addWidget(when)
        if when_detail:
            detail = QLabel(when_detail)
            detail.setWordWrap(True)
            detail.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
            root.addWidget(detail)

        root.addWidget(self._section(t("openai.limit.now", lang)))
        action = QLabel(t(f"openai.limit.now.{kind}", lang))
        action.setWordWrap(True)
        root.addWidget(action)
        actions = _ACTIONS[kind]
        primary_key, primary_url_key = actions[0]
        primary = QPushButton(t(primary_key, lang))
        primary.setObjectName("primaryButton")
        primary.clicked.connect(lambda _checked=False, url=_LINKS[primary_url_key]: self._open(url))
        root.addWidget(primary)
        muted = self._muted()
        for key, url_key in actions:
            root.addWidget(self._link(t(key, lang), _LINKS[url_key], muted))

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setStyleSheet("QScrollArea { border: none; background: transparent; }")
        scroll.viewport().setAutoFillBackground(False)
        body = QWidget()
        column = QVBoxLayout(body)
        column.setContentsMargins(0, 4, 8, 0)
        column.setSpacing(8)
        scroll.setWidget(body)
        root.addWidget(scroll, 1)

        column.addWidget(self._section(t("openai.limit.proof", lang)))
        column.addWidget(self._proof(limit, lang))
        said = (limit.get("message") or "").strip()
        if said:
            column.addWidget(self._section(t("openai.limit.said", lang)))
            quote = QLabel(said)
            quote.setWordWrap(True)
            quote.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
            column.addWidget(quote)
        piper = QLabel(t("openai.limit.piper", lang))
        piper.setWordWrap(True)
        piper.setObjectName("mutedLabel")
        column.addWidget(piper)
        column.addStretch(1)

        buttons = QDialogButtonBox()
        close = buttons.addButton(t("openai.limit.close", lang), QDialogButtonBox.ButtonRole.RejectRole)
        close.clicked.connect(self.reject)
        root.addWidget(buttons)

    def _section(self, text: str) -> QLabel:
        label = QLabel(text)
        label.setObjectName("sectionLabel")
        return label

    def _proof(self, limit: dict, lang: str) -> QWidget:
        frame = QFrame()
        form = QFormLayout(frame)
        form.setContentsMargins(0, 0, 0, 0)
        form.setSpacing(4)
        missing = t("openai.limit.missing", lang)
        rows = (
            ("openai.limit.http", f"HTTP {limit.get('status') or 429}"),
            ("openai.limit.code", limit.get("code") or missing),
            ("openai.limit.type", limit.get("error_type") or missing),
            ("openai.limit.request", limit.get("request_id") or missing),
        )
        checked = limit.get("checked_at")
        received = format_local(checked, lang) if checked else missing
        if checked:
            received = f"{received} · {format_utc(checked)}"
        for key, value in (*rows, ("openai.limit.received", received)):
            value_label = QLabel(str(value))
            value_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
            value_label.setWordWrap(True)
            form.addRow(t(key, lang), value_label)
        for bucket in limit.get("buckets") or []:
            name = bucket.get("name") or ""
            label_key = f"openai.limit.bucket.{name}"
            label = t(label_key, lang) if t(label_key, lang) != label_key else name
            remaining = bucket.get("remaining") or missing
            cap = bucket.get("limit") or missing
            text = t("openai.limit.bucket_value", lang, remaining=remaining, limit=cap)
            if bucket.get("resets_at"):
                text += " · " + t("openai.limit.bucket_resets", lang, when=format_local(bucket["resets_at"], lang))
            value_label = QLabel(text)
            value_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
            value_label.setWordWrap(True)
            form.addRow(label, value_label)
        return frame

    def _when(self, limit: dict, lang: str, kind: str) -> tuple[str, str]:
        resets_at = limit.get("resets_at")
        source = limit.get("reset_source") or ""
        if kind == "rate_limit":
            if resets_at:
                headline = t(
                    "openai.limit.when.rate", lang,
                    relative=relative_wait(float(limit.get("reset_seconds") or 0), lang),
                    when=format_local(resets_at, lang),
                )
                detail = ""
                if source:
                    detail = t("openai.limit.when.rate_source", lang, source=_source_label(source, lang))
                return headline, detail
            return t("openai.limit.when.rate_unknown", lang), t("openai.limit.when.rate_unknown_detail", lang)
        if kind in {"org_spend", "project_spend"} and resets_at:
            return (
                t("openai.limit.when.monthly", lang, when=format_local(resets_at, lang)),
                t("openai.limit.when.monthly_detail", lang, utc=format_utc(resets_at)),
            )
        if kind == "credits":
            return t("openai.limit.when.credits", lang), t("openai.limit.when.credits_detail", lang)
        if kind == "usage_limit":
            return t("openai.limit.when.usage", lang), t("openai.limit.when.usage_detail", lang)
        if kind == "quota":
            return t("openai.limit.when.quota", lang), t("openai.limit.when.quota_detail", lang)
        return t("openai.limit.when.unknown", lang), t("openai.limit.when.unknown_detail", lang)

    def _link(self, label: str, url: str, muted: str) -> QLabel:
        link = QLabel(
            f'<a href="{html.escape(url, quote=True)}">{html.escape(label)}</a>'
            f'<br><span style="color:{muted}">{html.escape(url)}</span>'
        )
        link.setOpenExternalLinks(True)
        link.setTextInteractionFlags(Qt.TextInteractionFlag.TextBrowserInteraction)
        link.setWordWrap(True)
        return link

    def _muted(self) -> str:
        color = self.palette().color(QPalette.ColorRole.Window)
        return "#a3aec9" if color.lightness() < 128 else "#5a6682"

    @staticmethod
    def _open(url: str) -> None:
        QDesktopServices.openUrl(QUrl(url))
