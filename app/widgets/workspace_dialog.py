from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from PySide6.QtCore import QSettings, Qt
from PySide6.QtWidgets import QDialog, QWidget

from app.constants import APP, ORG


@dataclass(frozen=True)
class WorkspaceDialogSpec:
    settings_key: str
    default_width: int
    default_height: int
    min_width: int
    min_height: int
    allow_maximize: bool = True


@dataclass(frozen=True)
class DialogSurfaceSpec:
    settings_key: str | None
    default_width: int
    default_height: int
    min_width: int
    min_height: int
    allow_maximize: bool = False
    persist_geometry: bool = False
    density: Literal["dialog", "workspace"] = "dialog"


def workspace_margins() -> tuple[int, int, int, int]:
    return (16, 16, 16, 16)


def workspace_spacing() -> int:
    return 10


def apply_workspace_dialog(
    dialog: QDialog,
    spec: WorkspaceDialogSpec,
    *,
    role: str = "workspaceDialog",
    density: str = "workspace",
) -> None:
    apply_dialog_surface(
        dialog,
        DialogSurfaceSpec(
            settings_key=spec.settings_key,
            default_width=spec.default_width,
            default_height=spec.default_height,
            min_width=spec.min_width,
            min_height=spec.min_height,
            allow_maximize=spec.allow_maximize,
            persist_geometry=True,
            density="workspace",
        ),
        role=role,
        density=density,
    )


def apply_dialog_surface(
    dialog: QDialog,
    spec: DialogSurfaceSpec,
    *,
    role: str | None = None,
    density: str | None = None,
) -> None:
    resolved_density = density or spec.density
    resolved_role = role or ("workspaceDialog" if resolved_density == "workspace" else "dialog")
    dialog.setProperty("immoRole", resolved_role)
    dialog.setProperty("immoDensity", resolved_density)
    dialog.setMinimumSize(spec.min_width, spec.min_height)
    dialog.setWindowFlag(Qt.WindowType.WindowMaximizeButtonHint, spec.allow_maximize)
    dialog.setWindowFlag(Qt.WindowType.WindowMinimizeButtonHint, spec.allow_maximize)
    if spec.persist_geometry and spec.settings_key:
        _restore_dialog_geometry(dialog, spec)
        dialog.finished.connect(lambda _result: _save_dialog_geometry(dialog, spec))
        return
    dialog.resize(spec.default_width, spec.default_height)


def apply_workspace_widget(widget: QWidget) -> None:
    widget.setProperty("immoRole", "workspaceDialog")
    widget.setProperty("immoDensity", "workspace")


def _restore_dialog_geometry(dialog: QDialog, spec: DialogSurfaceSpec) -> None:
    settings = QSettings(ORG, APP)
    raw = settings.value(f"{spec.settings_key}/geometry")
    if isinstance(raw, (bytes, bytearray)) and raw:
        try:
            if dialog.restoreGeometry(bytes(raw)):
                return
        except Exception:
            pass
    dialog.resize(spec.default_width, spec.default_height)


def _save_dialog_geometry(dialog: QDialog, spec: DialogSurfaceSpec) -> None:
    settings = QSettings(ORG, APP)
    settings.setValue(f"{spec.settings_key}/geometry", dialog.saveGeometry())


__all__ = [
    "DialogSurfaceSpec",
    "apply_dialog_surface",
    "WorkspaceDialogSpec",
    "apply_workspace_dialog",
    "apply_workspace_widget",
    "workspace_margins",
    "workspace_spacing",
]
