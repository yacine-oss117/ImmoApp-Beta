"""Menu construction and language handling for the main window."""

from __future__ import annotations

from collections.abc import Callable
from functools import partial
from typing import Protocol, cast

from PySide6.QtCore import QObject, QSettings
from PySide6.QtGui import QAction, QActionGroup
from PySide6.QtWidgets import QApplication, QMenu, QMenuBar, QMessageBox, QWidget

from app.constants import APP, ORG
from app.services.api_config import get_api_config
from app.services.offline_account_scope import get_active_account_scope
from app.services.ui_capabilities import (
    UiCapabilities,
    load_capabilities,
    normalize_account_key,
    refresh_capabilities_async,
)
from app.utils.i18n import LANGUAGE_KEY, install_translator, tr_factory

_TR = tr_factory("MainWindowMenus")


class _MenuHost(Protocol):
    _menu_actions: dict[str, QAction]
    _admin_menu: QMenu | None
    _settings_menu: QMenu | None

    def menuBar(self) -> QMenuBar: ...
    def _host_object(self) -> QObject: ...
    def _host_widget(self) -> QWidget: ...
    def _disconnect_session(self) -> None: ...
    def _open_notifications(self) -> None: ...
    def _backup_database_manual(self) -> None: ...
    def _open_time_settings(self) -> None: ...
    def _open_wa_templates(self) -> None: ...
    def _open_agency_settings(self) -> None: ...
    def _open_user_management(self) -> None: ...
    def _open_security_settings(self) -> None: ...
    def _open_session_manager(self) -> None: ...
    def _open_contract_builder(self) -> None: ...
    def _open_communes_manager(self) -> None: ...
    def _open_trash_dialog(self) -> None: ...
    def _open_audit_logs(self) -> None: ...
    def _open_storage_delete(self) -> None: ...
    def _open_health_dialog(self) -> None: ...
    def _open_sync_issues(self) -> None: ...
    def _open_send_diagnostics(self) -> None: ...
    def _open_support_bundle(self) -> None: ...
    def _open_security_controls(self) -> None: ...
    def _open_welcome_guide(self) -> None: ...
    def _add_action(self, menu: QMenu, label: str, handler: Callable[..., object]) -> QAction: ...
    def _register_action(
        self,
        action_key: str,
        menu: QMenu,
        label: str,
        handler: Callable[..., object],
    ) -> QAction: ...
    def _apply_capability_visibility(self, capabilities: UiCapabilities) -> None: ...
    def _init_language_menu(self, menu: QMenu) -> None: ...
    def _init_theme_menu(self, menu: QMenu) -> None: ...
    def _set_language(self, language_code: str, _checked: bool = False) -> None: ...
    def _set_theme(self, theme_name: str, _checked: bool = False) -> None: ...
    def _current_theme(self) -> str: ...
    def _set_density(self, density_name: str, _checked: bool = False) -> None: ...
    def _current_density(self) -> str: ...
    def _qt_app(self) -> QApplication | None: ...


class MainWindowMenuMixin:
    """Mixin providing menu bar construction and language handling."""

    def _host_object(self) -> QObject:
        return cast(QObject, getattr(self, "_host", self))

    def _host_widget(self) -> QWidget:
        return cast(QWidget, getattr(self, "_host", self))

    def _init_menus(self: _MenuHost) -> None:
        menubar = self.menuBar()
        menubar.setObjectName("immoMainMenuBar")
        menubar.setAccessibleName(_TR("Main menu"))

        self._menu_actions: dict[str, QAction] = {}
        self._admin_menu: QMenu | None = None
        self._settings_menu: QMenu | None = None

        config = get_api_config()
        scope = get_active_account_scope()
        account_key = (
            normalize_account_key(
                api_base=scope.api_base,
                agency_id=scope.agency_id,
                user_id=scope.user_id,
            )
            if scope is not None
            else normalize_account_key(api_base=config.base_url, username=config.username)
        )
        capabilities = load_capabilities(account_key)

        settings_menu = menubar.addMenu(_TR("Settings"))
        settings_menu.setObjectName("immoMenuSettings")
        settings_menu.menuAction().setObjectName("immoMenuSettingsAction")
        self._settings_menu = settings_menu
        language_menu = menubar.addMenu(_TR("Language"))
        language_menu.setObjectName("immoMenuLanguage")
        language_menu.menuAction().setObjectName("immoMenuLanguageAction")
        theme_menu = menubar.addMenu(_TR("Theme"))
        theme_menu.setObjectName("immoMenuTheme")
        theme_menu.menuAction().setObjectName("immoMenuThemeAction")
        self._init_language_menu(language_menu)
        self._init_theme_menu(theme_menu)

        account_menu = menubar.addMenu(_TR("My Account"))
        account_menu.setObjectName("immoMenuAccount")
        account_menu.menuAction().setObjectName("immoMenuAccountAction")
        notifications_action = self._register_action(
            "account.notifications",
            account_menu,
            _TR("Notifications"),
            self._open_notifications,
        )
        notifications_action.setShortcut("Ctrl+Alt+N")
        self._register_action(
            "account.sign_out",
            account_menu,
            _TR("Sign out"),
            self._disconnect_session,
        )
        self._register_action(
            "account.security",
            account_menu,
            _TR("Security"),
            self._open_security_settings,
        )
        self._register_action(
            "account.devices",
            account_menu,
            _TR("Your Devices"),
            self._open_session_manager,
        )
        self._register_action(
            "account.report_problem",
            account_menu,
            _TR("Report a Problem"),
            self._open_send_diagnostics,
        )
        self._register_action(
            "account.welcome_guide",
            account_menu,
            _TR("Welcome Guide"),
            self._open_welcome_guide,
        )

        self._register_action(
            "settings.date_time",
            settings_menu,
            _TR("Date & Time"),
            self._open_time_settings,
        )
        self._register_action(
            "settings.templates",
            settings_menu,
            _TR("Message Templates"),
            self._open_wa_templates,
        )
        agency_profile_action = self._register_action(
            "settings.agency_profile",
            settings_menu,
            _TR("Agency Profile"),
            self._open_agency_settings,
        )
        agency_profile_action.setShortcut("Ctrl+Alt+P")
        self._register_action(
            "settings.team_members",
            settings_menu,
            _TR("Team Members"),
            self._open_user_management,
        )
        self._register_action(
            "settings.recently_deleted",
            settings_menu,
            _TR("Recently Deleted"),
            self._open_trash_dialog,
        )
        self._register_action(
            "settings.activity_history",
            settings_menu,
            _TR("Activity History"),
            self._open_audit_logs,
        )
        self._register_action(
            "settings.connection_status",
            settings_menu,
            _TR("Connection Status"),
            self._open_health_dialog,
        )
        self._register_action(
            "settings.sync_issues",
            settings_menu,
            _TR("Sync Issues"),
            self._open_sync_issues,
        )
        self._register_action(
            "settings.report_problem",
            settings_menu,
            _TR("Report a Problem"),
            self._open_send_diagnostics,
        )
        self._register_action(
            "settings.support_bundle",
            settings_menu,
            _TR("Export Support Bundle"),
            self._open_support_bundle,
        )

        contracts_menu = menubar.addMenu(_TR("Contracts"))
        contracts_menu.setObjectName("immoMenuContracts")
        contracts_menu.menuAction().setObjectName("immoMenuContractsAction")
        self._register_action(
            "contracts.new",
            contracts_menu,
            _TR("New Contract"),
            self._open_contract_builder,
        )

        communes_menu = menubar.addMenu(_TR("Locations"))
        communes_menu.setObjectName("immoMenuLocations")
        communes_menu.menuAction().setObjectName("immoMenuLocationsAction")
        self._register_action(
            "locations.manage",
            communes_menu,
            _TR("Manage Locations"),
            self._open_communes_manager,
        )

        admin_menu = menubar.addMenu(_TR("Admin"))
        admin_menu.setObjectName("immoMenuAdmin")
        admin_menu.menuAction().setObjectName("immoMenuAdminAction")
        self._admin_menu = admin_menu
        self._register_action(
            "admin.storage_delete",
            admin_menu,
            _TR("Delete Storage Object"),
            self._open_storage_delete,
        )
        self._register_action(
            "admin.security_controls",
            admin_menu,
            _TR("Security Controls"),
            self._open_security_controls,
        )
        self._register_action(
            "admin.backup_now",
            admin_menu,
            _TR("Backup Now"),
            self._backup_database_manual,
        )

        self._apply_capability_visibility(capabilities)
        refresh_capabilities_async(account_key, self._apply_capability_visibility)

    def _add_action(
        self: _MenuHost, menu: QMenu, label: str, handler: Callable[..., object]
    ) -> QAction:
        action = cast(QAction, QAction(label, self._host_object()))
        action.triggered.connect(handler)
        menu.addAction(action)
        return action

    def _register_action(
        self: _MenuHost,
        action_key: str,
        menu: QMenu,
        label: str,
        handler: Callable[..., object],
    ) -> QAction:
        action = self._add_action(menu, label, handler)
        action.setObjectName(f"menuAction_{action_key.replace('.', '_')}")
        self._menu_actions[action_key] = action
        return action

    def _apply_capability_visibility(self: _MenuHost, capabilities: UiCapabilities) -> None:
        team_action = self._menu_actions.get("settings.team_members")
        if team_action is not None:
            team_action.setVisible(bool(capabilities.can_manage_team))

        history_action = self._menu_actions.get("settings.activity_history")
        if history_action is not None:
            history_action.setVisible(bool(capabilities.can_view_activity))

        security_action = self._menu_actions.get("account.security")
        devices_action = self._menu_actions.get("account.devices")
        if security_action is not None:
            security_action.setVisible(bool(capabilities.can_view_security))
        if devices_action is not None:
            devices_action.setVisible(bool(capabilities.can_view_security))

        if self._admin_menu is not None:
            self._admin_menu.menuAction().setVisible(bool(capabilities.can_open_admin_tools))

    def _init_language_menu(self: _MenuHost, menu: QMenu) -> None:
        settings = QSettings(ORG, APP)
        raw = settings.value(LANGUAGE_KEY, "auto", str)
        current = str(raw).strip() if raw else "auto"

        group = QActionGroup(self._host_object())
        group.setExclusive(True)

        options: list[tuple[str, str]] = [
            (_TR("System Default"), "auto"),
            (_TR("French (FR)"), "fr_FR"),
            (_TR("Arabic (DZ)"), "ar_DZ"),
        ]

        for label, code in options:
            action = QAction(label, self._host_object())
            action.setCheckable(True)
            action.setChecked(code == current)
            action.triggered.connect(partial(self._set_language, code))
            group.addAction(action)
            menu.addAction(action)

    def _init_theme_menu(self: _MenuHost, menu: QMenu) -> None:
        current = self._current_theme()
        group = QActionGroup(self._host_object())
        group.setExclusive(True)

        options: list[tuple[str, str]] = [
            (_TR("Dark"), "dark"),
            (_TR("Light"), "light"),
        ]
        for label, code in options:
            action = QAction(label, self._host_object())
            action.setCheckable(True)
            action.setChecked(code == current)
            action.triggered.connect(partial(self._set_theme, code))
            group.addAction(action)
            menu.addAction(action)

        density_menu = menu.addMenu(_TR("Density"))
        current_density = self._current_density()
        density_group = QActionGroup(self._host_object())
        density_group.setExclusive(True)
        density_options: list[tuple[str, str]] = [
            (_TR("Compact"), "compact"),
            (_TR("Comfortable"), "comfortable"),
        ]
        for label, code in density_options:
            action = QAction(label, self._host_object())
            action.setCheckable(True)
            action.setChecked(code == current_density)
            action.triggered.connect(partial(self._set_density, code))
            density_group.addAction(action)
            density_menu.addAction(action)

    def _set_language(self: _MenuHost, language_code: str, _checked: bool = False) -> None:
        settings = QSettings(ORG, APP)
        settings.setValue(LANGUAGE_KEY, language_code)
        settings.sync()

        app = self._qt_app()
        if app is not None:
            install_translator(app, language_code)

        QMessageBox.information(
            self._host_widget(),
            _TR("Language Updated"),
            _TR("Language changes fully apply after restarting the app."),
        )

    def _qt_app(self: _MenuHost) -> QApplication | None:  # pragma: no cover - thin wrapper
        return cast(QApplication | None, QApplication.instance())
