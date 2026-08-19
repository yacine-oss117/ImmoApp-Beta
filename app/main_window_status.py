"""Main window mixin for status bar setup and timers."""

from __future__ import annotations

import logging
import time
from typing import Protocol, cast

from PySide6.QtCore import QObject, QSettings, QTimer
from PySide6.QtWidgets import QLabel, QStatusBar

from app.constants import APP, ORG
from app.services.db_core import db_health_status
from app.services.network_sync import flush_pending_network_work, get_network_status_snapshot
from app.utils.badge_rules import badge_state
from app.utils.i18n import tr_factory
from app.utils.qt_async import run_background
from app.utils.time_service import (
    _fmt_city_region,
    _fmt_region_city,
    _local_iana_tz,
    _normalize_iana_id,
    apply_auto_tz_refresh_result,
    authoritative_now,
    get_system_tz,
    maybe_resync_if_due,
    should_refresh_auto_tz,
)

logger = logging.getLogger(__name__)
_TR = tr_factory("MainWindowStatus")


class _SignalLike(Protocol):
    def connect(self, slot: object) -> object: ...
    def emit(self, *args: object) -> object: ...


class _StatusHost(Protocol):
    status_bar: QStatusBar
    time_label: QLabel
    loc_label: QLabel
    net_label: QLabel
    db_label: QLabel
    timer: QTimer
    resync_timer: QTimer
    tz_timer: QTimer
    sync_timer: QTimer
    status_message: _SignalLike
    tz_refresh_result: _SignalLike
    _tz_refresh_in_flight: bool
    _tz_refresh_last_attempt: float
    _resync_in_flight: bool
    _sync_in_flight: bool

    def statusBar(self) -> QStatusBar: ...
    def _update_status_bar(self) -> None: ...
    def _update_network_label(self) -> None: ...
    def _kickoff_resync_async(self) -> None: ...
    def _kickoff_network_sync_async(self) -> None: ...
    def _kickoff_tz_refresh_async(self, force: bool = ...) -> None: ...
    def _current_location_label(self) -> str: ...
    def _post_status_message(self, message: str, timeout: int = ...) -> None: ...
    def _apply_tz_refresh_result(self, tz_name: object, nowm: float) -> None: ...
    def _set_time_label_state(self, state: str) -> None: ...


class MainWindowStatusMixin:
    """Handles status bar widgets and periodic background refresh."""

    status_bar: QStatusBar
    time_label: QLabel
    loc_label: QLabel
    net_label: QLabel
    db_label: QLabel
    timer: QTimer
    resync_timer: QTimer
    tz_timer: QTimer
    sync_timer: QTimer
    _tz_refresh_in_flight: bool
    _tz_refresh_last_attempt: float
    _resync_in_flight: bool
    _sync_in_flight: bool

    def _init_status_bar(self: _StatusHost) -> None:
        self.status_bar = self.statusBar()
        self.time_label = QLabel("")
        self.loc_label = QLabel("")
        self.net_label = QLabel("")
        self.db_label = QLabel("")
        self.time_label.setObjectName("statusTimeLabel")
        self.loc_label.setObjectName("statusLocationLabel")
        self.net_label.setObjectName("statusNetworkLabel")
        self.db_label.setObjectName("statusDbLabel")
        self.time_label.setProperty("statusState", "ok")
        self.net_label.setProperty("statusState", "ok")
        self.status_bar.addPermanentWidget(self.time_label)
        self.status_bar.addPermanentWidget(self.loc_label)
        self.status_bar.addPermanentWidget(self.net_label)
        self.status_bar.addPermanentWidget(self.db_label)
        self.status_message.connect(self.status_bar.showMessage)
        self.tz_refresh_result.connect(self._apply_tz_refresh_result)
        self._tz_refresh_in_flight = False
        self._tz_refresh_last_attempt = 0.0
        self._resync_in_flight = False
        self._sync_in_flight = False

        parent_obj = cast(QObject, getattr(self, "_host", self))
        self.timer = QTimer(parent_obj)
        self.timer.timeout.connect(self._update_status_bar)
        self.timer.start(1000)
        self._update_status_bar()

        self._kickoff_resync_async()
        self.resync_timer = QTimer(parent_obj)
        self.resync_timer.timeout.connect(self._kickoff_resync_async)
        self.resync_timer.start(10 * 60 * 1000)

        self.sync_timer = QTimer(parent_obj)
        self.sync_timer.timeout.connect(self._kickoff_network_sync_async)
        self.sync_timer.start(15 * 1000)
        self._kickoff_network_sync_async()

        self._kickoff_tz_refresh_async()
        self.tz_timer = QTimer(parent_obj)
        self.tz_timer.timeout.connect(self._kickoff_tz_refresh_async)
        self.tz_timer.start(6 * 60 * 60 * 1000)

    def _update_status_bar(self: _StatusHost) -> None:
        try:
            s = QSettings(ORG, APP)
            offline = bool(s.value("time/offline_mode", False, bool))
            dt, note = authoritative_now(allow_network=False)
            self.time_label.setText(dt.strftime("%I:%M:%S %p").lstrip("0"))
            self.loc_label.setText(self._current_location_label())
            self.db_label.setText(db_health_status())
            self._update_network_label()

            if offline:
                self._set_time_label_state("offline")
                self.time_label.setToolTip(_TR("{note} (offline mode)").format(note=note))
            else:
                state = badge_state(note)
                self._set_time_label_state(state)
                cached_tz = cast(str, s.value("cache/tz_name", "", str) or "")
                last_tz_refresh = float(
                    cast(float, s.value("cache/tz_refresh_mono", 0.0, float) or 0.0)
                )
                last_status = cast(str, s.value("cache/tz_refresh_status", "", str) or "")
                if not cached_tz or last_status == "fail":
                    self._kickoff_tz_refresh_async(force=True)
                age = ""
                if last_tz_refresh:
                    elapsed = (time.perf_counter() - last_tz_refresh) / 3600.0
                    age = (
                        _TR(" | timezone saved {hours:.1f}h ago").format(hours=elapsed)
                        if elapsed >= 0
                        else ""
                    )
                if last_status == "fail":
                    self._set_time_label_state("error")
                    self.time_label.setToolTip(
                        _TR("{note} | tz fetch failed{age}").format(note=note, age=age)
                    )
                else:
                    self.time_label.setToolTip(_TR("{note}{age}").format(note=note, age=age))
        except (AttributeError, RuntimeError, ValueError, OSError):
            logger.error("Failed to update status bar", exc_info=True)
            self.status_bar.showMessage(_TR("Status bar update failed"), 5000)

    def _update_network_label(self: _StatusHost) -> None:
        snapshot = get_network_status_snapshot(sync_in_flight=self._sync_in_flight)
        state = str(snapshot.get("state") or "online")
        pending_api = int(snapshot.get("pending_api") or 0)
        pending_media = int(snapshot.get("pending_media") or 0)
        pending_creates = int(snapshot.get("pending_creates") or 0)
        failed_api = int(snapshot.get("failed_api") or 0)
        needs_review = int(snapshot.get("needs_review") or 0)
        blocked_ops = int(snapshot.get("blocked_ops") or 0)
        pending_total = int(snapshot.get("pending_total") or 0)
        circuit = cast(dict[str, object], snapshot.get("circuit") or {})
        if state == "offline":
            text = _TR("Net: Offline")
            status_state = "offline"
            tooltip = _TR("Offline mode is enabled. Queued writes will wait for manual reconnect.")
        elif state == "error":
            text = _TR("Net: Sync issues")
            status_state = "error"
            if bool(snapshot.get("store_error", False)):
                tooltip = _TR(
                    "Connection details are temporarily unavailable. The app will check again automatically."
                )
            else:
                tooltip = _TR(
                    "Pending data: {pending}. Pending creates: {creates}. Review needed: {review}. Failed: {failed}."
                ).format(
                    pending=pending_total,
                    creates=pending_creates,
                    review=needs_review,
                    failed=failed_api,
                )
        elif state == "syncing":
            text = _TR("Net: Syncing")
            status_state = "orange"
            tooltip = _TR(
                "Replaying queued work. Pending data: {pending_api}. Pending creates: {creates}. Pending media: {pending_media}."
            ).format(
                pending_api=pending_api,
                creates=pending_creates,
                pending_media=pending_media,
            )
        elif state == "pending":
            text = _TR("Net: Pending {count}").format(count=pending_total)
            status_state = "orange"
            tooltip = _TR(
                "Queued writes are waiting for reconnect. Pending data: {pending_api}. Pending creates: {creates}. Blocked: {blocked}. Pending media: {pending_media}."
            ).format(
                pending_api=pending_api,
                creates=pending_creates,
                blocked=blocked_ops,
                pending_media=pending_media,
            )
        elif state == "degraded":
            text = _TR("Net: Reconnecting")
            status_state = "red"
            open_for_seconds = cast(float | int, circuit.get("open_for_seconds") or 0.0)
            tooltip = _TR(
                "Connection state is {state_name}. Try again in about {open_for:.1f}s."
            ).format(
                state_name=str(circuit.get("state") or "unknown"),
                open_for=float(open_for_seconds),
            )
        else:
            text = _TR("Net: Online")
            status_state = "ok"
            tooltip = _TR(
                "Connected. Pending data: {pending_api}. Pending creates: {creates}. Review needed: {review}. Pending media: {pending_media}."
            ).format(
                pending_api=pending_api,
                creates=pending_creates,
                review=needs_review,
                pending_media=pending_media,
            )

        self.net_label.setText(text)
        self.net_label.setProperty("statusState", status_state)
        self.net_label.setToolTip(tooltip)
        style = self.net_label.style()
        if style is not None:
            style.unpolish(self.net_label)
            style.polish(self.net_label)
        self.net_label.update()

    def _kickoff_resync_async(self: _StatusHost) -> None:
        """Resync time seeds in a background thread to avoid blocking UI."""
        if self._resync_in_flight:
            return
        self._resync_in_flight = True

        def _worker() -> None:
            try:
                maybe_resync_if_due(allow_network=True)
            except (RuntimeError, ValueError):
                logger.error("Resync failed", exc_info=True)
                self._post_status_message(_TR("Time resync failed"), 5000)
            finally:
                self._resync_in_flight = False

        run_background(_worker)

    def _kickoff_tz_refresh_async(self: _StatusHost, force: bool = False) -> None:
        """Refresh auto-detected timezone in a background thread."""
        nowm = time.perf_counter()
        if self._tz_refresh_in_flight:
            return
        if (nowm - self._tz_refresh_last_attempt) < 60.0:
            return
        if not should_refresh_auto_tz(force=force):
            return
        self._tz_refresh_in_flight = True
        self._tz_refresh_last_attempt = nowm

        def _worker() -> None:
            tz_name: str | None = None
            try:
                tz_name = get_system_tz()
            except (RuntimeError, ValueError):
                logger.error("TZ refresh failed", exc_info=True)
            self.tz_refresh_result.emit(tz_name or "", nowm)

        run_background(_worker)

    def _kickoff_network_sync_async(self: _StatusHost) -> None:
        """Flush queued writes/uploads in the background when connectivity recovers."""
        if self._sync_in_flight:
            return
        self._sync_in_flight = True

        def _worker() -> None:
            try:
                summary = flush_pending_network_work()
            except Exception:
                logger.debug("Network sync failed", exc_info=True)
                return
            finally:
                self._sync_in_flight = False

            flushed_api = int(summary.get("flushed_api") or 0)
            flushed_media = int(summary.get("flushed_media") or 0)
            discarded_api = int(summary.get("discarded_api") or 0)
            if flushed_api > 0 or flushed_media > 0:
                self._post_status_message(
                    _TR("Synced {changes} changes and {media} media uploads.").format(
                        changes=flushed_api,
                        media=flushed_media,
                    ),
                    5000,
                )
            if discarded_api > 0:
                self._post_status_message(
                    _TR("{count} queued changes could not be replayed.").format(
                        count=discarded_api,
                    ),
                    5000,
                )

        run_background(_worker)

    def _current_location_label(self: _StatusHost) -> str:
        s = QSettings(ORG, APP)
        force_manual = cast(bool, s.value("time/force_manual_tz", False, bool))
        manual_tz = cast(str, s.value("time/manual_tz", "", str) or "")
        auto_tz = cast(bool, s.value("time/auto_detect_tz", True, bool))
        tzid: str | None = None

        if force_manual and manual_tz:
            norm = _normalize_iana_id(manual_tz) or manual_tz
            return _fmt_region_city(norm)

        if auto_tz:
            wilaya = cast(str, s.value("cache/geo_region", "", str) or "")
            country = cast(str, s.value("cache/geo_country", "", str) or "")
            if wilaya or country:
                parts = [p for p in (wilaya, country) if p]
                return " | ".join(parts)
            tzid = cast(str, s.value("cache/tz_name", "", str) or _local_iana_tz() or "")
            return _fmt_city_region(tzid or "")

        tzid = _local_iana_tz()
        return _fmt_city_region(tzid or _TR("Local | System"))

    def _post_status_message(self: _StatusHost, message: str, timeout: int = 5000) -> None:
        """Post a status message on the UI thread."""
        self.status_message.emit(message, timeout)

    def _set_time_label_state(self: _StatusHost, state: str) -> None:
        self.time_label.setProperty("statusState", state)
        style = self.time_label.style()
        if style is not None:
            style.unpolish(self.time_label)
            style.polish(self.time_label)
        self.time_label.update()

    def _apply_tz_refresh_result(self: _StatusHost, tz_name: object, nowm: float) -> None:
        """Persist timezone refresh results on the UI thread."""
        tz_value = str(tz_name) if isinstance(tz_name, str) and tz_name else None
        status = apply_auto_tz_refresh_result(tz_value, nowm=nowm)
        self._tz_refresh_in_flight = False
        if status == "fail":
            self._post_status_message(_TR("Timezone refresh failed"), 5000)
