"""Compile global QSS from semantic theme tokens."""

from __future__ import annotations

from app.ui.theme_tokens import get_theme_tokens


def build_stylesheet(theme_name: str | None = None, density_name: str | None = None) -> str:
    """Build the full stylesheet for the current theme."""
    t = get_theme_tokens(theme_name)
    density = (density_name or "compact").strip().lower()
    compact = density == "compact"
    control_min_h = 30 if compact else 34
    table_row_h = 28 if compact else 32
    button_pad_v = 4 if compact else 6
    button_pad_h = 10 if compact else 12
    section_pad_v = 6 if compact else 8
    font_size = "12px" if compact else "13px"
    control_sm_h = max(24, control_min_h - 4)
    control_md_h = control_min_h
    control_lg_h = control_min_h + 4
    return f"""
QWidget {{
    background: {t["BG"]};
    color: {t["TEXT"]};
    font-size: {font_size};
    outline: none;
}}

QWidget[immoDensity="workspace"] {{
    font-size: {font_size};
}}

QMainWindow {{
    background: {t["BG"]};
}}

QMenuBar {{
    background: {t["MENU_BG"]};
    color: {t["TEXT"]};
    border-bottom: 1px solid {t["BORDER"]};
    padding: 4px 8px;
}}

QMenuBar::item {{
    background: transparent;
    padding: 6px 12px;
    border-radius: 8px;
}}

QMenuBar::item:selected {{
    background: {t["GHOST_HOVER"]};
}}

QMenu {{
    background: {t["MENU_BG"]};
    color: {t["TEXT"]};
    border: 1px solid {t["BORDER"]};
    padding: 6px;
}}

QMenu::item {{
    padding: 6px 14px;
    border-radius: 6px;
}}

QMenu::item:selected {{
    background: {t["GHOST_HOVER"]};
}}

QMenu[immoMenuRole="context"] {{
    border-radius: 8px;
    padding: 4px;
}}

QMenu[immoMenuRole="context"]::item {{
    padding: 8px 20px;
    border-radius: 6px;
}}

QStatusBar {{
    background: {t["MENU_BG"]};
    color: {t["TEXT_MUTED"]};
    border-top: 1px solid {t["BORDER"]};
}}

QTabWidget::pane {{
    border-top: 1px solid {t["BORDER"]};
}}

QTabBar::tab {{
    background: transparent;
    color: {t["TEXT_MUTED"]};
    padding: 10px 16px;
    margin-right: 2px;
    border-bottom: 2px solid transparent;
}}

QTabBar::tab:selected {{
    color: {t["TEXT"]};
    border-bottom: 2px solid {t["PRIMARY"]};
}}

QTabBar::tab:hover:!selected {{
    color: {t["TEXT"]};
}}

QPushButton {{
    background: {t["SURFACE_SOFT"]};
    color: {t["TEXT"]};
    border: 1px solid {t["BORDER"]};
    border-radius: 8px;
    padding: {button_pad_v}px {button_pad_h}px;
    min-height: {control_md_h}px;
    font-weight: 600;
}}

QPushButton[immoSize="sm"] {{
    min-height: {control_sm_h}px;
    padding: {max(2, button_pad_v - 1)}px {max(8, button_pad_h - 2)}px;
}}

QPushButton[immoSize="md"] {{
    min-height: {control_md_h}px;
}}

QPushButton[immoSize="lg"] {{
    min-height: {control_lg_h}px;
    padding: {button_pad_v + 1}px {button_pad_h + 2}px;
}}

QPushButton:hover {{
    background: {t["GHOST_HOVER"]};
}}

QPushButton:pressed {{
    background: {t["SURFACE_ALT"]};
}}

QPushButton:disabled {{
    color: {t["TEXT_DIM"]};
    background: {t["SURFACE_ALT"]};
}}

QPushButton[immoVariant="primary"] {{
    background: {t["PRIMARY"]};
    color: #ffffff;
    border: none;
}}

QPushButton[immoVariant="primary"]:hover {{
    background: {t["PRIMARY_HOVER"]};
}}

QPushButton[immoVariant="primary"]:pressed {{
    background: {t["PRIMARY_ACTIVE"]};
}}

QPushButton[immoVariant="secondary"] {{
    background: {t["SURFACE_SOFT"]};
    color: {t["TEXT"]};
    border: 1px solid {t["BORDER"]};
}}

QPushButton[immoVariant="secondary"]:hover {{
    background: {t["GHOST_HOVER"]};
}}

QPushButton[immoVariant="secondary"]:pressed {{
    background: {t["SURFACE_ALT"]};
}}

QPushButton[immoVariant="ghost"] {{
    background: transparent;
    color: {t["TEXT"]};
    border: 1px solid {t["BORDER"]};
}}

QPushButton[immoVariant="ghost"]:hover {{
    background: {t["GHOST_HOVER"]};
}}

QPushButton[immoVariant="success"] {{
    background: {t["SUCCESS"]};
    color: #ffffff;
    border: none;
}}

QPushButton[immoVariant="warning"] {{
    background: {t["WARNING"]};
    color: #ffffff;
    border: none;
}}

QPushButton[immoVariant="danger"] {{
    background: {t["DANGER"]};
    color: #ffffff;
    border: none;
}}

QLineEdit, QComboBox, QSpinBox, QDoubleSpinBox, QDateEdit, QDateTimeEdit, QTimeEdit {{
    background: {t["INPUT_BG"]};
    color: {t["TEXT"]};
    border: 1px solid {t["BORDER"]};
    border-radius: 8px;
    padding: {button_pad_v}px 10px;
    min-height: {control_md_h}px;
}}

QLineEdit[immoSize="sm"], QComboBox[immoSize="sm"], QSpinBox[immoSize="sm"], QDoubleSpinBox[immoSize="sm"], QDateEdit[immoSize="sm"], QDateTimeEdit[immoSize="sm"], QTimeEdit[immoSize="sm"] {{
    min-height: {control_sm_h}px;
    padding-top: {max(2, button_pad_v - 1)}px;
    padding-bottom: {max(2, button_pad_v - 1)}px;
}}

QLineEdit[immoSize="md"], QComboBox[immoSize="md"], QSpinBox[immoSize="md"], QDoubleSpinBox[immoSize="md"], QDateEdit[immoSize="md"], QDateTimeEdit[immoSize="md"], QTimeEdit[immoSize="md"] {{
    min-height: {control_md_h}px;
}}

QLineEdit[immoSize="lg"], QComboBox[immoSize="lg"], QSpinBox[immoSize="lg"], QDoubleSpinBox[immoSize="lg"], QDateEdit[immoSize="lg"], QDateTimeEdit[immoSize="lg"], QTimeEdit[immoSize="lg"] {{
    min-height: {control_lg_h}px;
}}

QLineEdit:focus, QComboBox:focus, QSpinBox:focus, QDoubleSpinBox:focus, QDateEdit:focus, QDateTimeEdit:focus, QTimeEdit:focus {{
    border: 1px solid {t["FOCUS"]};
}}

QLineEdit[immoState="error"], QComboBox[immoState="error"], QSpinBox[immoState="error"], QDoubleSpinBox[immoState="error"], QDateEdit[immoState="error"], QDateTimeEdit[immoState="error"], QTimeEdit[immoState="error"] {{
    border: 1px solid {t["DANGER"]};
}}

QLineEdit[immoState="success"], QComboBox[immoState="success"], QSpinBox[immoState="success"], QDoubleSpinBox[immoState="success"], QDateEdit[immoState="success"], QDateTimeEdit[immoState="success"], QTimeEdit[immoState="success"] {{
    border: 1px solid {t["SUCCESS"]};
}}

QLineEdit::placeholder {{
    color: {t["TEXT_DIM"]};
}}

QComboBox::drop-down {{
    border: none;
    width: 22px;
}}

QComboBox::down-arrow {{
    image: none;
    border-left: 4px solid transparent;
    border-right: 4px solid transparent;
    border-top: 5px solid {t["TEXT_MUTED"]};
    margin-right: 8px;
}}

QCheckBox {{
    spacing: 8px;
    color: {t["TEXT"]};
}}

QCheckBox::indicator {{
    width: 18px;
    height: 18px;
    border: 1px solid {t["BORDER"]};
    border-radius: 4px;
    background: {t["INPUT_BG"]};
}}

QCheckBox::indicator:checked {{
    background: {t["PRIMARY"]};
    border-color: {t["PRIMARY"]};
}}

QLabel {{
    color: {t["TEXT"]};
    background: transparent;
}}

QLabel[immoState="muted"] {{
    color: {t["TEXT_MUTED"]};
}}

QLabel[immoState="loading"] {{
    color: {t["INFO"]};
}}

QLabel[immoState="error"] {{
    color: {t["DANGER"]};
}}

QLabel[immoState="success"] {{
    color: {t["SUCCESS"]};
}}

QFormLayout > QLabel {{
    color: {t["TEXT_MUTED"]};
    font-weight: 600;
}}

QFrame[immoCard="true"] {{
    background: {t["CARD"]};
    border: 1px solid {t["BORDER"]};
    border-radius: 12px;
}}

QDialog[immoRole="workspaceDialog"],
QWidget[immoRole="workspaceDialog"] {{
    background: {t["BG"]};
}}

QFrame[immoRole="workspaceToolbar"] {{
    background: transparent;
    border: none;
}}

QFrame[immoRole="workspaceEditor"] {{
    background: {t["SURFACE"]};
    border: 1px solid {t["BORDER"]};
    border-radius: 10px;
}}

QFrame[immoRole="contractArticle"] {{
    margin: 4px 0;
}}

QFrame[immoRole="crmFilters"],
QFrame[immoRole="crmTable"],
QFrame[immoRole="matchControls"],
QFrame[immoRole="matchResults"] {{
    border-radius: 12px;
}}

QLabel[immoMuted="true"] {{
    color: {t["TEXT_MUTED"]};
}}

QLabel[immoEmptyState="true"] {{
    color: {t["TEXT_MUTED"]};
    font-style: italic;
    padding: 10px;
}}

QFrame#immoFormSection {{
    background: {t["SURFACE"]};
    border: 1px solid {t["BORDER"]};
    border-radius: 10px;
    margin-top: 10px;
}}

QLabel#immoFormSectionTitle {{
    color: {t["TEXT_MUTED"]};
    font-weight: 700;
    padding: 0 8px;
    margin-left: 8px;
    margin-top: -6px;
    background: {t["SURFACE"]};
}}

QLabel#dashboardTitle {{
    font-size: 24px;
    font-weight: 700;
    color: {t["TEXT"]};
}}

QLabel#dashboardSectionTitle {{
    color: {t["TEXT_MUTED"]};
    font-size: 14px;
    font-weight: 700;
    padding: 2px 0;
}}

QLabel#dialogSectionTitle {{
    color: {t["TEXT"]};
    font-size: 18px;
    font-weight: 700;
}}

QLabel#dashboardStatTitle {{
    color: {t["TEXT_MUTED"]};
    font-size: 13px;
    font-weight: 600;
}}

QLabel#dashboardStatValue {{
    color: {t["TEXT"]};
    font-size: 28px;
    font-weight: 800;
}}

QLabel#dashboardNotice {{
    background: {t["SURFACE_SOFT"]};
    border: 1px solid {t["BORDER"]};
    border-left: 3px solid {t["WARNING"]};
    border-radius: 10px;
    color: {t["TEXT"]};
    padding: 10px 12px;
}}

QFrame[cardRole="visit"] {{
    border-left: 4px solid {t["PRIMARY"]};
}}

QFrame[cardRole="pending"] {{
    border-left: 4px solid {t["WARNING"]};
}}

QFrame[cardRole="contract"] {{
    border-left: 4px solid {t["WARNING"]};
}}

QFrame[cardRole="lead"] {{
    border: 2px solid {t["SUCCESS"]};
}}

QLabel[leadTitle="true"] {{
    color: {t["TEXT"]};
    font-weight: 700;
    font-size: 16px;
}}

QLabel[leadBadge="true"] {{
    color: #ffffff;
    background: {t["SUCCESS"]};
    border-radius: 10px;
    padding: 4px 10px;
    font-weight: 700;
    font-size: 12px;
}}

QPushButton[matchCellRole="phone"] {{
    color: {t["SUCCESS"]};
    background: transparent;
    border: none;
    text-align: left;
    font-size: 13px;
}}

QPushButton[matchCellRole="phone"]:hover {{
    text-decoration: underline;
}}

QPushButton[matchCellRole="position"] {{
    color: {t["INFO"]};
    background: transparent;
    border: 1px solid {t["BORDER"]};
    border-radius: 6px;
    min-height: 28px;
    padding: 4px 8px;
    font-size: 12px;
}}

QPushButton[matchCellRole="position"]:hover {{
    background: {t["GHOST_HOVER"]};
}}

QWidget[matchActionsContainer="true"] {{
    background: transparent;
    border: none;
}}

QPushButton[matchAction="visit"] {{
    min-height: 28px;
    padding: 4px 10px;
}}

QPushButton[matchAction="contract"] {{
    min-height: 28px;
    padding: 4px 10px;
}}

QLabel#matchResultsHeader {{
    font-size: 14px;
    padding: 10px 14px;
    background: {t["SURFACE_SOFT"]};
    color: {t["TEXT"]};
    border-radius: 8px;
    border: 1px solid {t["BORDER"]};
    border-left: 3px solid {t["PRIMARY"]};
}}

QLabel#matchProgressLabel {{
    color: {t["TEXT_MUTED"]};
    font-size: 14px;
    font-weight: 600;
}}

QLabel#matchProgressLabel[immoState="error"] {{
    color: {t["DANGER"]};
}}

QLabel#matchProgressLabel[immoState="success"] {{
    color: {t["SUCCESS"]};
}}

QLabel[matchNoResults="true"] {{
    color: {t["TEXT_MUTED"]};
    padding: 20px;
    font-style: italic;
}}

QLabel#matchPlaceholder {{
    color: {t["TEXT_MUTED"]};
    font-size: 14px;
    min-height: 110px;
}}

QLabel#statusTimeLabel {{
    font-weight: 700;
}}

QLabel#statusTimeLabel[statusState="ok"] {{
    color: {t["SUCCESS"]};
}}

QLabel#statusTimeLabel[statusState="green"] {{
    color: {t["SUCCESS"]};
}}

QLabel#statusTimeLabel[statusState="orange"] {{
    color: {t["WARNING"]};
}}

QLabel#statusTimeLabel[statusState="red"] {{
    color: {t["DANGER"]};
}}

QLabel#statusTimeLabel[statusState="error"] {{
    color: {t["DANGER"]};
}}

QLabel#statusTimeLabel[statusState="offline"] {{
    color: {t["TEXT_DIM"]};
}}

QLabel#statusNetworkLabel {{
    font-weight: 600;
}}

QLabel#statusNetworkLabel[statusState="ok"] {{
    color: {t["SUCCESS"]};
}}

QLabel#statusNetworkLabel[statusState="orange"] {{
    color: {t["WARNING"]};
}}

QLabel#statusNetworkLabel[statusState="red"] {{
    color: {t["DANGER"]};
}}

QLabel#statusNetworkLabel[statusState="error"] {{
    color: {t["DANGER"]};
}}

QLabel#statusNetworkLabel[statusState="offline"] {{
    color: {t["TEXT_DIM"]};
}}

QFrame#clientsRequestsCard {{
    background: {t["SURFACE"]};
    border: 1px solid {t["BORDER"]};
    border-radius: 10px;
}}

QLabel#clientsRequestsTitle {{
    color: {t["TEXT"]};
    font-weight: 700;
    font-size: 13px;
}}

QFrame#demandeSummaryCard {{
    background: {t["SURFACE_ALT"]};
    border: 1px solid {t["BORDER"]};
    border-left: 3px solid {t["PRIMARY"]};
    border-radius: 9px;
}}

QFrame#demandeSummaryCard:hover {{
    background: {t["SURFACE_SOFT"]};
}}

QLabel#demandeSummaryTitle {{
    color: {t["TEXT"]};
    font-weight: 700;
    font-size: 13px;
}}

QLabel#demandeSummaryPrimary {{
    color: {t["TEXT"]};
    font-weight: 600;
}}

QLabel#demandeSummarySecondary,
QLabel#demandeSummaryNotes {{
    color: {t["TEXT_MUTED"]};
    font-size: 12px;
}}

QLabel[immoDialogTitle="true"] {{
    color: {t["TEXT"]};
    font-size: 16px;
    font-weight: 700;
    padding: 2px 0 4px 2px;
}}

QDialog#immoDialog,
QDialog#contractDialog,
QDialog#contractEditDialog {{
    background: {t["CARD"]};
    border: 1px solid {t["BORDER"]};
    border-radius: 12px;
}}

QGroupBox[immoRole="dialogPanel"] {{
    border-radius: 12px;
}}

QLabel#agencyAssetPreview {{
    background: {t["SURFACE_ALT"]};
    border: 2px dashed {t["BORDER"]};
    border-radius: 10px;
    color: {t["TEXT_MUTED"]};
}}

QLabel#waTemplatePreview {{
    background: {t["SURFACE_ALT"]};
    border: 1px solid {t["BORDER"]};
    border-radius: 8px;
    color: {t["TEXT"]};
    padding: 10px;
}}

QLabel#simulationStatusBanner {{
    background: {t["SURFACE_ALT"]};
    border: 1px solid {t["BORDER"]};
    border-radius: 8px;
    padding: 8px;
    font-weight: 600;
}}

QLabel#simulationStatusBanner[immoState="success"] {{
    border-color: {t["SUCCESS"]};
}}

QLabel#simulationStatusBanner[immoState="error"] {{
    border-color: {t["DANGER"]};
}}

QLabel#agencySettingsNote,
QLabel#simulationDialogNote {{
    font-size: 11px;
}}

QScrollArea[immoRole="articleScroll"],
QScrollArea[immoRole="editorScroll"] {{
    border: none;
    background: transparent;
}}

QPushButton[immoRole="tinyAction"] {{
    min-width: 24px;
    min-height: 24px;
    max-width: 24px;
    max-height: 24px;
    border-radius: 12px;
    padding: 0;
    font-size: 12px;
}}

QLineEdit[articleRole="title"] {{
    font-weight: 700;
}}

QLineEdit[articleRole="title"][articleRequired="true"],
QTextEdit[articleRequired="true"] {{
    background: {t["SURFACE_SOFT"]};
    border-color: {t["BORDER"]};
}}

QLabel[articleRole="requiredFlag"] {{
    color: {t["WARNING"]};
    font-weight: 700;
}}

QDialog#immoImportDialog {{
    background: {t["BG"]};
}}

QWidget#WizardContent {{
    background: {t["CARD"]};
    border: 1px solid {t["BORDER"]};
    border-radius: 12px;
}}

QLabel#StepTitle {{
    color: {t["TEXT"]};
    font-size: 18px;
    font-weight: 700;
}}

QLabel#StepDescription {{
    color: {t["TEXT_MUTED"]};
    font-size: 13px;
}}

QProgressBar#importExecutionProgress {{
    border: 1px solid {t["BORDER"]};
    border-radius: 6px;
    background: {t["SURFACE_ALT"]};
    min-height: 12px;
}}

QProgressBar#importExecutionProgress::chunk {{
    background: {t["PRIMARY"]};
    border-radius: 5px;
}}

QProgressBar#importExecutionProgress[immoState="error"]::chunk {{
    background: {t["DANGER"]};
}}

QFrame#InfoBox {{
    background: {t["IMPORT_INFO_BG"]};
    border: 1px solid {t["IMPORT_INFO_BORDER"]};
    border-radius: 8px;
}}

QFrame#InfoBox QLabel {{
    color: {t["IMPORT_INFO_BORDER"]};
}}

QFrame#DropZone {{
    border: 2px dashed {t["BORDER"]};
    border-radius: 16px;
    background: {t["SURFACE_SOFT"]};
}}

QFrame#DropZone:hover {{
    border-color: {t["PRIMARY"]};
    background: {t["GHOST_HOVER"]};
}}

QLabel#DropIcon {{
    color: {t["PRIMARY"]};
    font-size: 48px;
}}

QLabel#DropText {{
    color: {t["TEXT_MUTED"]};
    font-size: 16px;
}}

QFrame#StatCard {{
    background: {t["SURFACE_ALT"]};
    border: 1px solid {t["BORDER"]};
    border-radius: 12px;
    min-width: 140px;
}}

QFrame#StatCard[immoState="success"] {{
    border-left: 4px solid {t["SUCCESS"]};
}}

QFrame#StatCard[immoState="info"] {{
    border-left: 4px solid {t["INFO"]};
}}

QFrame#StatCard[immoState="error"] {{
    border-left: 4px solid {t["DANGER"]};
}}

QFrame#StatCard[immoState="muted"] {{
    border-left: 4px solid {t["TEXT_DIM"]};
}}

QLabel#StatValue {{
    font-size: 30px;
    font-weight: 800;
}}

QLabel#StatValue[immoState="success"] {{
    color: {t["SUCCESS"]};
}}

QLabel#StatValue[immoState="info"] {{
    color: {t["INFO"]};
}}

QLabel#StatValue[immoState="error"] {{
    color: {t["DANGER"]};
}}

QLabel#StatValue[immoState="muted"] {{
    color: {t["TEXT_DIM"]};
}}

QLabel#StatLabel {{
    font-size: 12px;
    color: {t["TEXT_MUTED"]};
}}

QDialog#immoLoginDialog {{
    background: {t["BG"]};
}}

QFrame#immoLoginBrand {{
    background: {t["SURFACE_SOFT"]};
    border-right: 1px solid {t["BORDER"]};
}}

QLabel#immoLoginTitle {{
    color: {t["TEXT"]};
    font-size: 34px;
    font-weight: 800;
}}

QLabel#immoLoginTagline {{
    color: {t["TEXT_MUTED"]};
    font-size: 15px;
    line-height: 1.25;
}}

QLabel#immoLoginBadge {{
    background: {t["SURFACE_ALT"]};
    color: {t["TEXT"]};
    border: 1px solid {t["BORDER"]};
    border-radius: 10px;
    padding: 6px 10px;
    font-size: 11px;
    font-weight: 700;
}}

QLabel#immoLoginFooter {{
    color: {t["TEXT_DIM"]};
    font-size: 11px;
}}

QFrame#immoLoginForm {{
    background: {t["CARD"]};
}}

QLabel#immoLoginHeading {{
    color: {t["TEXT"]};
    font-size: 30px;
    font-weight: 800;
}}

QLabel#immoLoginHint {{
    color: {t["TEXT_MUTED"]};
    font-size: 14px;
}}

QLabel#immoLoginResumeBadge {{
    background: {t["PRIMARY"]};
    color: #ffffff;
    border-radius: 10px;
    padding: 4px 10px;
    font-size: 11px;
    font-weight: 700;
}}

QLabel#immoLoginStatus {{
    color: {t["WARNING"]};
    font-size: 13px;
    font-weight: 600;
}}

QFrame#collapsibleHeader {{
    background: {t["SURFACE_SOFT"]};
    border: 1px solid {t["BORDER"]};
    border-radius: 8px;
}}

QFrame#collapsibleHeader:hover {{
    background: {t["GHOST_HOVER"]};
}}

QLabel#collapsibleArrow {{
    color: {t["TEXT_MUTED"]};
    font-size: 10px;
}}

QLabel#collapsibleTitle {{
    color: {t["TEXT"]};
    font-weight: 700;
    font-size: 13px;
}}

QGroupBox {{
    background: {t["SURFACE"]};
    border: 1px solid {t["BORDER"]};
    border-radius: 10px;
    margin-top: 12px;
    padding-top: {section_pad_v}px;
}}

QGroupBox::title {{
    subcontrol-origin: margin;
    left: 12px;
    padding: 2px 8px;
    color: {t["TEXT_MUTED"]};
    background: {t["SURFACE"]};
    font-weight: 700;
}}

QTreeView, QTableWidget, QTableView {{
    background: {t["SURFACE"]};
    alternate-background-color: {t["TABLE_ALT"]};
    color: {t["TEXT"]};
    border: 1px solid {t["BORDER"]};
    border-radius: 8px;
    gridline-color: {t["BORDER"]};
    selection-background-color: {t["SELECTION"]};
}}

QTreeView[immoRole="workspaceTable"],
QTableWidget[immoRole="workspaceTable"],
QTableView[immoRole="workspaceTable"] {{
    border-radius: 10px;
}}

QTreeView::item, QTableWidget::item, QTableView::item {{
    min-height: {table_row_h}px;
    padding: 8px 6px;
}}

QHeaderView::section {{
    background: {t["HEADER_BG"]};
    color: {t["TEXT_MUTED"]};
    border: none;
    border-right: 1px solid {t["BORDER"]};
    border-bottom: 1px solid {t["BORDER"]};
    padding: 10px 8px;
    font-weight: 700;
}}

QScrollBar:vertical {{
    background: {t["SURFACE_ALT"]};
    width: 10px;
    margin: 0;
}}

QScrollBar::handle:vertical {{
    background: {t["BORDER"]};
    border-radius: 5px;
    min-height: 24px;
    margin: 1px;
}}

QScrollBar:horizontal {{
    background: {t["SURFACE_ALT"]};
    height: 10px;
    margin: 0;
}}

QScrollBar::handle:horizontal {{
    background: {t["BORDER"]};
    border-radius: 5px;
    min-width: 24px;
    margin: 1px;
}}

QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical,
QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {{
    width: 0;
    height: 0;
}}

/* Compact modern scrollbars used by the Clients dual-scroll workspace and request dialogs.
   They stay visible and fully draggable/clickable while occupying very little space. */
QScrollBar[immoScrollRole="compact"]:vertical {{
    background: transparent;
    width: 8px;
    margin: 2px 1px;
}}

QScrollBar[immoScrollRole="compact"]::handle:vertical {{
    background: {t["TEXT_DIM"]};
    border-radius: 4px;
    min-height: 34px;
    margin: 1px;
}}

QScrollBar[immoScrollRole="compact"]::handle:vertical:hover {{
    background: {t["TEXT_MUTED"]};
}}

QScrollBar[immoScrollRole="compact"]::handle:vertical:pressed {{
    background: {t["PRIMARY"]};
}}

QScrollBar[immoScrollRole="compact"]::add-page:vertical,
QScrollBar[immoScrollRole="compact"]::sub-page:vertical {{
    background: transparent;
}}

QScrollBar[immoScrollRole="compact"]:horizontal {{
    background: transparent;
    height: 8px;
    margin: 1px 2px;
}}

QScrollBar[immoScrollRole="compact"]::handle:horizontal {{
    background: {t["TEXT_DIM"]};
    border-radius: 4px;
    min-width: 34px;
    margin: 1px;
}}

QScrollBar[immoScrollRole="compact"]::handle:horizontal:hover {{
    background: {t["TEXT_MUTED"]};
}}

QScrollBar[immoScrollRole="compact"]::handle:horizontal:pressed {{
    background: {t["PRIMARY"]};
}}

QScrollBar[immoScrollRole="compact"]::add-page:horizontal,
QScrollBar[immoScrollRole="compact"]::sub-page:horizontal {{
    background: transparent;
}}

QScrollBar[immoScrollRole="compact"]::add-line:vertical,
QScrollBar[immoScrollRole="compact"]::sub-line:vertical,
QScrollBar[immoScrollRole="compact"]::add-line:horizontal,
QScrollBar[immoScrollRole="compact"]::sub-line:horizontal {{
    width: 0;
    height: 0;
}}

QToolTip {{
    background: {t["SURFACE_ALT"]};
    color: {t["TEXT"]};
    border: 1px solid {t["BORDER"]};
    border-radius: 6px;
    padding: 6px 8px;
}}

QFrame#NotificationToast_info,
QFrame#NotificationToast_success,
QFrame#NotificationToast_warning,
QFrame#NotificationToast_error {{
    background: {t["SURFACE"]};
    border: 1px solid {t["BORDER"]};
    border-radius: 10px;
}}

QFrame#NotificationToast_info {{
    border-left: 4px solid #2196F3;
}}

QFrame#NotificationToast_success {{
    border-left: 4px solid #4CAF50;
}}

QFrame#NotificationToast_warning {{
    border-left: 4px solid #FF9800;
}}

QFrame#NotificationToast_error {{
    border-left: 4px solid #F44336;
}}

QLabel#notificationToastTitle {{
    color: {t["TEXT"]};
    font-weight: 700;
    font-size: 14px;
}}

QLabel#notificationToastBody {{
    color: {t["TEXT_MUTED"]};
    font-size: 12px;
}}

QPushButton#notificationToastClose {{
    background: transparent;
    border: none;
    color: {t["TEXT_MUTED"]};
    font-size: 14px;
    min-height: 20px;
    min-width: 20px;
    max-width: 20px;
    max-height: 20px;
    padding: 0;
}}

QPushButton#notificationToastClose:hover {{
    color: {t["TEXT"]};
    background: {t["GHOST_HOVER"]};
    border-radius: 4px;
}}

QProgressBar#notificationToastProgress {{
    border: none;
    background: transparent;
    min-height: 2px;
    max-height: 2px;
}}

QProgressBar#notificationToastProgress::chunk {{
    border-radius: 1px;
}}

QFrame#NotificationToast_info QProgressBar#notificationToastProgress::chunk {{
    background: #2196F3;
}}

QFrame#NotificationToast_success QProgressBar#notificationToastProgress::chunk {{
    background: #4CAF50;
}}

QFrame#NotificationToast_warning QProgressBar#notificationToastProgress::chunk {{
    background: #FF9800;
}}

QFrame#NotificationToast_error QProgressBar#notificationToastProgress::chunk {{
    background: #F44336;
}}

QFrame#noticeBanner[immoState="success"] {{
    border-left: 4px solid {t["SUCCESS"]};
}}

QFrame#noticeBanner[immoState="warning"] {{
    border-left: 4px solid {t["WARNING"]};
}}

QFrame#noticeBanner[immoState="error"] {{
    border-left: 4px solid {t["DANGER"]};
}}

QDialog#NotificationsDialog {{
    background: {t["SURFACE"]};
}}

QFrame#NotificationCard {{
    background: {t["SURFACE"]};
    border: 1px solid {t["BORDER"]};
    border-radius: 8px;
}}

QFrame#NotificationCard_unread {{
    background: {t["SURFACE_SOFT"]};
    border: 1px solid {t["BORDER"]};
    border-left: 3px solid {t["PRIMARY"]};
    border-radius: 8px;
}}

QFrame#notificationCardAccent_info {{
    background: #2196F3;
    border: none;
}}

QFrame#notificationCardAccent_success {{
    background: #4CAF50;
    border: none;
}}

QFrame#notificationCardAccent_warning {{
    background: #FF9800;
    border: none;
}}

QFrame#notificationCardAccent_error {{
    background: #F44336;
    border: none;
}}

QLabel#notificationCardTitle {{
    color: {t["TEXT"]};
    font-weight: 700;
    font-size: 13px;
}}

QLabel#notificationCardBody {{
    color: {t["TEXT_MUTED"]};
    font-size: 12px;
}}

QLabel#notificationCardTime {{
    color: {t["TEXT_DIM"]};
    font-size: 11px;
}}

QLabel#notificationCardUnreadDot {{
    color: {t["PRIMARY"]};
    font-size: 12px;
    font-weight: 700;
}}

QLabel#notificationEmptyIcon {{
    color: {t["TEXT_DIM"]};
    font-size: 28px;
}}

QLabel#notificationEmptyText {{
    color: {t["TEXT_MUTED"]};
    font-size: 14px;
}}

QWidget#NotificationFilterBar QPushButton {{
    border-radius: 12px;
    padding: 4px 14px;
    border: 1px solid {t["BORDER"]};
    background: transparent;
    color: {t["TEXT_MUTED"]};
    min-height: 26px;
}}

QWidget#NotificationFilterBar QPushButton:checked {{
    background: {t["PRIMARY"]};
    border-color: {t["PRIMARY"]};
    color: #ffffff;
}}

QFrame#locationChip {{
    background: {t["SURFACE_SOFT"]};
    border: 1px solid {t["BORDER"]};
    border-radius: 12px;
}}

QFrame#locationChip QLabel {{
    color: {t["TEXT"]};
}}

QFrame#locationChip QToolButton {{
    border: none;
    background: transparent;
    color: {t["TEXT_MUTED"]};
    font-weight: 700;
    min-width: 18px;
}}

QFrame#locationChip QToolButton:hover {{
    color: {t["DANGER"]};
}}

QLabel#locationStatusLabel {{
    color: {t["TEXT_MUTED"]};
    padding-top: 2px;
    padding-left: 2px;
    font-size: 12px;
}}

QLabel#locationStatusLabel[immoState="loading"] {{
    color: {t["INFO"]};
}}

QLabel#locationStatusLabel[immoState="error"] {{
    color: {t["DANGER"]};
}}

QLabel#locationStatusLabel[immoState="success"] {{
    color: {t["SUCCESS"]};
}}

QDialog#immoStartupSplash {{
    background: {t["BG"]};
    border: 1px solid {t["BORDER"]};
    border-radius: 14px;
}}

QLabel#startupTitle {{
    color: {t["PRIMARY"]};
    font-size: 24px;
    font-weight: 800;
}}

QLabel#startupStatus {{
    color: {t["TEXT"]};
    font-size: 14px;
    font-weight: 600;
}}

QLabel#startupDetail {{
    color: {t["TEXT_MUTED"]};
    font-size: 12px;
}}

QProgressBar#startupProgress {{
    border: 1px solid {t["BORDER"]};
    border-radius: 8px;
    background: {t["SURFACE_ALT"]};
    height: 26px;
    text-align: center;
    color: {t["TEXT"]};
    font-weight: 700;
}}

QProgressBar#startupProgress::chunk {{
    background: {t["PRIMARY"]};
    border-radius: 7px;
}}
"""
