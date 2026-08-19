"""
Match tab action handlers.
"""

from __future__ import annotations

import logging
from functools import partial
from typing import Any, cast

from PySide6.QtWidgets import QWidget

from app.services.match_models import ClientMatchResult
from app.utils.i18n import tr_factory
from app.views.base import QMessageBox
from app.views.match_state import MatchSettings, save_match_settings
from app.widgets.user_feedback import (
    UserFacingMessage,
    build_info_message,
    map_exception_to_user_message,
)

logger = logging.getLogger(__name__)
_TR = tr_factory("MatchTab")


class MatchTabActionsMixin:
    """Action handlers extracted from MatchTab."""

    _dropdown_controller: Any
    _worker_controller: Any
    _results_controller: Any
    run_btn: Any
    threshold: Any
    limit: Any
    min_matches: Any
    progress_label: Any
    _run_btn_default_text: str
    _match_counts_dirty_flag: bool
    _last_match_result: ClientMatchResult | None

    def mark_all_dirty(self) -> None: ...

    def _emit_feedback(
        self, message: UserFacingMessage, auto_dismiss_ms: int | None = None
    ) -> None:
        callback = getattr(self, "_show_feedback", None)
        if callable(callback):
            callback(message, auto_dismiss_ms)
            return
        body = message.message
        if message.action_hint:
            body = f"{body} {message.action_hint}".strip()
        if message.severity in {"success", "info"}:
            QMessageBox.information(cast(QWidget, self), message.title, body)
        else:
            QMessageBox.warning(cast(QWidget, self), message.title, body)

    def _on_run_match_clicked(self) -> None:
        """Run matching for selected client and display results."""
        client_id = self._dropdown_controller.get_selected_client_id()
        if not client_id:
            self._emit_feedback(
                build_info_message(
                    title=_TR("Select a client"),
                    message=_TR("Choose a client first, then run matching."),
                ),
                auto_dismiss_ms=5000,
            )
            return

        self._maybe_refresh_dirty_counts()

        self.run_btn.setEnabled(False)
        self.run_btn.setText(_TR("Matching..."))

        try:
            score_threshold = float(self.threshold.value())
        except (RuntimeError, ValueError) as exc:
            self._emit_feedback(
                map_exception_to_user_message(exc, context="match.run"),
            )
            self.run_btn.setEnabled(True)
            self.run_btn.setText(self._run_btn_default_text)
            return

        self._worker_controller.run_match(
            client_id,
            limit_per_demande=int(self.limit.value()),
            score_threshold=score_threshold,
            on_ready=partial(self._on_match_ready, score_threshold=score_threshold),
            on_error=self._on_match_error,
        )

    def _on_full_count_ready(self, client_id: int, count: int) -> None:
        """Update header and cached counts after full count computes."""
        if not self._last_match_result or self._last_match_result.client_id != client_id:
            return
        self._results_controller.update_full_count(count)
        self._dropdown_controller.sync_match_count(client_id, count)

    def _on_match_ready(self, result: ClientMatchResult, *, score_threshold: float) -> None:
        """Handle completion of the match run worker."""
        self._last_match_result = result
        self._results_controller.display_results(result, score_threshold, full_count=None)

        if score_threshold > 0:
            self._worker_controller.compute_full_count(
                result.client_id,
                on_ready=self._on_full_count_ready,
            )
        else:
            self._dropdown_controller.sync_match_count(
                result.client_id,
                result.total_unique_offers,
            )

        self.run_btn.setEnabled(True)
        self.run_btn.setText(self._run_btn_default_text)

    def _on_match_error(self, error: str) -> None:
        """Report match failure from the worker."""
        self._emit_feedback(
            map_exception_to_user_message(RuntimeError(error), context="match.run"),
        )
        self.run_btn.setEnabled(True)
        self.run_btn.setText(self._run_btn_default_text)

    def _save_settings(self) -> None:
        """Persist match settings to QSettings."""
        settings = MatchSettings(
            score_threshold=float(self.threshold.value()),
            limit_per_demande=int(self.limit.value()),
            min_matches=int(self.min_matches.value()),
        )
        save_match_settings(settings)

    def _set_progress_state(self, state: str) -> None:
        self.progress_label.setProperty("immoState", state)
        style = self.progress_label.style()
        if style is not None:
            style.unpolish(self.progress_label)
            style.polish(self.progress_label)
        self.progress_label.update()

    def _reset_progress_style(self) -> None:
        self._set_progress_state("muted")

    def _maybe_refresh_dirty_counts(self) -> None:
        if self._match_counts_dirty_flag:
            self._match_counts_dirty_flag = False
            self.mark_all_dirty()
