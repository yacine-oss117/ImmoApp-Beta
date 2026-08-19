"""WhatsApp integration helpers."""

import logging
import os
import platform
import subprocess
import sys
from collections.abc import Sequence
from urllib.parse import quote

from PySide6.QtCore import QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import QMessageBox, QWidget

from app.shared_types import TemplateContext
from app.utils.common import phone_digits
from app.utils.i18n import tr_factory

logger = logging.getLogger(__name__)
_TR = tr_factory("WhatsApp")
DEFAULT_COUNTRY_CODE = os.environ.get("IMMOAPP_DEFAULT_COUNTRY_CODE", "213")

_SAFE_COMMANDS = {
    ("/usr/bin/osascript", "-e", 'id of app "WhatsApp"'),
    ("xdg-mime", "query", "default", "x-scheme-handler/whatsapp"),
    ("tasklist",),
    (
        "/usr/bin/osascript",
        "-e",
        'tell app "System Events" to (name of processes) contains "WhatsApp"',
    ),
}


def _safe_check_output(args: Sequence[str], *, creationflags: int = 0) -> bytes:
    command = tuple(args)
    if command not in _SAFE_COMMANDS:
        raise ValueError("Unsupported command")
    return subprocess.check_output(list(command), creationflags=creationflags)


def to_wa_digits(phone: str, default_cc: str = DEFAULT_COUNTRY_CODE) -> str:
    """Normalize phone into WhatsApp E.164 digits."""
    raw = (phone or "").strip()
    d = phone_digits(raw)
    if not d:
        return ""
    if raw.startswith("+"):
        return d
    if raw.startswith("00"):
        return d[2:]
    if raw.startswith("0"):
        return f"{default_cc}{d[1:]}" if len(d) >= 2 else ""
    return d


def _qurl_desktop_consumer(digits: str) -> QUrl:
    return QUrl(f"whatsapp://send?phone={digits}")


def _qurl_web_consumer(digits: str) -> QUrl:
    return QUrl(f"https://wa.me/{digits}?app_absent=0")


def _is_whatsapp_consumer_registered() -> bool:
    """Detect if the whatsapp:// protocol is registered (Windows/macOS)."""
    if sys.platform.startswith("win"):
        try:
            import winreg

            roots = [winreg.HKEY_CLASSES_ROOT, winreg.HKEY_CURRENT_USER]
            paths = [r"whatsapp", r"Software\\Classes\\whatsapp"]
            for root in roots:
                for p in paths:
                    try:
                        k = winreg.OpenKey(root, p)
                        _ = winreg.QueryValueEx(k, "URL Protocol")
                        return True
                    except FileNotFoundError:
                        logger.debug("WhatsApp registry key not found: %s\\%s", root, p)
                        continue
        except (OSError, ImportError) as exc:
            logger.warning("WhatsApp registry check failed: %s", exc)
            return False
        return False

    if sys.platform == "darwin":
        try:
            out = _safe_check_output(["/usr/bin/osascript", "-e", 'id of app "WhatsApp"'])
            return bool(out)
        except (subprocess.CalledProcessError, OSError):
            logger.debug("WhatsApp macOS detection failed", exc_info=True)
            return False

    if sys.platform.startswith("linux"):
        try:
            out = _safe_check_output(["xdg-mime", "query", "default", "x-scheme-handler/whatsapp"])
            return bool(out.strip())
        except (subprocess.CalledProcessError, OSError):
            logger.debug("WhatsApp linux detection failed", exc_info=True)
            return False

    return False


def _is_whatsapp_running() -> bool:
    """Check if WhatsApp desktop is currently running (best-effort)."""
    system = platform.system().lower()
    try:
        if system == "windows":
            out = _safe_check_output(
                ["tasklist"], creationflags=0x08000000 if sys.platform.startswith("win") else 0
            )
            txt = out.decode(errors="ignore").lower()
            return any(
                name in txt for name in ("whatsapp.exe", "whatsappbeta.exe", "whatsapp desktop")
            )
        if system == "darwin":
            out = _safe_check_output(
                [
                    "/usr/bin/osascript",
                    "-e",
                    'tell app "System Events" to (name of processes) contains "WhatsApp"',
                ]
            )
            return out.strip().lower() == b"true"
    except (subprocess.CalledProcessError, OSError):
        logger.debug("WhatsApp running check failed", exc_info=True)
        return False
    return False


def ensure_whatsapp_open_then_open_chat(parent: QWidget, phone: str) -> str:
    """Open WhatsApp chat; falls back to web when desktop is unavailable."""
    digits = to_wa_digits(phone, default_cc=DEFAULT_COUNTRY_CODE)
    if not digits:
        QMessageBox.warning(
            parent,
            _TR("WhatsApp"),
            _TR("This record has no valid phone number."),
        )
        return "invalid"

    # Try desktop protocol if registered
    if _is_whatsapp_consumer_registered():
        if QDesktopServices.openUrl(_qurl_desktop_consumer(digits)):
            return "opened"

    # Fallback: open WhatsApp Web (cross-platform)
    QMessageBox.information(
        parent,
        _TR("WhatsApp"),
        _TR("WhatsApp Desktop is not available. Opening WhatsApp Web instead."),
    )
    QDesktopServices.openUrl(_qurl_web_consumer(digits))
    return "web"


def open_whatsapp_with_template(
    parent: QWidget, phone: str, template_name: str, context: TemplateContext
) -> str:
    """
    Open WhatsApp chat with a pre-filled message from a template.

    Args:
        parent: Parent widget for dialogs
        phone: Phone number
        template_name: Name of the template to use
        context: Dictionary with placeholder values

    Returns:
        "opened", "web", or "invalid"
    """
    from app.services.wa_templates_repository import get_template_by_name, render_template

    digits = to_wa_digits(phone, default_cc=DEFAULT_COUNTRY_CODE)
    if not digits:
        QMessageBox.warning(
            parent,
            _TR("WhatsApp"),
            _TR("This record has no valid phone number."),
        )
        return "invalid"

    # Get and render template
    tpl = get_template_by_name(template_name)
    if not tpl:
        QMessageBox.warning(
            parent,
            _TR("WhatsApp"),
            _TR("Template '{name}' not found.").format(name=template_name),
        )
        return "invalid"

    render_context: dict[str, str] = {k: str(v) for k, v in context.items() if v is not None}
    message = render_template(str(tpl["template"]), render_context)
    encoded_message = quote(message)

    # Try desktop protocol with message
    if _is_whatsapp_consumer_registered():
        url = QUrl(f"whatsapp://send?phone={digits}&text={encoded_message}")
        if QDesktopServices.openUrl(url):
            return "opened"

    # Fallback to web with message
    web_url = QUrl(f"https://wa.me/{digits}?text={encoded_message}")
    QDesktopServices.openUrl(web_url)
    return "web"


def open_whatsapp_with_message(parent: QWidget, phone: str, message: str) -> str:
    """
    Open WhatsApp chat with a custom message (not from template).

    Args:
        parent: Parent widget for dialogs
        phone: Phone number
        message: The message text to pre-fill

    Returns:
        "opened", "web", or "invalid"
    """
    digits = to_wa_digits(phone, default_cc=DEFAULT_COUNTRY_CODE)
    if not digits:
        QMessageBox.warning(
            parent,
            _TR("WhatsApp"),
            _TR("This record has no valid phone number."),
        )
        return "invalid"

    encoded_message = quote(message)

    # Try desktop protocol with message
    if _is_whatsapp_consumer_registered():
        url = QUrl(f"whatsapp://send?phone={digits}&text={encoded_message}")
        if QDesktopServices.openUrl(url):
            return "opened"

    # Fallback to web with message
    web_url = QUrl(f"https://wa.me/{digits}?text={encoded_message}")
    QDesktopServices.openUrl(web_url)
    return "web"
