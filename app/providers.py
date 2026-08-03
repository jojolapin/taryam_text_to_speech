"""Voice provider registry (metadata + availability).

Playback and synthesis still flow through :class:`TTSEngine` and the bridge; this
module gives a single place to *describe* the available providers so the UI can
show status and (from Phase 3) route requests. Piper is available today; OpenAI
is added later. Kept dependency-free and easy to unit-test.

(C) 2026 JojoLapin Inc.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Dict, List, Optional, Tuple


@dataclass
class ProviderInfo:
    id: str
    label: str
    offline: bool
    requires_network: bool
    is_ai: bool
    available: bool
    detail: str = ""


class VoiceProvider:
    """Base contract. Subclasses describe themselves and report availability."""

    id: str = "base"
    label: str = "Base"
    offline: bool = False
    requires_network: bool = False
    is_ai: bool = False

    def is_available(self) -> Tuple[bool, str]:
        """Return ``(available, detail)``. ``detail`` is a short status string."""
        return True, ""

    def info(self) -> ProviderInfo:
        ok, detail = self.is_available()
        return ProviderInfo(
            id=self.id,
            label=self.label,
            offline=self.offline,
            requires_network=self.requires_network,
            is_ai=self.is_ai,
            available=ok,
            detail=detail,
        )


class PiperProvider(VoiceProvider):
    """Offline, local Piper engine. Available when at least one voice is installed."""

    id = "piper"
    label = "Piper (offline)"
    offline = True
    requires_network = False
    is_ai = False

    def __init__(self, engine) -> None:
        self._engine = engine

    def is_available(self) -> Tuple[bool, str]:
        try:
            voices = self._engine.discover_voices()
        except Exception:  # noqa: BLE001 - availability probe must never raise
            voices = []
        count = len(voices)
        if count:
            return True, f"{count} voice(s) installed"
        return False, "No voices installed"


class ProviderRegistry:
    def __init__(self, default_id: str = "piper") -> None:
        self._providers: Dict[str, VoiceProvider] = {}
        self.default_id = default_id

    def register(self, provider: VoiceProvider) -> VoiceProvider:
        self._providers[provider.id] = provider
        return provider

    def has(self, provider_id: str) -> bool:
        return provider_id in self._providers

    def get(self, provider_id: str) -> Optional[VoiceProvider]:
        return self._providers.get(provider_id) or self._providers.get(self.default_id)

    def ids(self) -> List[str]:
        return list(self._providers.keys())

    def status(self) -> List[dict]:
        """JSON-serializable status for every registered provider."""
        return [asdict(p.info()) for p in self._providers.values()]
