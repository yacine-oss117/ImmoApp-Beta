"""Stylesheet and small widget helpers for the Hub Manager app."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QFrame, QLabel, QPushButton, QVBoxLayout

HUB_MANAGER_STYLESHEET = """
QWidget#hub-manager-root {
    background: #f5f1e8;
    color: #18212f;
}
QWidget#hub-manager-root QLabel {
    color: #18212f;
}
QFrame#hub-hero {
    background: qlineargradient(x1:0, y1:0, x2:1, y2:1, stop:0 #123a49, stop:0.56 #174e5e, stop:1 #1d756c);
    border-radius: 22px;
}
QFrame#hub-hero QLabel {
    color: #ffffff;
}
QLabel#hub-hero-title {
    color: #ffffff;
    font-size: 26px;
    font-weight: 800;
}
QLabel#hub-hero-subtitle {
    color: #d7ebe8;
    font-size: 14px;
}
QLabel#hub-status-badge {
    background: #f2b84b;
    color: #2b2006;
    border-radius: 15px;
    padding: 8px 14px;
    font-weight: 700;
}
QFrame#hub-card, QFrame#hub-action-card, QFrame#hub-dashboard-card {
    background: #fffdf8;
    border: 1px solid #ded7c9;
    border-radius: 18px;
}
QLabel#hub-card-title {
    color: #123a49;
    font-size: 14px;
    font-weight: 800;
}
QLabel#hub-field-label {
    color: #5d6470;
    font-weight: 700;
}
QPushButton#hub-primary-action {
    background: #1d756c;
    color: #ffffff;
    border: 2px solid #1d756c;
    border-radius: 14px;
    padding: 13px 20px;
    font-weight: 700;
}
QPushButton#hub-primary-action:hover {
    background: #23877d;
    border-color: #8edbd0;
}
QPushButton#hub-primary-action:pressed {
    background: #13534d;
    padding-top: 15px;
    padding-bottom: 11px;
}
QPushButton#hub-secondary-action {
    background: #e6f0ee;
    color: #153f4f;
    border: 2px solid #c2ddd8;
    border-radius: 14px;
    padding: 13px 20px;
    font-weight: 700;
}
QPushButton#hub-secondary-action:hover {
    background: #f4fbf9;
    border-color: #8ebbb3;
}
QPushButton#hub-secondary-action:pressed {
    background: #d1e4e0;
    padding-top: 15px;
    padding-bottom: 11px;
}
QGroupBox {
    background: #fffdf8;
    color: #18212f;
    border: 1px solid #ded7c9;
    border-radius: 14px;
    margin-top: 14px;
    padding: 12px;
    font-weight: 700;
}
QGroupBox::title {
    subcontrol-origin: margin;
    left: 14px;
    padding: 0 6px;
    background: #fffdf8;
    color: #153f4f;
}
QPushButton {
    background: #ffffff;
    color: #153f4f;
    border: 2px solid #d5cdc0;
    border-radius: 12px;
    padding: 11px 14px;
    font-weight: 650;
}
QPushButton:hover {
    background: #f0f7f5;
    border-color: #8ebbb3;
}
QPushButton:pressed {
    background: #e0efec;
    border-color: #1d756c;
    padding-top: 13px;
    padding-bottom: 9px;
}
QPushButton:focus {
    border-color: #f2b84b;
}
QPushButton:disabled {
    background: #ece7dc;
    color: #8c897f;
    border-color: #ded7c9;
}
QPlainTextEdit {
    background: #101820;
    color: #d9f2ec;
    border-radius: 10px;
    padding: 8px;
}
QScrollArea {
    background: transparent;
    border: 0;
}
QWidget#hub-action-panel {
    background: transparent;
}
"""


def configure_button(button: QPushButton, *, min_height: int = 52) -> QPushButton:
    button.setCursor(Qt.CursorShape.PointingHandCursor)
    button.setMinimumHeight(min_height)
    return button


def section_title(text: str) -> QLabel:
    label = QLabel(text)
    label.setObjectName("hub-card-title")
    return label


def field_label(text: str) -> QLabel:
    label = QLabel(text)
    label.setObjectName("hub-field-label")
    return label


def card(title: str, *, object_name: str = "hub-card") -> tuple[QFrame, QVBoxLayout]:
    frame = QFrame()
    frame.setObjectName(object_name)
    layout = QVBoxLayout(frame)
    layout.setContentsMargins(22, 18, 22, 20)
    layout.setSpacing(12)
    layout.addWidget(section_title(title))
    return frame, layout
