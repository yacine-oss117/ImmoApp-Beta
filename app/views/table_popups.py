"""
Shared popup menu helpers for table actions.
"""

from __future__ import annotations

import urllib.parse

from PySide6.QtCore import QUrl
from PySide6.QtGui import QCursor, QDesktopServices, QGuiApplication
from PySide6.QtWidgets import QMenu, QMessageBox, QWidget

from app.utils.i18n import tr_factory
from app.utils.wa import ensure_whatsapp_open_then_open_chat

_TR = tr_factory("TablePopups")


def show_phone_menu(parent: QWidget, phone: str) -> None:
    """Show context menu for phone actions."""
    menu = QMenu(parent)
    menu.setProperty("immoMenuRole", "context")

    copy_action = menu.addAction(_TR("Copy Phone"))
    whatsapp_action = menu.addAction(_TR("Open WhatsApp"))
    menu.addSeparator()
    menu.addAction(_TR("Cancel"))

    action = menu.exec_(QCursor.pos())

    if action == copy_action:
        clipboard = QGuiApplication.clipboard()
        clipboard.setText(phone)
        QMessageBox.information(
            parent,
            _TR("Copied"),
            _TR("Phone {phone} copied to clipboard!").format(phone=phone),
        )
    elif action == whatsapp_action:
        ensure_whatsapp_open_then_open_chat(parent, phone)


def show_location_menu(parent: QWidget, location: str) -> None:
    """Show context menu for location actions."""
    menu = QMenu(parent)
    menu.setProperty("immoMenuRole", "context")

    copy_action = menu.addAction(_TR("Copy Location"))
    maps_action = menu.addAction(_TR("Open in Maps"))
    menu.addSeparator()
    menu.addAction(_TR("Cancel"))

    action = menu.exec_(QCursor.pos())

    if action == copy_action:
        clipboard = QGuiApplication.clipboard()
        clipboard.setText(location)
        QMessageBox.information(
            parent,
            _TR("Copied"),
            _TR("Location copied to clipboard!"),
        )
    elif action == maps_action:
        query = urllib.parse.quote(f"{location}, Algeria")
        QDesktopServices.openUrl(QUrl(f"https://www.google.com/maps/search/{query}"))
