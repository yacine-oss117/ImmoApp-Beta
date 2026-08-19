from __future__ import annotations

import re
import time
from pathlib import Path
from typing import Any, Callable

from pywinauto import Desktop, keyboard
from pywinauto.controls.uiawrapper import UIAWrapper


def _wrapper_identity(wrapper: UIAWrapper) -> tuple[int, str, str]:
    handle = int(getattr(wrapper, "handle", 0) or 0)
    info = getattr(wrapper, "element_info", None)
    automation_id = str(getattr(info, "automation_id", "") or "")
    control_type = str(getattr(info, "control_type", "") or "")
    return handle, automation_id, control_type


def _focus_for_input(target: UIAWrapper) -> None:
    try:
        top_level = target.top_level_parent()
    except Exception:
        top_level = None
    if isinstance(top_level, UIAWrapper):
        try:
            top_level.set_focus()
        except Exception:
            pass
    try:
        target.set_focus()
    except Exception:
        pass


def _send_keys_to(target: UIAWrapper, keys: str) -> None:
    _focus_for_input(target)
    try:
        target.type_keys(keys, set_foreground=True)
        return
    except Exception:
        pass
    keyboard.send_keys(keys)


def automation_id_matches(actual: object, expected: str | None) -> bool:
    if not expected:
        return True
    actual_text = str(actual or "")
    if actual_text == expected:
        return True
    if actual_text.endswith(f".{expected}"):
        return True
    last_segment = actual_text.rsplit(".", 1)[-1]
    return last_segment == expected


def automation_id_has_prefix(actual: object, prefix: str) -> bool:
    actual_text = str(actual or "")
    if actual_text.startswith(prefix):
        return True
    last_segment = actual_text.rsplit(".", 1)[-1]
    return last_segment.startswith(prefix)


def wait_for(
    description: str,
    predicate: Callable[[], Any],
    *,
    timeout: float = 20.0,
    interval: float = 0.2,
) -> Any:
    deadline = time.monotonic() + timeout
    last_error: Exception | None = None
    while time.monotonic() < deadline:
        try:
            value = predicate()
            if value:
                return value
        except Exception as exc:  # pragma: no cover - exercised in live runs
            last_error = exc
        time.sleep(interval)
    if last_error is not None:
        raise AssertionError(f"Timed out waiting for {description}") from last_error
    raise AssertionError(f"Timed out waiting for {description}")


def normalize_text(value: object) -> str:
    return re.sub(r"\s+", " ", str(value or "").strip())


def wrapper_texts(root: UIAWrapper) -> list[str]:
    texts: list[str] = []
    for wrapper in [root, *root.descendants()]:
        name = normalize_text(getattr(wrapper.element_info, "name", ""))
        if name:
            texts.append(name)
    return texts


def control_tree_as_text(root: UIAWrapper) -> str:
    lines: list[str] = []

    def _walk(node: UIAWrapper, depth: int) -> None:
        info = node.element_info
        control_type = str(getattr(info, "control_type", "") or "")
        auto_id = str(getattr(info, "automation_id", "") or "")
        name = str(getattr(info, "name", "") or "")
        indent = "  " * depth
        lines.append(f"{indent}{control_type or 'Control'} | auto_id={auto_id!r} | name={name!r}")
        for child_wrapper in node.children():
            _walk(child_wrapper, depth + 1)

    _walk(root, 0)
    return "\n".join(lines)


def child(
    root: UIAWrapper,
    *,
    auto_id: str | None = None,
    title: str | None = None,
    title_re: str | None = None,
    control_type: str | None = None,
    found_index: int = 0,
    timeout: float = 15.0,
    visible_only: bool = True,
) -> UIAWrapper:
    def _resolve() -> UIAWrapper | None:
        matches = matching_descendants(
            root,
            auto_id=auto_id,
            title=title,
            title_re=title_re,
            control_type=control_type,
            visible_only=visible_only,
        )
        if found_index >= len(matches):
            return None
        return matches[found_index]

    return wait_for(
        f"child control auto_id={auto_id!r} title={title!r} title_re={title_re!r}",
        _resolve,
        timeout=timeout,
    )


def descendant_with_auto_id_prefix(
    root: UIAWrapper,
    *,
    prefix: str,
    timeout: float = 15.0,
) -> UIAWrapper:
    def _resolve() -> UIAWrapper | None:
        for wrapper in [root, *root.descendants()]:
            automation_id = str(getattr(wrapper.element_info, "automation_id", "") or "")
            if automation_id_has_prefix(automation_id, prefix):
                return wrapper
        return None

    return wait_for(f"descendant with automation id prefix {prefix!r}", _resolve, timeout=timeout)


def matching_descendants(
    root: UIAWrapper,
    *,
    auto_id: str | None = None,
    title: str | None = None,
    title_re: str | None = None,
    control_type: str | None = None,
    visible_only: bool = True,
) -> list[UIAWrapper]:
    matches: list[UIAWrapper] = []
    seen: set[tuple[int, str, str]] = set()
    for wrapper in [*root.children(), *root.descendants()]:
        wrapper_id = _wrapper_identity(wrapper)
        if wrapper_id in seen:
            continue
        seen.add(wrapper_id)
        wrapper_auto_id = str(getattr(wrapper.element_info, "automation_id", "") or "")
        wrapper_title = str(getattr(wrapper.element_info, "name", "") or "")
        wrapper_control_type = str(getattr(wrapper.element_info, "control_type", "") or "")
        if auto_id and not automation_id_matches(wrapper_auto_id, auto_id):
            continue
        if title is not None and normalize_text(wrapper_title) != normalize_text(title):
            continue
        if title_re is not None and re.search(title_re, wrapper_title or "") is None:
            continue
        if control_type is not None and wrapper_control_type != control_type:
            continue
        if visible_only and hasattr(wrapper, "is_visible") and not wrapper.is_visible():
            continue
        matches.append(wrapper)
    return matches


def click(target: UIAWrapper, *, timeout: float = 10.0) -> None:
    wait_for(
        "enabled control",
        lambda: target if not hasattr(target, "is_enabled") or target.is_enabled() else None,
        timeout=timeout,
    )
    _focus_for_input(target)
    try:
        target.invoke()
        return
    except Exception:
        pass
    try:
        target.set_focus()
    except Exception:
        pass
    try:
        target.click_input()
        return
    except Exception:
        pass
    for keys in ("{SPACE}", "{ENTER}"):
        try:
            _send_keys_to(target, keys)
            return
        except Exception:
            continue
    raise AssertionError("Could not click target control")


def activate_menu_path(
    window: UIAWrapper,
    path: list[tuple[str, str | None]],
    *,
    timeout: float = 15.0,
) -> None:
    if not path:
        raise AssertionError("Menu path must include at least one segment")

    menu_bar = child(
        window,
        auto_id="immoMainMenuBar",
        control_type="MenuBar",
        timeout=timeout,
    )

    def _menu_candidate(
        root: UIAWrapper,
        *,
        title: str,
        auto_id: str | None,
    ) -> UIAWrapper | None:
        candidates = [root, *root.descendants()]
        for wrapper in candidates:
            if not isinstance(wrapper, UIAWrapper):
                continue
            if hasattr(wrapper, "is_visible") and not wrapper.is_visible():
                continue
            control_type = str(getattr(wrapper.element_info, "control_type", "") or "")
            if control_type not in {"MenuItem", "Button"}:
                continue
            wrapper_auto_id = str(getattr(wrapper.element_info, "automation_id", "") or "")
            wrapper_title = str(getattr(wrapper.element_info, "name", "") or "")
            if auto_id and automation_id_matches(wrapper_auto_id, auto_id):
                return wrapper
            if normalize_text(wrapper_title) == normalize_text(title):
                return wrapper
        return None

    search_roots: list[UIAWrapper] = [menu_bar]
    for title, auto_id in path:

        def _resolve_menu_target(
            current_title: str = title,
            current_auto_id: str | None = auto_id,
            current_roots: tuple[UIAWrapper, ...] = tuple(search_roots),
        ) -> UIAWrapper | None:
            for root in [*current_roots, *Desktop(backend="uia").windows()]:
                candidate = _menu_candidate(
                    root,
                    title=current_title,
                    auto_id=current_auto_id,
                )
                if candidate is not None:
                    return candidate
            return None

        target = wait_for(
            f"menu item {title!r}",
            _resolve_menu_target,
            timeout=timeout,
        )
        click(target)
        search_roots = [
            wrapper
            for wrapper in Desktop(backend="uia").windows()
            if isinstance(wrapper, UIAWrapper)
        ]


def collapse_combo_popup(combo: UIAWrapper) -> None:
    try:
        combo.collapse()
        return
    except Exception:
        pass
    try:
        _send_keys_to(combo, "{ESC}")
    except Exception:
        pass


def clear_and_type(edit: UIAWrapper, text: str) -> None:
    _focus_for_input(edit)
    try:
        edit.click_input()
    except Exception:  # pragma: no cover - live UI fallback
        pass
    try:
        edit.set_edit_text("")
    except Exception:
        _send_keys_to(edit, "^a{BACKSPACE}")
    try:
        edit.set_edit_text(str(text))
        return
    except Exception:
        pass
    try:
        edit.type_keys(text, with_spaces=True, set_foreground=True)
    except Exception:
        keyboard.send_keys(text, with_spaces=True, pause=0.02)


def clear_and_type_live(edit: UIAWrapper, text: str) -> None:
    _focus_for_input(edit)
    try:
        edit.click_input()
    except Exception:  # pragma: no cover - live UI fallback
        pass
    try:
        _send_keys_to(edit, "^a{BACKSPACE}")
    except Exception:
        try:
            edit.set_edit_text("")
        except Exception:
            pass
    if text:
        try:
            edit.type_keys(str(text), with_spaces=True, set_foreground=True)
            return
        except Exception:
            try:
                keyboard.send_keys(str(text), with_spaces=True, pause=0.02)
                return
            except Exception:
                edit.set_edit_text(str(text))


def select_combo_item(combo: UIAWrapper, label: str, *, verify: bool = True) -> None:
    try:
        combo.select(label)
        collapse_combo_popup(combo)
        if verify:
            wait_for_combo_value(combo, label, timeout=10.0)
        return
    except Exception:
        pass
    _focus_for_input(combo)
    try:
        click(combo)
    except Exception:
        pass
    try:
        combo.expand()
    except Exception:
        try:
            click(combo)
        except Exception:
            pass
        _send_keys_to(combo, "{F4}")

    normalized_label = normalize_text(label).lower()

    def _resolve() -> UIAWrapper | None:
        from pywinauto import Desktop

        for root in Desktop(backend="uia").windows():
            candidates = [root, *root.descendants()]
            for wrapper in candidates:
                if not isinstance(wrapper, UIAWrapper):
                    continue
                if hasattr(wrapper, "is_visible") and not wrapper.is_visible():
                    continue
                control_type = str(getattr(wrapper.element_info, "control_type", "") or "")
                if control_type not in {"ListItem", "DataItem"}:
                    continue
                name = normalize_text(getattr(wrapper.element_info, "name", "")).lower()
                if name == normalized_label:
                    return wrapper
        return None

    list_item = wait_for(f"combo list item {label!r}", _resolve, timeout=10.0)
    click(list_item)
    collapse_combo_popup(combo)
    if verify:
        wait_for_combo_value(combo, label, timeout=10.0)


def select_combo_popup_item_containing(combo: UIAWrapper, expected_text: str) -> None:
    normalized_expected = normalize_text(expected_text).lower()
    if not normalized_expected:
        raise AssertionError("expected_text is required for combo popup selection")
    _focus_for_input(combo)
    try:
        click(combo)
    except Exception:
        pass
    try:
        combo.expand()
    except Exception:
        try:
            click(combo)
        except Exception:
            pass
        _send_keys_to(combo, "{F4}")

    def _resolve() -> UIAWrapper | None:
        from pywinauto import Desktop

        for root in Desktop(backend="uia").windows():
            candidates = [root, *root.descendants()]
            for wrapper in candidates:
                if not isinstance(wrapper, UIAWrapper):
                    continue
                if hasattr(wrapper, "is_visible") and not wrapper.is_visible():
                    continue
                control_type = str(getattr(wrapper.element_info, "control_type", "") or "")
                if control_type not in {"ListItem", "DataItem"}:
                    continue
                name = normalize_text(getattr(wrapper.element_info, "name", "")).lower()
                if normalized_expected and normalized_expected in name:
                    return wrapper
        return None

    target = wait_for(
        f"combo popup item containing {expected_text!r}",
        _resolve,
        timeout=15.0,
    )
    click(target)
    collapse_combo_popup(combo)
    wait_for_combo_value(combo, expected_text, timeout=10.0)


def select_combo_index(combo: UIAWrapper, index: int) -> None:
    if int(index) < 0:
        raise AssertionError(f"Combo index must be non-negative, got {index!r}")
    try:
        combo.select(int(index))
        collapse_combo_popup(combo)
        return
    except Exception:
        pass
    _focus_for_input(combo)
    try:
        click(combo)
    except Exception:
        pass
    try:
        combo.expand()
    except Exception:
        try:
            click(combo)
        except Exception:
            pass
        _send_keys_to(combo, "{F4}")
    _send_keys_to(combo, "{HOME}")
    for _ in range(int(index)):
        _send_keys_to(combo, "{DOWN}")
    _send_keys_to(combo, "{ENTER}")
    collapse_combo_popup(combo)


def select_combo_index_collapsed(
    combo: UIAWrapper,
    index: int,
    *,
    commit: bool = False,
) -> None:
    if int(index) < 0:
        raise AssertionError(f"Combo index must be non-negative, got {index!r}")
    try:
        combo.select(int(index))
        collapse_combo_popup(combo)
        return
    except Exception:
        pass
    _focus_for_input(combo)
    try:
        click(combo)
    except Exception:
        pass
    _send_keys_to(combo, "{HOME}")
    for _ in range(int(index)):
        _send_keys_to(combo, "{DOWN}")
    if commit:
        _send_keys_to(combo, "{ENTER}")
        collapse_combo_popup(combo)


def combo_selected_text(combo: UIAWrapper) -> str:
    try:
        selected = str(combo.selected_text() or "").strip()
        if selected:
            return selected
    except Exception:
        pass
    try:
        value = str(combo.get_value() or "").strip()
        if value:
            return value
    except Exception:
        pass
    try:
        window_text = str(combo.window_text() or "").strip()
        if window_text:
            return window_text
    except Exception:
        pass
    for text in combo.texts():
        normalized = str(text or "").strip()
        if normalized:
            return normalized
    return ""


def wait_for_combo_value(combo: UIAWrapper, expected_text: str, *, timeout: float = 10.0) -> None:
    normalized_expected = normalize_text(expected_text).lower()
    wait_for(
        f"combo value containing {expected_text!r}",
        lambda: (
            True
            if normalized_expected in normalize_text(combo_selected_text(combo)).lower()
            else None
        ),
        timeout=timeout,
    )


def select_tab_by_index(tab_widget: UIAWrapper, index: int) -> None:
    def _items() -> list[UIAWrapper]:
        return [item for item in tab_widget.descendants(control_type="TabItem")]

    items = wait_for("tab items", lambda: _items() if _items() else None, timeout=10.0)
    resolved = list(items)
    if index < 0 or index >= len(resolved):
        raise AssertionError(f"Tab index {index} out of range for {len(resolved)} tab items")
    target = resolved[index]
    try:
        target.select()
        return
    except Exception:
        pass
    click(target)


def select_first_row(table: UIAWrapper) -> None:
    def _rows() -> list[UIAWrapper]:
        rows = []
        for control_type in ("DataItem", "ListItem", "TreeItem"):
            rows.extend(table.descendants(control_type=control_type))
        return rows

    rows = wait_for("table rows", lambda: _rows() if _rows() else None, timeout=15.0)
    click(list(rows)[0])


def wait_for_text(root: UIAWrapper, expected_text: str, *, timeout: float = 20.0) -> None:
    expected = normalize_text(expected_text).lower()
    wait_for(
        f"text {expected_text!r}",
        lambda: True if any(expected in text.lower() for text in wrapper_texts(root)) else None,
        timeout=timeout,
    )


def wait_for_absent_text(root: UIAWrapper, expected_text: str, *, timeout: float = 20.0) -> None:
    expected = normalize_text(expected_text).lower()
    wait_for(
        f"absence of text {expected_text!r}",
        lambda: True if all(expected not in text.lower() for text in wrapper_texts(root)) else None,
        timeout=timeout,
    )


def wait_for_row_text(table: UIAWrapper, expected_text: str, *, timeout: float = 20.0) -> None:
    wait_for_text(table, expected_text, timeout=timeout)


def choose_file(open_dialog: UIAWrapper, file_path: Path) -> None:
    dialog_handle = int(getattr(open_dialog, "handle", 0) or 0)
    dialog_title = normalize_text(getattr(open_dialog.element_info, "name", "") or "")

    filename_edit: UIAWrapper | None = None
    for candidate in (
        lambda: child(
            open_dialog,
            auto_id="1148",
            control_type="Edit",
            timeout=1.0,
            visible_only=False,
        ),
        lambda: child(
            open_dialog,
            auto_id="1148",
            timeout=1.0,
            visible_only=False,
        ),
        lambda: child(
            open_dialog,
            control_type="Edit",
            found_index=0,
            timeout=1.0,
            visible_only=False,
        ),
    ):
        try:
            filename_edit = candidate()
            break
        except Exception:
            continue
    if filename_edit is not None:
        clear_and_type(filename_edit, str(file_path))
        try:
            _send_keys_to(filename_edit, "{ENTER}")
        except Exception:
            pass
    else:
        open_dialog.set_focus()
        for accelerator in ("%n", ""):
            if accelerator:
                keyboard.send_keys(accelerator)
                time.sleep(0.2)
            keyboard.send_keys("^a{BACKSPACE}")
            keyboard.send_keys(str(file_path), with_spaces=True, pause=0.02)
            time.sleep(0.2)
            keyboard.send_keys("{ENTER}")
            return

    confirm_button: UIAWrapper | None = None
    confirm_candidates: list[dict[str, str]] = [
        {"auto_id": "1", "control_type": "SplitButton"},
        {"title": "Open", "control_type": "SplitButton"},
        {"title": "Ouvrir", "control_type": "SplitButton"},
        {"title": "OK", "control_type": "SplitButton"},
        {"auto_id": "1", "control_type": "Button"},
        {"title": "Open", "control_type": "Button"},
        {"title": "Ouvrir", "control_type": "Button"},
        {"title": "OK", "control_type": "Button"},
    ]
    for confirm_candidate in confirm_candidates:
        try:
            confirm_button = child(
                open_dialog,
                auto_id=confirm_candidate.get("auto_id"),
                title=confirm_candidate.get("title"),
                control_type=str(confirm_candidate["control_type"]),
                timeout=1.0,
                visible_only=False,
            )
            break
        except Exception:
            continue

    def _dialog_still_present() -> bool:
        for window in Desktop(backend="uia").windows():
            window_handle = int(getattr(window, "handle", 0) or 0)
            if dialog_handle and window_handle == dialog_handle:
                return True
            if dialog_title and normalize_text(window.window_text()) == dialog_title:
                return True
        return False

    if _dialog_still_present():
        open_dialog.set_focus()
        if confirm_button is not None:
            click(confirm_button)
        else:
            keyboard.send_keys("{ENTER}")

    try:
        wait_for(
            "file dialog to close",
            lambda: None if _dialog_still_present() else True,
            timeout=5.0,
        )
    except AssertionError:
        pass


def click_message_box_button(dialog: UIAWrapper, *labels: str) -> None:
    for label in labels:
        try:
            button = child(
                dialog,
                title=label,
                control_type="Button",
                timeout=2.0,
                visible_only=False,
            )
            click(button)
            return
        except Exception:
            continue
    raise AssertionError(f"Could not find any message-box button in {labels!r}")


def write_text_file(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
