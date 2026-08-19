"""Match tab phone menu actions."""

from __future__ import annotations

import logging
import urllib.parse
from typing import cast

from PySide6.QtCore import QUrl
from PySide6.QtGui import QCursor, QDesktopServices, QGuiApplication
from PySide6.QtWidgets import QMenu, QMessageBox, QWidget

from app.services.wa_templates_repository import get_all_templates, render_template
from app.shared_types import TemplateContext
from app.utils.i18n import tr_factory
from app.utils.wa_templates import build_template_context

logger = logging.getLogger(__name__)
_TR = tr_factory("MatchPhoneMenu")


def show_phone_menu(parent: QWidget, phone: str, owner_name: str) -> None:
    """Show context menu for phone button with Copy/WhatsApp options and templates."""
    if not phone:
        return

    menu = QMenu(parent)

    copy_action = menu.addAction(_TR("Copy number"))
    open_wa_action = menu.addAction(_TR("Open WhatsApp"))
    menu.addSeparator()

    # Templates Submenu
    templates_menu = menu.addMenu(_TR("Send template..."))
    templates = get_all_templates()

    if not templates:
        no_tpl = templates_menu.addAction(_TR("(No templates)"))
        no_tpl.setEnabled(False)

    # Context for rendering
    context: TemplateContext = build_template_context(
        client_name=owner_name,
        location=_TR("your property"),
        price=_TR("N/A"),
        property_type=_TR("property"),
    )

    for tpl in templates:
        action = templates_menu.addAction(f"{tpl['name']}")
        action.setData(tpl)

    action = menu.exec(QCursor.pos())
    if not action:
        return

    if action == copy_action:
        cb = QGuiApplication.clipboard()
        cb.setText(phone)
        QMessageBox.information(
            parent,
            _TR("Copied"),
            _TR("Number {phone} copied!").format(phone=phone),
        )
        return

    if action == open_wa_action:
        clean_phone = "".join(c for c in phone if c.isdigit() or c == "+")
        QDesktopServices.openUrl(QUrl(f"https://wa.me/{clean_phone}"))
        return

    if action.parent() == templates_menu:
        tpl = action.data()
        if tpl:
            try:
                message = render_template(
                    tpl["template"],
                    cast(dict[str, str], context),
                )
                encoded_msg = urllib.parse.quote(message)
                clean_phone = "".join(c for c in phone if c.isdigit() or c == "+")
                url = f"https://wa.me/{clean_phone}?text={encoded_msg}"
                QDesktopServices.openUrl(QUrl(url))
            except (OSError, RuntimeError) as exc:
                logger.error("Template send failed", exc_info=True)
                QMessageBox.warning(
                    parent,
                    _TR("Error"),
                    _TR("Send failed: {error}").format(error=exc),
                )
