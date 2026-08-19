"""
BaseTableTab - Shared functionality for table-based tabs.

This module contains common code used by ClientsTab, ListingsTab, MatchTab, and CRM.
By inheriting from BaseTableTab, each tab avoids duplicating:
- Phone button click handling
- Table header sorting logic
- Location caching
- Table setup and styling

Also re-exports commonly used Qt widgets so child classes can import from here.
"""

from __future__ import annotations

from PySide6.QtCore import QDate, QDateTime, QSettings, Qt, QTime, QTimer, QUrl
from PySide6.QtGui import QClipboard, QColor, QDesktopServices, QFont
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QCompleter,
    QDateEdit,
    QDateTimeEdit,
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QFormLayout,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QSpinBox,
    QTableWidget,
    QTableWidgetItem,
    QTabWidget,
    QTextEdit,
    QTimeEdit,
    QVBoxLayout,
    QWidget,
)

from app.constants import APP, ORG
from app.utils.common import fmt_int_group, fmt_money_short, format_datetime, norm_text
from app.utils.wa import ensure_whatsapp_open_then_open_chat
from app.views.base_table import BaseTableTab
from app.views.searchable_combo import SearchableComboBox
from app.widgets.common import KeyItem, SelectiveSortHeader

__all__ = [
    "BaseTableTab",
    "SearchableComboBox",
    "Qt",
    "QSettings",
    "QTimer",
    "QUrl",
    "QDateTime",
    "QDate",
    "QTime",
    "QDesktopServices",
    "QColor",
    "QFont",
    "QClipboard",
    "QWidget",
    "QApplication",
    "QTableWidget",
    "QTableWidgetItem",
    "QHeaderView",
    "QVBoxLayout",
    "QHBoxLayout",
    "QFormLayout",
    "QGridLayout",
    "QPushButton",
    "QLabel",
    "QLineEdit",
    "QTextEdit",
    "QComboBox",
    "QSizePolicy",
    "QSpinBox",
    "QDoubleSpinBox",
    "QCheckBox",
    "QMessageBox",
    "QCompleter",
    "QTabWidget",
    "QScrollArea",
    "QFrame",
    "QDialog",
    "QDialogButtonBox",
    "QDateTimeEdit",
    "QDateEdit",
    "QTimeEdit",
    "KeyItem",
    "SelectiveSortHeader",
    "fmt_int_group",
    "fmt_money_short",
    "norm_text",
    "format_datetime",
    "ORG",
    "APP",
    "ensure_whatsapp_open_then_open_chat",
]
