"""
Match tab state helpers (selection + settings).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import cast

from app.views.base import APP, ORG, QSettings
from app.views.match_dropdown import ClientDropdownData


@dataclass(frozen=True)
class MatchSettings:
    """Persisted match tab settings."""

    score_threshold: float
    limit_per_demande: int
    min_matches: int


def load_match_settings() -> MatchSettings:
    """Load match settings from QSettings."""
    settings = QSettings(ORG, APP)
    raw_threshold = settings.value("ui/match/threshold", 0.0, float)
    raw_limit = settings.value("ui/match/limit", 20, int)
    raw_min_matches = settings.value("ui/match/min_matches", 0, int)
    score_threshold = float(cast(float, raw_threshold or 0.0))
    limit_per_demande = int(cast(int, raw_limit or 20))
    min_matches = int(cast(int, raw_min_matches or 0))
    return MatchSettings(
        score_threshold=score_threshold,
        limit_per_demande=limit_per_demande,
        min_matches=min_matches,
    )


def save_match_settings(settings: MatchSettings) -> None:
    """Persist match settings to QSettings."""
    store = QSettings(ORG, APP)
    store.setValue("ui/match/threshold", settings.score_threshold)
    store.setValue("ui/match/limit", settings.limit_per_demande)
    store.setValue("ui/match/min_matches", settings.min_matches)


@dataclass
class MatchSelectionState:
    """Tracks dropdown mappings to resolve selected client IDs."""

    id_map: dict[str, int] = field(default_factory=dict)
    ids_by_index: list[int] = field(default_factory=list)

    def update(self, dropdown: ClientDropdownData) -> None:
        self.id_map = dropdown.id_map
        self.ids_by_index = dropdown.ids_by_index

    def get_selected_id(self, current_index: int, current_text: str) -> int:
        if 0 <= current_index < len(self.ids_by_index):
            return self.ids_by_index[current_index]
        return self.id_map.get(current_text, 0)

    def find_index_for_id(self, client_id: int) -> int | None:
        for index, cid in enumerate(self.ids_by_index):
            if cid == client_id:
                return index
        return None

    def find_text_for_id(self, client_id: int) -> str | None:
        for text, cid in self.id_map.items():
            if cid == client_id:
                return text
        return None
