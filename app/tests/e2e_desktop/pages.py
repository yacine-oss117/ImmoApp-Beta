from __future__ import annotations

import re
from pathlib import Path
from typing import cast

from pywinauto import keyboard
from pywinauto.controls.uiawrapper import UIAWrapper

from app.tests.e2e_desktop.runtime import DesktopSession
from app.tests.e2e_desktop.ui import (
    activate_menu_path,
    child,
    choose_file,
    clear_and_type,
    clear_and_type_live,
    click,
    click_message_box_button,
    combo_selected_text,
    descendant_with_auto_id_prefix,
    matching_descendants,
    normalize_text,
    select_combo_index,
    select_combo_item,
    select_combo_popup_item_containing,
    select_first_row,
    select_tab_by_index,
    wait_for,
    wait_for_absent_text,
    wait_for_combo_value,
    wait_for_text,
    wrapper_texts,
)
from core.data.locations import ALGERIAN_LOCATIONS, ALGERIAN_WILAYAS

_TAB_INDEX = {
    "dashboard": 0,
    "matches": 1,
    "clients": 2,
    "listings": 3,
    "crm": 4,
}

_COMBO_LABEL_INDEX = {
    "demandeTypeCombo": {
        "Any": 0,
        "Apartment": 1,
        "House": 2,
        "Business": 3,
        "Land": 4,
        "Other": 5,
    },
    "offerTypeCombo": {
        "Any": 0,
        "Apartment": 1,
        "House": 2,
        "Business": 3,
        "Land": 4,
        "Other": 5,
    },
    "demandeActionCombo": {"To Buy": 0, "To Rent": 1},
    "offerActionCombo": {"For Sale": 0, "For Rent": 1},
    "demandeFurnishedCombo": {"Any": 0, "Yes": 1, "No": 2},
    "offerFurnishedCombo": {"Yes": 0, "No": 1, "Any": 2},
}


def _panel_text(root: UIAWrapper) -> str:
    return " ".join(wrapper_texts(root)).lower()


def _scroll_into_view(target: UIAWrapper) -> None:
    for action in (
        lambda: target.scroll_into_view(),
        lambda: target.iface_scroll_item.ScrollIntoView(),
    ):
        try:
            action()
            return
        except Exception:
            pass


def _wait_for_message_box_text(
    session: DesktopSession,
    *,
    expected_texts: tuple[str, ...],
    timeout: float = 25.0,
) -> UIAWrapper:
    expected = tuple(normalize_text(text).lower() for text in expected_texts)

    def _matching_dialog() -> UIAWrapper | None:
        try:
            dialog = session.message_box(timeout=0.5)
        except AssertionError:
            return None
        text_blob = " ".join(wrapper_texts(dialog)).lower()
        return dialog if all(text in text_blob for text in expected) else None

    return wait_for(
        f"message box containing {', '.join(repr(text) for text in expected_texts)}",
        _matching_dialog,
        timeout=timeout,
    )


def _set_field_text(root: UIAWrapper, auto_id: str, value: object) -> None:
    target = child(root, auto_id=auto_id, timeout=10.0, visible_only=False)
    _scroll_into_view(target)
    text = str(value)
    expected = normalize_text(text).lower()
    control_type = str(getattr(target.element_info, "control_type", "") or "")

    def _value_text(wrapper: UIAWrapper) -> str:
        values: list[str] = []
        for getter in (
            lambda: wrapper.iface_range_value.CurrentValue,
            lambda: wrapper.iface_value.CurrentValue,
            lambda: wrapper.get_value(),
            lambda: wrapper.window_text(),
        ):
            try:
                values.append(str(getter() or ""))
            except Exception:
                pass
        try:
            values.extend(str(item or "") for item in wrapper.texts())
        except Exception:
            pass
        return normalize_text(" ".join(values)).lower()

    def _matches(wrapper: UIAWrapper) -> bool:
        if expected in _value_text(wrapper):
            return True
        try:
            return float(wrapper.iface_range_value.CurrentValue) == float(str(value))
        except Exception:
            return False

    def _commit_and_verify(
        wrapper: UIAWrapper,
        description: str,
        timeout: float = 1.0,
        *,
        require_target: bool = False,
    ) -> bool:
        keyboard.send_keys("{TAB}", pause=0.05)
        try:
            wait_for(
                description,
                lambda: (
                    True if _matches(target) or (not require_target and _matches(wrapper)) else None
                ),
                timeout=timeout,
            )
            return True
        except AssertionError:
            return False

    if control_type == "Spinner":
        input_target = target
        try:
            input_target = child(
                target,
                auto_id=f"{auto_id}Edit",
                control_type="Edit",
                timeout=1.0,
                visible_only=False,
            )
        except Exception:
            pass
        try:
            input_target.set_focus()
        except Exception:
            pass
        try:
            input_target.click_input()
        except Exception:
            click(input_target)
        try:
            input_target.type_keys("^a{BACKSPACE}", set_foreground=True)
            input_target.type_keys(text, with_spaces=True, set_foreground=True)
            input_target.type_keys("{TAB}", set_foreground=True)
        except Exception:
            keyboard.send_keys("^a{BACKSPACE}", pause=0.05)
            keyboard.send_keys(text, with_spaces=True, pause=0.02)
            keyboard.send_keys("{TAB}", pause=0.05)
        return

    if control_type == "Edit":
        if auto_id == "offerPriceFlexInput":
            clear_and_type_live(target, text)
        else:
            clear_and_type(target, text)
        keyboard.send_keys("{TAB}", pause=0.05)
        return
    for scope in (target, root):
        try:
            editor = child(
                scope,
                auto_id=f"{auto_id}Edit",
                control_type="Edit",
                timeout=1.0,
                visible_only=False,
            )
            clear_and_type_live(editor, text)
            if _commit_and_verify(
                editor,
                f"field {auto_id!r} edit value {text!r}",
                require_target=True,
            ):
                return
        except Exception:
            pass

    for setter in (
        lambda: target.iface_range_value.SetValue(float(str(value))),
        lambda: target.iface_value.SetValue(text),
        lambda: target.set_value(text),
    ):
        try:
            setter()
            if _commit_and_verify(target, f"field {auto_id!r} value {text!r}"):
                return
        except Exception:
            pass
    try:
        target.set_focus()
    except Exception:
        pass
    try:
        target.click_input()
    except Exception:
        pass
    try:
        keyboard.send_keys("^a{BACKSPACE}", pause=0.05)
        keyboard.send_keys(text, with_spaces=True, pause=0.02)
        if _commit_and_verify(target, f"field {auto_id!r} keyboard value {text!r}"):
            return
    except Exception:
        pass
    try:
        clear_and_type(target, text)
    except Exception:
        editor = child(target, control_type="Edit", timeout=2.0, visible_only=False)
        clear_and_type_live(editor, text)
        if _commit_and_verify(editor, f"field {auto_id!r} fallback edit value {text!r}"):
            return
    if not _commit_and_verify(target, f"field {auto_id!r} fallback value {text!r}"):
        raise AssertionError(f"Unable to set field {auto_id!r} to {text!r}")


def _set_spinbox_value(root: UIAWrapper, auto_id: str, value: int | float) -> None:
    target = child(root, auto_id=auto_id, timeout=10.0, visible_only=False)
    _scroll_into_view(target)
    expected = float(value)
    text = str(value)
    observed_values: list[str] = []
    editor_target: UIAWrapper | None = None

    def _editor() -> UIAWrapper | None:
        nonlocal editor_target
        if editor_target is not None:
            return editor_target
        for resolver in (
            lambda: child(
                root,
                auto_id=f"{auto_id}Edit",
                control_type="Edit",
                timeout=0.5,
                visible_only=False,
            ),
            lambda: child(target, control_type="Edit", timeout=0.5, visible_only=False),
        ):
            try:
                editor_target = resolver()
                return editor_target
            except Exception:
                pass
        return None

    def _current_value() -> float | None:
        values: list[object] = []
        sources = [target]
        editor = _editor()
        if editor is not None:
            sources.append(editor)
        for source in sources:
            for getter in (
                lambda source=source: source.iface_range_value.CurrentValue,
                lambda source=source: source.iface_value.CurrentValue,
                lambda source=source: source.get_value(),
                lambda source=source: source.window_text(),
            ):
                try:
                    values.append(getter())
                except Exception:
                    pass
            try:
                values.extend(source.texts())
            except Exception:
                pass
        for raw_value in values:
            raw_text = normalize_text(raw_value).replace(",", "")
            if raw_text:
                observed_values.append(raw_text)
            if not raw_text:
                continue
            match = re.search(r"[-+]?\d+(?:\s\d{3})*(?:\.\d+)?", raw_text)
            candidate = (match.group(0) if match else raw_text.split(" ", 1)[0]).replace(" ", "")
            try:
                return float(candidate)
            except ValueError:
                continue
        return None

    def _matches() -> bool:
        current = _current_value()
        return current is not None and abs(current - expected) < 0.001

    try:
        editor = _editor()
        if editor is not None:
            _scroll_into_view(editor)
            try:
                editor.set_focus()
            except Exception:
                pass
            try:
                editor.click_input()
            except Exception:
                click(editor)
            try:
                editor.type_keys("^a{BACKSPACE}", set_foreground=True)
                editor.type_keys(text, with_spaces=True, set_foreground=True)
                editor.type_keys("{TAB}", set_foreground=True)
            except Exception:
                keyboard.send_keys("^a{BACKSPACE}", pause=0.05)
                keyboard.send_keys(text, with_spaces=True, pause=0.02)
                keyboard.send_keys("{TAB}", pause=0.05)
            wait_for(
                f"spinbox {auto_id!r} editor value {text!r}",
                lambda: True if _matches() else None,
                timeout=5.0,
            )
            return
    except Exception:
        pass

    try:
        target.set_focus()
    except Exception:
        pass
    try:
        target.click_input()
        keyboard.send_keys("^a{BACKSPACE}", pause=0.05)
        keyboard.send_keys(text, with_spaces=True, pause=0.02)
        keyboard.send_keys("{TAB}", pause=0.05)
        if _current_value() is None:
            raise AssertionError(f"Unable to read spinbox {auto_id!r} after direct keyboard")
        wait_for(
            f"spinbox {auto_id!r} direct keyboard value {text!r}",
            lambda: True if _matches() else None,
            timeout=3.0,
        )
        return
    except Exception:
        pass

    try:
        editor = _editor()
        if editor is None:
            raise LookupError(f"No editor found for {auto_id!r}")
        _scroll_into_view(editor)
        clear_and_type_live(editor, text)
        keyboard.send_keys("{TAB}", pause=0.05)
        if _current_value() is None:
            raise AssertionError(f"Unable to read spinbox {auto_id!r} after keyboard")
        wait_for(
            f"spinbox {auto_id!r} keyboard value {text!r}",
            lambda: True if _matches() else None,
            timeout=5.0,
        )
        return
    except Exception:
        pass

    for setter in (
        lambda: target.iface_range_value.SetValue(expected),
        lambda: target.iface_value.SetValue(text),
        lambda: target.set_value(text),
    ):
        try:
            setter()
            keyboard.send_keys("{TAB}", pause=0.05)
            if _current_value() is None:
                raise AssertionError(f"Unable to read spinbox {auto_id!r} after setter")
            wait_for(
                f"spinbox {auto_id!r} value {text!r}",
                lambda: True if _matches() else None,
                timeout=2.0,
            )
            return
        except Exception:
            pass

    observed = ", ".join(dict.fromkeys(observed_values[-12:])) or "<no UIA value>"
    raise AssertionError(
        f"Unable to set spinbox {auto_id!r} to {text!r}; observed values: {observed}"
    )


def _set_combo_label(root: UIAWrapper, auto_id: str, label: str) -> None:
    combo = child(root, auto_id=auto_id, timeout=10.0, visible_only=False)
    label_indexes = _COMBO_LABEL_INDEX.get(auto_id, {})
    if label in label_indexes:
        try:
            select_combo_index(combo, label_indexes[label])
            wait_for_combo_value(combo, label, timeout=2.0)
            return
        except Exception:
            pass
    try:
        select_combo_item(combo, label)
        return
    except Exception:
        pass
    select_combo_item(combo, label, verify=False)


def _control_text_blob(*controls: UIAWrapper) -> str:
    values: list[str] = []
    for control in controls:
        for getter in (
            lambda control=control: control.iface_value.CurrentValue,
            lambda control=control: control.get_value(),
            lambda control=control: control.window_text(),
        ):
            try:
                values.append(str(getter() or ""))
            except Exception:
                pass
        try:
            values.extend(str(text or "") for text in control.texts())
        except Exception:
            pass
    return normalize_text(" ".join(values)).lower()


def _prefix_combo_value_candidates(value: str) -> list[str]:
    raw = str(value or "").strip()
    if not raw:
        return []
    candidates = [raw]
    normalized = normalize_text(raw).lower()
    for wilaya in ALGERIAN_WILAYAS:
        wilaya_text = str(wilaya)
        wilaya_normalized = normalize_text(wilaya_text).lower()
        if wilaya_normalized == normalized or wilaya_normalized.startswith(f"{normalized} -"):
            if wilaya_text not in candidates:
                candidates.insert(0, wilaya_text)
            break
    return candidates


def _location_value_candidates(value: str) -> list[str]:
    raw = str(value or "").strip()
    if not raw:
        return []
    candidates = [raw]
    normalized = normalize_text(raw).lower()
    for location in ALGERIAN_LOCATIONS:
        location_text = str(location)
        location_normalized = normalize_text(location_text).lower()
        if location_normalized == normalized or location_normalized.startswith(f"{normalized},"):
            if location_text not in candidates:
                candidates.insert(0, location_text)
            break
    return candidates


def _set_prefix_combo_value(
    root: UIAWrapper,
    *,
    combo_auto_id: str,
    input_auto_id: str,
    value: str,
) -> None:
    combo = child(root, auto_id=combo_auto_id, timeout=10.0, visible_only=False)
    edit = child(
        root,
        auto_id=input_auto_id,
        control_type="Edit",
        timeout=10.0,
        visible_only=False,
    )
    observed: list[str] = []
    for candidate in _prefix_combo_value_candidates(value):
        expected = normalize_text(candidate).lower()
        clear_and_type_live(edit, candidate)
        try:
            edit.set_focus()
            keyboard.send_keys("{ENTER}", pause=0.05)
        except Exception:
            pass
        try:

            def _combo_contains_expected(expected_text: str = expected) -> UIAWrapper | None:
                if expected_text in _control_text_blob(combo, edit):
                    return combo
                if expected_text in normalize_text(combo_selected_text(combo)).lower():
                    return combo
                return None

            wait_for(
                f"typed prefix combo value {candidate!r}",
                _combo_contains_expected,
                timeout=3.0,
            )
            return
        except AssertionError:
            observed.append(_control_text_blob(combo, edit) or "<no UIA value>")
        try:
            select_combo_popup_item_containing(combo, candidate)
            return
        except AssertionError:
            observed.append(_control_text_blob(combo, edit) or "<no UIA value>")

    raise AssertionError(
        f"Unable to set prefix combo {combo_auto_id!r} to {value!r}; "
        f"observed values: {', '.join(dict.fromkeys(observed[-8:])) or '<none>'}"
    )


def _add_location_value(root: UIAWrapper, *, prefix: str, value: str) -> None:
    edit = child(
        root,
        auto_id=f"{prefix}Input",
        control_type="Edit",
        timeout=10.0,
        visible_only=False,
    )

    def _edit_contains_value(expected: str) -> bool:
        values: list[str] = []
        for getter in (
            lambda: edit.iface_value.CurrentValue,
            lambda: edit.get_value(),
            lambda: edit.window_text(),
        ):
            try:
                values.append(str(getter() or ""))
            except Exception:
                pass
        values.extend(wrapper_texts(edit))
        return expected in normalize_text(" ".join(values)).lower()

    observed: list[str] = []
    for candidate in _location_value_candidates(value):
        expected = normalize_text(candidate).lower()
        clear_and_type_live(edit, candidate)
        try:

            def _live_input_contains_expected(expected_text: str = expected) -> bool | None:
                return True if _edit_contains_value(expected_text) else None

            wait_for(
                f"location input typed {candidate!r}",
                _live_input_contains_expected,
                timeout=2.0,
            )
        except AssertionError:
            clear_and_type(edit, candidate)

            def _fallback_input_contains_expected(expected_text: str = expected) -> bool | None:
                return True if _edit_contains_value(expected_text) else None

            wait_for(
                f"location input typed {candidate!r}",
                _fallback_input_contains_expected,
                timeout=5.0,
            )
        try:
            edit.set_focus()
            keyboard.send_keys("{ENTER}", pause=0.05)
        except Exception:
            pass
        try:

            def _panel_contains_expected(expected_text: str = expected) -> bool | None:
                return True if expected_text in _panel_text(root) else None

            wait_for(
                f"location chip added {candidate!r}",
                _panel_contains_expected,
                timeout=3.0,
            )
            return
        except AssertionError:
            observed.append(_panel_text(root) or "<no panel text>")
        add_button = child(root, auto_id=f"{prefix}AddButton", timeout=10.0, visible_only=False)
        _scroll_into_view(add_button)
        try:
            add_button.click_input()
        except Exception:
            click(add_button)
        try:

            def _panel_contains_expected_after_click(
                expected_text: str = expected,
            ) -> bool | None:
                return True if expected_text in _panel_text(root) else None

            wait_for(
                f"location chip added {candidate!r}",
                _panel_contains_expected_after_click,
                timeout=10.0,
            )
            return
        except AssertionError:
            observed.append(_panel_text(root) or "<no panel text>")

    raise AssertionError(
        f"Unable to add location {value!r}; "
        f"observed panel text: {', '.join(dict.fromkeys(observed[-4:])) or '<none>'}"
    )


def _is_checked(control: UIAWrapper) -> bool:
    try:
        return bool(control.get_toggle_state())
    except Exception:
        pass
    try:
        return bool(control.iface_toggle.CurrentToggleState)
    except Exception:
        return False


def _set_checkbox(root: UIAWrapper, auto_id: str, checked: bool) -> None:
    control = child(root, auto_id=auto_id, timeout=10.0, visible_only=False)
    if _is_checked(control) != bool(checked):
        click(control)


def _tree_descendants(root: UIAWrapper, control_type: str) -> list[UIAWrapper]:
    try:
        return list(root.descendants(control_type=control_type))
    except KeyError:
        pass

    rows: list[UIAWrapper] = []
    try:
        stack = list(reversed(root.element_info.children()))
    except Exception:
        return rows
    while stack:
        info = stack.pop()
        if getattr(info, "control_type", None) == control_type:
            try:
                rows.append(UIAWrapper(info))
            except KeyError:
                pass
        try:
            stack.extend(reversed(info.children()))
        except Exception:
            continue
    return rows


def _wait_for_control_absent(root: UIAWrapper, *, auto_id: str, timeout: float = 20.0) -> None:
    wait_for(
        f"absence of control {auto_id!r}",
        lambda: (
            True
            if not matching_descendants(
                root,
                auto_id=auto_id,
                visible_only=False,
            )
            else None
        ),
        timeout=timeout,
    )


def _open_tree_row_containing(tree: UIAWrapper, expected_text: str) -> None:
    expected = normalize_text(expected_text).lower()

    def _column_count() -> int:
        try:
            headers = _tree_descendants(tree, "Header")
        except Exception:
            headers = []
        return max(1, len(headers))

    def _row() -> UIAWrapper | None:
        for control_type in ("DataItem", "ListItem", "TreeItem"):
            rows = _tree_descendants(tree, control_type)
            columns = _column_count() if control_type == "TreeItem" else 1
            for index, row in enumerate(rows):
                name = normalize_text(getattr(row.element_info, "name", "")).lower()
                if expected in name:
                    row_start = index - (index % columns)
                    return rows[row_start]
        return None

    row = wait_for(f"tree row containing {expected_text!r}", _row, timeout=10.0)
    try:
        row.select()
        return
    except Exception:
        pass
    try:
        click(row)
        return
    except Exception:
        pass
    try:
        row.double_click_input()
    except Exception:
        keyboard.send_keys("{ENTER}", pause=0.05)


def _activate_first_visible_tree_row(tree: UIAWrapper) -> None:
    try:
        tree.set_focus()
    except Exception:
        pass
    try:
        click(tree)
    except Exception:
        pass
    keyboard.send_keys("{HOME}{DOWN}{ENTER}", pause=0.05)


class SetupWizardPage:
    def __init__(self, dialog: UIAWrapper) -> None:
        self.dialog = dialog

    @classmethod
    def wait(cls, session: DesktopSession) -> SetupWizardPage:
        return cls(session.window(auto_id="immoSetupWizardDialog"))

    def connect_manual(self, base_url: str) -> None:
        clear_and_type(child(self.dialog, auto_id="setupWizardManualUrlInput"), base_url)
        if "127.0.0.1" in base_url or "localhost" in base_url:
            checkbox = child(self.dialog, auto_id="setupWizardLocalHubCheckbox")
            try:
                if checkbox.get_toggle_state() == 0:
                    click(checkbox)
            except Exception:
                click(checkbox)
        click(child(self.dialog, auto_id="setupWizardManualConnectButton"))


class QuickStartPage:
    def __init__(self, dialog: UIAWrapper) -> None:
        self.dialog = dialog

    @classmethod
    def wait(cls, session: DesktopSession) -> QuickStartPage:
        return cls(session.window(title_re=".*Get started.*"))

    def choose_sign_in(self) -> None:
        click(child(self.dialog, auto_id="quickStartSignInButton"))


class LoginPage:
    def __init__(self, dialog: UIAWrapper) -> None:
        self.dialog = dialog

    @classmethod
    def wait(cls, session: DesktopSession) -> LoginPage:
        return cls(session.window(auto_id="immoLoginDialog"))

    def sign_in(self, username: str, password: str, *, base_url: str | None = None) -> None:
        if base_url:
            try:
                base_url_input = child(
                    self.dialog,
                    auto_id="immoLoginBaseUrlInput",
                    control_type="Edit",
                    timeout=1.0,
                    visible_only=False,
                )
            except AssertionError:
                base_url_input = None
            if base_url_input is not None and base_url_input.is_visible():
                clear_and_type(base_url_input, base_url)
        clear_and_type(child(self.dialog, auto_id="immoLoginUsernameInput"), username)
        clear_and_type(child(self.dialog, auto_id="immoLoginPasswordInput"), password)
        click(child(self.dialog, auto_id="immoLoginPrimaryButton"))

    def wait_for_error(self, expected_text: str) -> None:
        wait_for_text(child(self.dialog, auto_id="immoLoginStatus"), expected_text, timeout=20.0)


class MainWindowPage:
    def __init__(self, window: UIAWrapper, session: DesktopSession) -> None:
        self.window = window
        self.session = session

    @classmethod
    def wait(cls, session: DesktopSession) -> MainWindowPage:
        return cls(session.window(auto_id="immoMainWindow", timeout=40.0), session)

    @property
    def tabs(self) -> UIAWrapper:
        return child(self.window, auto_id="immoMainTabs")

    def select_tab(self, tab_id: str) -> None:
        normalized = str(tab_id).strip().lower()
        if normalized not in _TAB_INDEX:
            raise AssertionError(f"Unknown tab id {tab_id!r}")
        select_tab_by_index(self.tabs, _TAB_INDEX[normalized])
        expected_control = {
            "matches": "matchRunButton",
            "clients": "clientFamilyNameInput",
            "listings": "listingOwnerNameInput",
            "crm": "crmFollowupTabs",
        }.get(normalized)
        if expected_control:
            child(self.window, auto_id=expected_control, timeout=20.0)

    def open_notifications(self) -> NotificationsPage:
        def _open() -> UIAWrapper | None:
            try:
                self.window.set_focus()
            except Exception:
                pass
            try:
                notifications_button = child(
                    self.window,
                    auto_id="immoNotificationsButton",
                    control_type="Button",
                    timeout=2.0,
                )
                notifications_button.click_input()
            except Exception:
                keyboard.send_keys("^%n", pause=0.05)
            try:
                toast_close = self.session.element(
                    auto_id="notificationToastClose",
                    control_type="Button",
                    timeout=0.5,
                )
            except AssertionError:
                toast_close = None
            if toast_close is not None:
                try:
                    click(toast_close)
                except Exception:
                    pass
            dialog = self.session.try_window(auto_id="NotificationsDialog", timeout=0.5)
            if dialog is not None:
                return dialog
            keyboard.send_keys("^%n", pause=0.05)
            return self.session.try_window(auto_id="NotificationsDialog", timeout=0.5)

        dialog = wait_for(
            "notifications dialog",
            _open,
            timeout=20.0,
        )
        return NotificationsPage(dialog)

    def open_agency_settings(self) -> AgencySettingsPage:
        def _open() -> UIAWrapper | None:
            try:
                self.window.set_focus()
            except Exception:
                pass
            keyboard.send_keys("^%p", pause=0.05)
            dialog = self.session.try_window(auto_id="agencySettingsDialog", timeout=0.5)
            if dialog is not None:
                return dialog
            try:
                activate_menu_path(
                    self.window,
                    [
                        ("Settings", "immoMenuSettingsAction"),
                        ("Agency Profile", "menuAction_settings_agency_profile"),
                    ],
                    timeout=4.0,
                )
            except AssertionError:
                try:
                    self.window.set_focus()
                except Exception:
                    pass
                keyboard.send_keys("{F10}{ENTER}{DOWN}{DOWN}{ENTER}", pause=0.05)
            dialog = self.session.try_window(auto_id="agencySettingsDialog", timeout=0.5)
            if dialog is not None:
                return dialog
            keyboard.send_keys("^%p", pause=0.05)
            return self.session.try_window(auto_id="agencySettingsDialog", timeout=0.5)

        dialog = wait_for(
            "agency settings dialog",
            _open,
            timeout=20.0,
        )
        return AgencySettingsPage(dialog, self.session)

    def wait_for_toast(self, *, title: str, body: str | None = None, timeout: float = 20.0) -> None:
        self.session.element(
            auto_id="notificationToastTitle",
            title=title,
            control_type="Text",
            timeout=timeout,
        )
        if body:
            self.session.element(
                auto_id="notificationToastBody",
                title=body,
                control_type="Text",
                timeout=timeout,
            )

    def wait_for_text(self, text: str, *, timeout: float = 20.0) -> None:
        wait_for_text(self.window, text, timeout=timeout)

    def wait_for_notice(
        self,
        *,
        title: str,
        body: str | None = None,
        timeout: float = 20.0,
    ) -> None:
        self.session.element(
            auto_id="noticeBannerTitle",
            title=title,
            control_type="Text",
            timeout=timeout,
        )
        if body:
            self.session.element(
                auto_id="noticeBannerBody",
                title_re=".*",
                control_type="Text",
                timeout=timeout,
            )
            wait_for_text(self.window, body, timeout=timeout)


class NotificationsPage:
    def __init__(self, dialog: UIAWrapper) -> None:
        self.dialog = dialog

    @classmethod
    def wait(cls, session: DesktopSession) -> NotificationsPage:
        return cls(session.window(auto_id="NotificationsDialog", timeout=20.0))

    def wait_for_notification(self, *, title: str, body: str | None = None) -> None:
        wait_for_text(self.dialog, title, timeout=20.0)
        if body:
            wait_for_text(self.dialog, body, timeout=20.0)

    def close(self) -> None:
        click(child(self.dialog, auto_id="notificationsCloseButton"))
        wait_for(
            "notifications dialog close",
            lambda: None if self.dialog.is_visible() else True,
            timeout=10.0,
        )


class AgencySettingsPage:
    def __init__(self, dialog: UIAWrapper, session: DesktopSession) -> None:
        self.dialog = dialog
        self.session = session

    @classmethod
    def wait(cls, session: DesktopSession) -> AgencySettingsPage:
        return cls(session.window(auto_id="agencySettingsDialog", timeout=20.0), session)

    def set_agency_name(self, value: str) -> None:
        clear_and_type(child(self.dialog, auto_id="agencySettingsNameInput"), value)

    def current_agency_name(self) -> str:
        control = child(self.dialog, auto_id="agencySettingsNameInput")
        texts = [text for text in control.texts() if str(text or "").strip()]
        return str(texts[0] if texts else control.window_text() or "").strip()

    def wait_for_status(self, expected_text: str) -> None:
        wait_for_text(
            child(self.dialog, auto_id="agencySettingsStatus"), expected_text, timeout=15.0
        )

    def save(self) -> None:
        click(child(self.dialog, auto_id="agencySettingsSaveButton"))
        wait_for(
            "agency settings close",
            lambda: (
                None
                if self.session.try_window(auto_id="agencySettingsDialog", timeout=0.3)
                else True
            ),
            timeout=20.0,
        )


class ClientsPage:
    def __init__(self, main: MainWindowPage, session: DesktopSession) -> None:
        self.main = main
        self.session = session
        child(main.window, auto_id="clientFamilyNameInput", timeout=20.0)

    @property
    def tree(self) -> UIAWrapper:
        return child(self.main.window, title="Clients tree", control_type="Tree")

    def wait_for_tree_rows(
        self,
        *,
        expected_text: str | None = None,
        timeout: float = 20.0,
    ) -> UIAWrapper:
        normalized_expected = str(expected_text or "").strip().lower()

        def _matching_tree(tree: UIAWrapper) -> UIAWrapper | None:
            rows: list[UIAWrapper] = []
            for control_type in ("DataItem", "ListItem", "TreeItem"):
                rows.extend(_tree_descendants(tree, control_type))
            if not rows:
                return None
            if normalized_expected:
                row_text = " ".join(
                    str(getattr(row.element_info, "name", "") or "").strip().lower() for row in rows
                )
                if normalized_expected not in row_text:
                    return None
            return tree

        def _resolve() -> UIAWrapper | None:
            tree = self.tree
            matched = _matching_tree(tree)
            if matched is not None:
                return matched
            try:
                click(child(self.main.window, auto_id="clientsExpandAllButton", timeout=1.0))
            except Exception:
                return None
            return _matching_tree(self.tree)

        return wait_for("client tree rows", _resolve, timeout=timeout)

    def current_family_name(self) -> str:
        control = child(self.main.window, auto_id="clientFamilyNameInput")
        texts = [text for text in control.texts() if str(text or "").strip()]
        return str(texts[0] if texts else control.window_text() or "").strip()

    def current_phone(self) -> str:
        control = child(self.main.window, auto_id="clientPhoneInput")
        texts = [text for text in control.texts() if str(text or "").strip()]
        return str(texts[0] if texts else control.window_text() or "").strip()

    def create_client(self, *, family_name: str, phone: str) -> None:
        clear_and_type(child(self.main.window, auto_id="clientFamilyNameInput"), family_name)
        clear_and_type(child(self.main.window, auto_id="clientPhoneInput"), phone)
        click(child(self.main.window, auto_id="clientsSaveButton"))
        dialog = self.session.message_box(timeout=10.0)
        wait_for_text(dialog, family_name, timeout=10.0)
        click_message_box_button(dialog, "OK", "Ok", "&OK")

    def create_client_expect_auth_error(self, *, family_name: str, phone: str) -> str:
        clear_and_type(child(self.main.window, auto_id="clientFamilyNameInput"), family_name)
        clear_and_type(child(self.main.window, auto_id="clientPhoneInput"), phone)
        click(child(self.main.window, auto_id="clientsSaveButton"))
        dialog = self.session.element(
            auto_id="clientsAuthRequiredMessageBox",
            title="Session needs attention",
            control_type="Window",
            timeout=15.0,
        )
        text = " ".join(wrapper_texts(dialog))
        expected = (
            "Your session or permissions changed while this page was open. "
            "Sign in again and try again."
        )
        if expected not in text:
            raise AssertionError(f"Unexpected auth/session error dialog text: {text}")
        click_message_box_button(dialog, "OK", "Ok", "&OK")
        return text

    def search(self, value: str) -> None:
        clear_and_type_live(child(self.main.window, auto_id="clientsSearchInput"), value)

    def open_first_listed_client(self) -> None:
        tree = self.tree
        try:
            first_row = wait_for(
                "first listed client row",
                lambda: next(
                    iter(
                        [
                            *_tree_descendants(tree, "DataItem"),
                            *_tree_descendants(tree, "ListItem"),
                            *_tree_descendants(tree, "TreeItem"),
                        ]
                    ),
                    None,
                ),
                timeout=5.0,
            )
            try:
                first_row.double_click_input()
                return
            except Exception:
                click(first_row)
                keyboard.send_keys("{ENTER}", pause=0.05)
                return
        except AssertionError:
            pass
        try:
            tree.set_focus()
        except Exception:
            pass
        try:
            click(tree)
        except Exception:
            pass
        keyboard.send_keys("{HOME}{DOWN}{ENTER}", pause=0.05)

    def select_existing(
        self,
        *,
        search_value: str,
        expected_name: str,
        editor_expected_name: str | None = None,
    ) -> None:
        self.search(search_value)
        try:
            self.wait_for_tree_rows(expected_text=expected_name, timeout=20.0)
        except AssertionError:
            click(child(self.main.window, auto_id="clientsExpandAllButton", timeout=10.0))
            self.wait_for_tree_rows(expected_text=expected_name, timeout=30.0)
        _open_tree_row_containing(self.tree, expected_name)
        selected_text = (editor_expected_name or expected_name).lower()
        try:
            wait_for(
                "selected client editor state",
                lambda: (
                    self.current_family_name()
                    if selected_text in self.current_family_name().lower()
                    else None
                ),
                timeout=10.0,
            )
        except AssertionError:
            _activate_first_visible_tree_row(self.tree)
            wait_for(
                "selected client editor state",
                lambda: (
                    self.current_family_name()
                    if selected_text in self.current_family_name().lower()
                    else None
                ),
                timeout=20.0,
            )

    def select_visible_existing(
        self,
        *,
        expected_name: str,
        editor_expected_name: str | None = None,
    ) -> None:
        self.search("")
        self.wait_for_tree_rows(expected_text=expected_name, timeout=30.0)
        _open_tree_row_containing(self.tree, expected_name)
        selected_text = (editor_expected_name or expected_name).lower()
        try:
            wait_for(
                "selected visible client editor state",
                lambda: (
                    self.current_family_name()
                    if selected_text in self.current_family_name().lower()
                    else None
                ),
                timeout=10.0,
            )
        except AssertionError:
            _activate_first_visible_tree_row(self.tree)
            wait_for(
                "selected visible client editor state",
                lambda: (
                    self.current_family_name()
                    if selected_text in self.current_family_name().lower()
                    else None
                ),
                timeout=20.0,
            )

    def save_current(self, *, expected_text: str) -> None:
        save_button = child(
            self.main.window,
            auto_id="clientsSaveButton",
            timeout=10.0,
            visible_only=False,
        )
        _scroll_into_view(save_button)
        click(save_button)
        dialog = _wait_for_message_box_text(
            self.session,
            expected_texts=(expected_text, "saved"),
        )
        click_message_box_button(dialog, "OK", "Ok", "&OK")

    def open_import_wizard(self) -> None:
        click(child(self.main.window, auto_id="clientsImportButton"))

    def wait_for_tree_text(self, expected_text: str, *, timeout: float = 20.0) -> None:
        self.wait_for_tree_rows(expected_text=expected_text, timeout=timeout)

    def wait_for_tree_text_absent(self, expected_text: str, *, timeout: float = 20.0) -> None:
        expected = normalize_text(expected_text).lower()
        wait_for(
            f"absence of client tree text {expected_text!r}",
            lambda: True if expected not in _panel_text(self.tree) else None,
            timeout=timeout,
        )

    def demande_panel(self, panel_index: int = 1) -> UIAWrapper:
        """Return the compact request summary card in the Clients editor."""
        panel = child(
            self.main.window,
            auto_id=f"demandePanel_{int(panel_index)}",
            timeout=20.0,
            visible_only=True,
        )
        _scroll_into_view(panel)
        child(
            panel,
            auto_id=f"demandePanelEditButton_{int(panel_index)}",
            timeout=10.0,
        )
        return panel

    def first_demande_panel(self) -> UIAWrapper:
        return self.demande_panel(1)

    def _fill_open_demande_dialog(
        self,
        *,
        type_label: str | None = None,
        action_label: str | None = None,
        wilaya: str | None = None,
        location: str | None = None,
        beds_min: int | None = None,
        surface_min: int | None = None,
        surface_max: int | None = None,
        budget_min: int | None = None,
        budget_max: int | None = None,
        furnished_label: str | None = None,
        floor_min: int | None = None,
        floor_max: int | None = None,
        elevator: bool | None = None,
        accessibility_required: bool | None = None,
        tags: str | None = None,
        remarks: str | None = None,
    ) -> None:
        root = self.main.window
        child(root, auto_id="demandeWilayaInput", control_type="Edit", timeout=20.0)
        if type_label is not None:
            _set_combo_label(root, "demandeTypeCombo", type_label)
            if normalize_text(type_label).lower() == "apartment":
                child(root, auto_id="demandeFloorMinInput", timeout=15.0, visible_only=False)
        if action_label is not None:
            _set_combo_label(root, "demandeActionCombo", action_label)
        if wilaya is not None:
            _set_prefix_combo_value(
                root,
                combo_auto_id="demandeWilayaCombo",
                input_auto_id="demandeWilayaInput",
                value=wilaya,
            )
        if location is not None:
            _add_location_value(root, prefix="demandeLocations", value=location)
        if beds_min is not None:
            _set_spinbox_value(root, "demandeBedsMinInput", beds_min)
        if surface_min is not None:
            _set_spinbox_value(root, "demandeSurfaceMinInput", surface_min)
        if surface_max is not None:
            _set_spinbox_value(root, "demandeSurfaceMaxInput", surface_max)
        if budget_min is not None:
            _set_spinbox_value(root, "demandeBudgetMinInput", budget_min)
        if budget_max is not None:
            _set_spinbox_value(root, "demandeBudgetMaxInput", budget_max)
        if furnished_label is not None:
            _set_combo_label(root, "demandeFurnishedCombo", furnished_label)
        if floor_min is not None:
            _set_spinbox_value(root, "demandeFloorMinInput", floor_min)
        if floor_max is not None:
            _set_spinbox_value(root, "demandeFloorMaxInput", floor_max)
        if elevator is not None:
            _set_checkbox(root, "demandeElevatorCheck", elevator)
        if accessibility_required is not None:
            _set_checkbox(root, "demandeAccessibilityCheck", accessibility_required)
        if tags is not None:
            _set_field_text(root, "demandeTagsInput", tags)
        if remarks is not None:
            _set_field_text(root, "demandeRemarksInput", remarks)

    def add_demande(
        self,
        *,
        panel_index: int = 1,
        type_label: str,
        action_label: str,
        wilaya: str,
        location: str,
        beds_min: int | None = None,
        surface_min: int | None = None,
        surface_max: int | None = None,
        budget_min: int | None = None,
        budget_max: int | None = None,
        furnished_label: str = "Any",
        floor_min: int | None = 0,
        floor_max: int | None = 8,
        elevator: bool | None = False,
        accessibility_required: bool | None = False,
        tags: str = "",
        remarks: str = "",
    ) -> None:
        click(child(self.main.window, auto_id="clientsAddDemandeButton"))
        self._fill_open_demande_dialog(
            type_label=type_label,
            action_label=action_label,
            wilaya=wilaya,
            location=location,
            beds_min=beds_min,
            surface_min=surface_min,
            surface_max=surface_max,
            budget_min=budget_min,
            budget_max=budget_max,
            furnished_label=furnished_label,
            floor_min=floor_min,
            floor_max=floor_max,
            elevator=elevator,
            accessibility_required=accessibility_required,
            tags=tags,
            remarks=remarks,
        )
        click(child(self.main.window, auto_id="demandeRequestSaveButton", timeout=10.0))
        self.demande_panel(panel_index)

    def fill_first_demande(
        self,
        *,
        panel_index: int = 1,
        type_label: str | None = None,
        action_label: str | None = None,
        wilaya: str | None = None,
        location: str | None = None,
        beds_min: int | None = None,
        surface_min: int | None = None,
        surface_max: int | None = None,
        budget_min: int | None = None,
        budget_max: int | None = None,
        furnished_label: str | None = None,
        floor_min: int | None = None,
        floor_max: int | None = None,
        elevator: bool | None = None,
        accessibility_required: bool | None = None,
        tags: str | None = None,
        remarks: str | None = None,
    ) -> None:
        panel = self.demande_panel(panel_index)
        click(
            child(
                panel,
                auto_id=f"demandePanelEditButton_{int(panel_index)}",
                timeout=10.0,
            )
        )
        self._fill_open_demande_dialog(
            type_label=type_label,
            action_label=action_label,
            wilaya=wilaya,
            location=location,
            beds_min=beds_min,
            surface_min=surface_min,
            surface_max=surface_max,
            budget_min=budget_min,
            budget_max=budget_max,
            furnished_label=furnished_label,
            floor_min=floor_min,
            floor_max=floor_max,
            elevator=elevator,
            accessibility_required=accessibility_required,
            tags=tags,
            remarks=remarks,
        )
        click(child(self.main.window, auto_id="demandeRequestSaveButton", timeout=10.0))

    def delete_first_demande_panel(self) -> None:
        panel = self.first_demande_panel()
        click(child(panel, auto_id="demandePanelDeleteButton_1", timeout=10.0))
        _wait_for_control_absent(self.main.window, auto_id="demandePanel_1", timeout=20.0)


class ListingsPage:
    def __init__(self, main: MainWindowPage, session: DesktopSession) -> None:
        self.main = main
        self.session = session
        child(main.window, auto_id="listingOwnerNameInput", timeout=20.0)

    @property
    def tree(self) -> UIAWrapper:
        return child(self.main.window, title="Properties tree", control_type="Tree")

    def wait_for_tree_rows(
        self,
        *,
        expected_text: str | None = None,
        timeout: float = 20.0,
    ) -> UIAWrapper:
        normalized_expected = str(expected_text or "").strip().lower()

        def _matching_tree(tree: UIAWrapper) -> UIAWrapper | None:
            rows: list[UIAWrapper] = []
            for control_type in ("DataItem", "ListItem", "TreeItem"):
                rows.extend(_tree_descendants(tree, control_type))
            if not rows:
                return None
            if normalized_expected:
                row_text = " ".join(
                    str(getattr(row.element_info, "name", "") or "").strip().lower() for row in rows
                )
                if normalized_expected not in row_text:
                    return None
            return tree

        def _resolve() -> UIAWrapper | None:
            tree = self.tree
            matched = _matching_tree(tree)
            if matched is not None:
                return matched
            try:
                click(child(self.main.window, auto_id="listingsExpandAllButton", timeout=1.0))
            except Exception:
                return None
            return _matching_tree(self.tree)

        return wait_for("listing tree rows", _resolve, timeout=timeout)

    def current_owner_name(self) -> str:
        control = child(self.main.window, auto_id="listingOwnerNameInput")
        texts = [text for text in control.texts() if str(text or "").strip()]
        return str(texts[0] if texts else control.window_text() or "").strip()

    def current_phone(self) -> str:
        control = child(self.main.window, auto_id="listingPhoneInput")
        texts = [text for text in control.texts() if str(text or "").strip()]
        return str(texts[0] if texts else control.window_text() or "").strip()

    def create_listing(self, *, owner_name: str, phone: str, remarks: str = "") -> None:
        clear_and_type(child(self.main.window, auto_id="listingOwnerNameInput"), owner_name)
        clear_and_type(child(self.main.window, auto_id="listingPhoneInput"), phone)
        clear_and_type(child(self.main.window, auto_id="listingRemarksInput"), remarks)
        click(child(self.main.window, auto_id="listingsSaveButton"))
        dialog = self.session.message_box(timeout=10.0)
        wait_for_text(dialog, owner_name, timeout=10.0)
        click_message_box_button(dialog, "OK", "Ok", "&OK")

    def open_import_wizard(self) -> None:
        click(child(self.main.window, auto_id="listingsImportButton"))

    def open_first_listed_listing(self) -> None:
        tree = self.tree
        try:
            first_row = wait_for(
                "first listed listing row",
                lambda: next(
                    iter(
                        [
                            *_tree_descendants(tree, "DataItem"),
                            *_tree_descendants(tree, "ListItem"),
                            *_tree_descendants(tree, "TreeItem"),
                        ]
                    ),
                    None,
                ),
                timeout=5.0,
            )
            try:
                first_row.double_click_input()
                return
            except Exception:
                click(first_row)
                keyboard.send_keys("{ENTER}", pause=0.05)
                return
        except AssertionError:
            pass
        try:
            tree.set_focus()
        except Exception:
            pass
        try:
            click(tree)
        except Exception:
            pass
        keyboard.send_keys("{HOME}{DOWN}{ENTER}", pause=0.05)

    def select_existing(
        self,
        *,
        search_value: str,
        expected_name: str,
        editor_expected_name: str | None = None,
    ) -> None:
        clear_and_type_live(child(self.main.window, auto_id="listingsSearchInput"), search_value)
        try:
            self.wait_for_tree_rows(expected_text=expected_name, timeout=20.0)
        except AssertionError:
            click(child(self.main.window, auto_id="listingsExpandAllButton", timeout=10.0))
            self.wait_for_tree_rows(expected_text=expected_name, timeout=30.0)
        _open_tree_row_containing(self.tree, expected_name)
        selected_text = (editor_expected_name or expected_name).lower()
        try:
            wait_for(
                "selected listing editor state",
                lambda: (
                    self.current_owner_name()
                    if selected_text in self.current_owner_name().lower()
                    else None
                ),
                timeout=10.0,
            )
        except AssertionError:
            _activate_first_visible_tree_row(self.tree)
            wait_for(
                "selected listing editor state",
                lambda: (
                    self.current_owner_name()
                    if selected_text in self.current_owner_name().lower()
                    else None
                ),
                timeout=20.0,
            )

    def select_visible_existing(
        self,
        *,
        expected_name: str,
        editor_expected_name: str | None = None,
    ) -> None:
        clear_and_type_live(child(self.main.window, auto_id="listingsSearchInput"), "")
        self.wait_for_tree_rows(expected_text=expected_name, timeout=30.0)
        _open_tree_row_containing(self.tree, expected_name)
        selected_text = (editor_expected_name or expected_name).lower()
        try:
            wait_for(
                "selected visible listing editor state",
                lambda: (
                    self.current_owner_name()
                    if selected_text in self.current_owner_name().lower()
                    else None
                ),
                timeout=10.0,
            )
        except AssertionError:
            _activate_first_visible_tree_row(self.tree)
            wait_for(
                "selected visible listing editor state",
                lambda: (
                    self.current_owner_name()
                    if selected_text in self.current_owner_name().lower()
                    else None
                ),
                timeout=20.0,
            )

    def save_current(self, *, expected_text: str) -> None:
        save_button = child(
            self.main.window,
            auto_id="listingsSaveButton",
            timeout=10.0,
            visible_only=False,
        )
        _scroll_into_view(save_button)
        click(save_button)
        dialog = _wait_for_message_box_text(
            self.session,
            expected_texts=(expected_text, "saved"),
        )
        click_message_box_button(dialog, "OK", "Ok", "&OK")

    def wait_for_tree_text(self, expected_text: str, *, timeout: float = 20.0) -> None:
        self.wait_for_tree_rows(expected_text=expected_text, timeout=timeout)

    def wait_for_tree_text_absent(self, expected_text: str, *, timeout: float = 20.0) -> None:
        expected = normalize_text(expected_text).lower()
        wait_for(
            f"absence of listing tree text {expected_text!r}",
            lambda: True if expected not in _panel_text(self.tree) else None,
            timeout=timeout,
        )

    def offer_panel(self, panel_index: int = 1) -> UIAWrapper:
        panel_id = f"offerPanel_{int(panel_index)}"
        panel = child(self.main.window, auto_id=panel_id, timeout=20.0, visible_only=True)
        _scroll_into_view(panel)
        child(panel, auto_id="offerWilayaInput", control_type="Edit", timeout=10.0)
        return panel

    def first_offer_panel(self) -> UIAWrapper:
        return self.offer_panel(1)

    def add_offer(
        self,
        *,
        panel_index: int = 1,
        type_label: str,
        action_label: str,
        wilaya: str,
        location: str,
        beds: int | None = None,
        surface: int | None = None,
        budget: int | None = None,
        furnished_label: str = "Any",
        floor: int | None = None,
        elevator: bool | None = False,
        accessibility_supported: bool | None = False,
        price_negotiable: bool | None = False,
        price_flex_pct: int | None = None,
        link: str | None = None,
        latitude: str | None = None,
        longitude: str | None = None,
        remarks: str = "",
    ) -> None:
        click(child(self.main.window, auto_id="listingsAddOfferButton"))
        self.offer_panel(panel_index)
        self.fill_first_offer(
            panel_index=panel_index,
            type_label=type_label,
            action_label=action_label,
            wilaya=wilaya,
            location=location,
            beds=beds,
            surface=surface,
            budget=budget,
            furnished_label=furnished_label,
            floor=floor,
            elevator=elevator,
            accessibility_supported=accessibility_supported,
            price_negotiable=price_negotiable,
            price_flex_pct=price_flex_pct,
            link=link,
            latitude=latitude,
            longitude=longitude,
            remarks=remarks,
        )

    def fill_first_offer(
        self,
        *,
        panel_index: int = 1,
        type_label: str | None = None,
        action_label: str | None = None,
        wilaya: str | None = None,
        location: str | None = None,
        beds: int | None = None,
        surface: int | None = None,
        budget: int | None = None,
        furnished_label: str | None = None,
        floor: int | None = None,
        elevator: bool | None = None,
        accessibility_supported: bool | None = None,
        price_negotiable: bool | None = None,
        price_flex_pct: int | None = None,
        link: str | None = None,
        latitude: str | None = None,
        longitude: str | None = None,
        remarks: str | None = None,
    ) -> None:
        panel = self.offer_panel(panel_index)
        if type_label is not None:
            _set_combo_label(panel, "offerTypeCombo", type_label)
            if normalize_text(type_label).lower() == "apartment":
                child(panel, auto_id="offerFloorInput", timeout=15.0, visible_only=False)
        if action_label is not None:
            _set_combo_label(panel, "offerActionCombo", action_label)
        if wilaya is not None:
            _set_prefix_combo_value(
                panel,
                combo_auto_id="offerWilayaCombo",
                input_auto_id="offerWilayaInput",
                value=wilaya,
            )
        if location is not None:
            _add_location_value(panel, prefix="offerLocation", value=location)
        if beds is not None:
            _set_spinbox_value(panel, "offerBedsInput", beds)
        if surface is not None:
            _set_spinbox_value(panel, "offerSurfaceInput", surface)
        if budget is not None:
            _set_spinbox_value(panel, "offerBudgetInput", budget)
        if furnished_label is not None:
            _set_combo_label(panel, "offerFurnishedCombo", furnished_label)
        if floor is not None:
            _set_spinbox_value(panel, "offerFloorInput", floor)
        if elevator is not None:
            _set_checkbox(panel, "offerElevatorCheck", elevator)
        if accessibility_supported is not None:
            _set_checkbox(panel, "offerAccessibilityCheck", accessibility_supported)
        if price_negotiable is not None:
            _set_checkbox(panel, "offerPriceNegotiableCheck", price_negotiable)
        if price_flex_pct is not None:
            _set_field_text(panel, "offerPriceFlexInput", price_flex_pct)
        if link is not None:
            _set_field_text(panel, "offerLinkInput", link)
        if latitude is not None:
            _set_field_text(panel, "offerLatitudeInput", latitude)
        if longitude is not None:
            _set_field_text(panel, "offerLongitudeInput", longitude)
        if remarks is not None:
            _set_field_text(panel, "offerRemarksInput", remarks)

    def delete_first_offer_panel(self) -> None:
        panel = self.first_offer_panel()
        click(child(panel, auto_id="offerPanelDeleteButton_1", timeout=10.0))
        _wait_for_control_absent(self.main.window, auto_id="offerPanel_1", timeout=20.0)

    def offer_photo_section(self, offer_id: int) -> UIAWrapper:
        return child(
            self.main.window,
            auto_id=f"offerPhotosSection_{int(offer_id)}",
            timeout=20.0,
            visible_only=False,
        )

    def add_offer_photo(self, *, offer_id: int, file_path: Path) -> None:
        section = self.offer_photo_section(offer_id)
        add_button = child(
            section,
            auto_id=f"offerPhotosAddButton_{int(offer_id)}",
            control_type="Button",
            timeout=10.0,
            visible_only=False,
        )
        _scroll_into_view(add_button)
        click(add_button)
        open_dialog = self.session.window(title_re=".*Select Property Photo.*", timeout=15.0)
        choose_file(open_dialog, file_path)

    def wait_for_offer_photo_item(self, *, offer_id: int, photo_id: int) -> None:
        section = self.offer_photo_section(offer_id)
        child(
            section,
            auto_id=f"offerPhotoItem_{int(photo_id)}",
            timeout=30.0,
            visible_only=False,
        )

    def wait_for_offer_photo_thumbnail_loaded(self, *, offer_id: int, photo_id: int) -> None:
        section = self.offer_photo_section(offer_id)

        def _loaded() -> UIAWrapper | None:
            thumbnail = child(
                section,
                auto_id=f"offerPhotoThumbnail_{int(photo_id)}",
                timeout=1.0,
                visible_only=False,
            )
            text = " ".join(wrapper_texts(thumbnail)).lower()
            return thumbnail if "thumbnail loaded" in text else None

        wait_for(
            f"loaded owner-tab thumbnail for offer {int(offer_id)} photo {int(photo_id)}",
            _loaded,
            timeout=45.0,
        )

    def delete_offer_photo(self, *, offer_id: int, photo_id: int) -> None:
        section = self.offer_photo_section(offer_id)
        button = child(
            section,
            auto_id=f"offerPhotoDeleteButton_{int(photo_id)}",
            control_type="Button",
            timeout=10.0,
            visible_only=False,
        )
        _scroll_into_view(button)
        click(button)
        _wait_for_control_absent(section, auto_id=f"offerPhotoItem_{int(photo_id)}", timeout=20.0)

    def wait_for_offer_photo_status(
        self,
        *,
        offer_id: int,
        expected_text: str,
        timeout: float = 20.0,
    ) -> None:
        section = self.offer_photo_section(offer_id)
        status = child(
            section,
            auto_id=f"offerPhotosStatus_{int(offer_id)}",
            control_type="Text",
            timeout=10.0,
            visible_only=False,
        )
        wait_for_text(status, expected_text, timeout=timeout)

    def add_unsupported_offer_photo_expect_error(self, *, offer_id: int, file_path: Path) -> str:
        self.add_offer_photo(offer_id=offer_id, file_path=file_path)
        section = self.offer_photo_section(offer_id)
        status = child(
            section,
            auto_id=f"offerPhotosStatus_{int(offer_id)}",
            control_type="Text",
            timeout=10.0,
            visible_only=False,
        )
        expected = "Unsupported property photo format. Use PNG, JPG, JPEG, or BMP."
        wait_for_text(status, expected, timeout=20.0)
        text = " ".join(wrapper_texts(status))
        if expected not in text:
            raise AssertionError(f"Unexpected offer photo validation status: {text}")
        return text


class MatchPage:
    def __init__(self, main: MainWindowPage) -> None:
        self.main = main
        child(main.window, auto_id="matchRunButton", timeout=20.0)

    def select_client(self, client_name: str) -> None:
        client_combo = child(self.main.window, auto_id="matchClientSelect")
        combo_edit = wait_for(
            "match client combobox edit",
            lambda: child(client_combo, control_type="Edit", timeout=1.0),
            timeout=10.0,
        )

        def _selected_text() -> str:
            return normalize_text(combo_selected_text(client_combo)).lower()

        normalized_client = normalize_text(client_name).lower()

        def _has_selected_client() -> bool:
            text = _selected_text()
            return normalized_client in text and ("|" in text or text.startswith("["))

        try:
            wait_for(
                "selected match client already present",
                lambda: client_combo if _has_selected_client() else None,
                timeout=3.0,
            )
        except AssertionError:
            try:
                select_combo_popup_item_containing(client_combo, client_name)
            except AssertionError:
                clear_and_type_live(combo_edit, client_name)
                wait_for(
                    "match client search result",
                    lambda: client_combo if _has_selected_client() else None,
                    timeout=5.0,
                )
        if not _has_selected_client():
            select_combo_popup_item_containing(client_combo, client_name)
        wait_for(
            "selected match client",
            lambda: (
                client_combo
                if client_name.lower()
                in " ".join(
                    text
                    for text in (
                        combo_selected_text(client_combo),
                        combo_edit.window_text(),
                        " ".join(str(value or "").strip() for value in combo_edit.texts()),
                    )
                    if str(text or "").strip()
                ).lower()
                else None
            ),
            timeout=15.0,
        )

    def run_selected(self) -> None:
        click(child(self.main.window, auto_id="matchRunButton"))

    def wait_for_results(self) -> None:
        results_scroll = child(
            self.main.window,
            auto_id="matchResultsScrollArea",
            timeout=30.0,
            visible_only=False,
        )
        wait_for(
            "match results scroll area visible",
            lambda: results_scroll if results_scroll.is_visible() else None,
            timeout=30.0,
        )
        descendant_with_auto_id_prefix(
            self.main.window,
            prefix="matchDemandeSection_",
            timeout=30.0,
        )

    def wait_for_no_matching_listings(self) -> None:
        self.wait_for_results()
        wait_for_text(self.main.window, "No matching listings found", timeout=30.0)

    def wait_for_visible_match_text(self, expected_text: str) -> None:
        self.wait_for_results()
        wait_for_text(self.main.window, expected_text, timeout=30.0)

    def expand_all_match_sections(self) -> None:
        self.wait_for_results()
        headers = matching_descendants(
            self.main.window,
            control_type="Custom",
            visible_only=True,
        )
        for header in headers:
            auto_id = str(getattr(header.element_info, "automation_id", "") or "")
            if not auto_id.endswith(".collapsibleHeader"):
                continue
            if ">" not in wrapper_texts(header):
                continue
            _scroll_into_view(header)
            try:
                header.click_input()
            except Exception:
                try:
                    arrow = child(
                        header,
                        auto_id="collapsibleArrow",
                        title=">",
                        control_type="Text",
                        timeout=1.0,
                        visible_only=True,
                    )
                    arrow.click_input()
                except Exception:
                    click(header)

    def open_offer_photos_for_match(
        self,
        *,
        listing_id: int,
        offer_id: int,
        expected_photo_id: int,
    ) -> None:
        self.wait_for_results()
        button_auto_id = f"matchOfferPhotosButton_listing_{int(listing_id)}_offer_{int(offer_id)}"
        try:
            button = child(
                self.main.window,
                auto_id=button_auto_id,
                control_type="Button",
                timeout=5.0,
                visible_only=False,
            )
        except AssertionError:
            self.expand_all_match_sections()
            button = child(
                self.main.window,
                auto_id=button_auto_id,
                control_type="Button",
                timeout=20.0,
                visible_only=False,
            )
        _scroll_into_view(button)
        click(button)
        dialog = self.main.session.window(
            auto_id=f"matchOfferPhotosDialog_offer_{int(offer_id)}",
            timeout=20.0,
        )
        child(
            dialog,
            auto_id=f"matchOfferPhotoItem_{int(expected_photo_id)}",
            timeout=20.0,
            visible_only=False,
        )
        wait_for(
            f"loaded match thumbnail for offer {int(offer_id)} photo {int(expected_photo_id)}",
            lambda: (
                thumbnail
                if "thumbnail loaded"
                in " ".join(
                    wrapper_texts(
                        thumbnail := child(
                            dialog,
                            auto_id=f"matchOfferPhotoThumbnail_{int(expected_photo_id)}",
                            timeout=1.0,
                            visible_only=False,
                        )
                    )
                ).lower()
                else None
            ),
            timeout=45.0,
        )
        click(child(dialog, auto_id="matchOfferPhotosDialogCloseButton", timeout=10.0))

    def open_create_contract_for_visible_listing(
        self,
        expected_text: str,
        *,
        listing_id: int | None = None,
    ) -> ContractDialogPage:
        self.wait_for_visible_match_text(expected_text)
        self._scroll_actions_into_view()
        prefix = (
            f"matchCreateContractButton_listing_{int(listing_id)}_"
            if listing_id is not None
            else "matchCreateContractButton_"
        )
        button = descendant_with_auto_id_prefix(
            self.main.window,
            prefix=prefix,
            timeout=20.0,
        )
        click(button)
        return ContractDialogPage.wait(self.main.session)

    def _scroll_actions_into_view(self) -> None:
        tables = matching_descendants(
            self.main.window,
            auto_id="Match results table",
            control_type="Table",
            visible_only=False,
        )
        if not tables:
            return
        table = tables[0]
        try:
            vertical_percent = table.iface_scroll.CurrentVerticalScrollPercent
        except Exception:
            vertical_percent = -1
        for action in (
            lambda: table.iface_scroll.SetScrollPercent(100, vertical_percent),
            lambda: table.type_keys("{END}", set_foreground=True),
            lambda: keyboard.send_keys("{END}", pause=0.05),
        ):
            try:
                table.set_focus()
            except Exception:
                pass
            try:
                action()
                return
            except Exception:
                continue

    def run_for_client(self, client_name: str) -> None:
        self.select_client(client_name)
        self.run_selected()
        self.wait_for_results()


class ContractDialogPage:
    def __init__(self, dialog: UIAWrapper, session: DesktopSession) -> None:
        self.dialog = dialog
        self.session = session

    @classmethod
    def wait(cls, session: DesktopSession) -> ContractDialogPage:
        return cls(session.window(auto_id="contractDialog", timeout=20.0), session)

    def fill_and_save(
        self,
        *,
        amount: int | float,
        deposit: int | float,
        start_date: str,
        end_date: str | None = None,
        terms: str,
        notes: str,
    ) -> None:
        _set_spinbox_value(self.dialog, "contractAmountInput", amount)
        _set_spinbox_value(self.dialog, "contractDepositInput", deposit)
        _set_field_text(self.dialog, "contractStartDateInput", start_date)
        if end_date is not None:
            _set_field_text(self.dialog, "contractEndDateInput", end_date)
        _set_field_text(self.dialog, "contractTermsInput", terms)
        _set_field_text(self.dialog, "contractNotesInput", notes)
        click(child(self.dialog, auto_id="contractCreateButton", timeout=10.0))
        wait_for(
            "contract create dialog closed",
            lambda: (
                None if self.session.try_window(auto_id="contractDialog", timeout=0.5) else True
            ),
            timeout=20.0,
        )


class ContractEditDialogPage:
    def __init__(self, dialog: UIAWrapper, session: DesktopSession) -> None:
        self.dialog = dialog
        self.session = session

    @classmethod
    def wait(cls, session: DesktopSession) -> ContractEditDialogPage:
        return cls(session.window(auto_id="contractEditDialog", timeout=20.0), session)

    def fill_and_save(
        self,
        *,
        amount: int | float | None = None,
        deposit: int | float | None = None,
        start_date: str | None = None,
        end_date: str | None = None,
        terms: str | None = None,
        notes: str | None = None,
    ) -> None:
        if amount is not None:
            _set_spinbox_value(self.dialog, "contractEditAmountInput", amount)
        if deposit is not None:
            _set_spinbox_value(self.dialog, "contractEditDepositInput", deposit)
        if start_date is not None:
            _set_field_text(self.dialog, "contractEditStartDateInput", start_date)
        if end_date is not None:
            _set_field_text(self.dialog, "contractEditEndDateInput", end_date)
        if terms is not None:
            _set_field_text(self.dialog, "contractEditTermsInput", terms)
        if notes is not None:
            _set_field_text(self.dialog, "contractEditNotesInput", notes)
        click(child(self.dialog, auto_id="contractEditSaveButton", timeout=10.0))
        wait_for(
            "contract edit dialog closed",
            lambda: (
                None if self.session.try_window(auto_id="contractEditDialog", timeout=0.5) else True
            ),
            timeout=20.0,
        )


class ContractsPage:
    def __init__(self, main: MainWindowPage, session: DesktopSession) -> None:
        self.main = main
        self.session = session
        child(main.window, auto_id="contractsTable", timeout=20.0)

    @classmethod
    def open(cls, main: MainWindowPage, session: DesktopSession) -> ContractsPage:
        main.select_tab("crm")
        tabs = child(main.window, auto_id="crmFollowupTabs", timeout=20.0)
        select_tab_by_index(tabs, 1)
        child(main.window, auto_id="contractsTable", timeout=20.0)
        return cls(main, session)

    def wait_for_contract(
        self,
        *,
        contract_id: int,
        expected_text: str,
        status_text: str,
        timeout: float = 30.0,
    ) -> None:
        wait_for_text(self.main.window, str(int(contract_id)), timeout=timeout)
        wait_for_text(self.main.window, expected_text, timeout=timeout)
        wait_for_text(self.main.window, status_text, timeout=timeout)

    def wait_for_contract_absent(self, *, contract_id: int, timeout: float = 30.0) -> None:
        table = child(self.main.window, auto_id="contractsTable", timeout=20.0)
        wait_for_absent_text(table, str(int(contract_id)), timeout=timeout)

    def edit_details(
        self,
        contract_id: int,
        *,
        amount: int | float | None = None,
        deposit: int | float | None = None,
        start_date: str | None = None,
        end_date: str | None = None,
        terms: str | None = None,
        notes: str | None = None,
    ) -> None:
        click(child(self.main.window, auto_id=f"contractEditButton_{int(contract_id)}"))
        ContractEditDialogPage.wait(self.session).fill_and_save(
            amount=amount,
            deposit=deposit,
            start_date=start_date,
            end_date=end_date,
            terms=terms,
            notes=notes,
        )

    def print_contract(self, contract_id: int) -> None:
        click(child(self.main.window, auto_id=f"contractPrintButton_{int(contract_id)}"))

    def sign_contract(self, contract_id: int) -> None:
        click(child(self.main.window, auto_id=f"contractSignButton_{int(contract_id)}"))
        dialog = self.session.message_box(timeout=10.0)
        wait_for_text(dialog, "signed", timeout=10.0)
        click_message_box_button(dialog, "Yes", "&Yes", "Oui", "&Oui")

    def cancel_contract(self, contract_id: int) -> None:
        click(child(self.main.window, auto_id=f"contractCancelLifecycleButton_{int(contract_id)}"))
        dialog = self.session.message_box(timeout=10.0)
        wait_for_text(dialog, "Cancel", timeout=10.0)
        click_message_box_button(dialog, "Yes", "&Yes", "Oui", "&Oui")

    def delete_contract(self, contract_id: int) -> None:
        click(child(self.main.window, auto_id=f"contractDeleteButton_{int(contract_id)}"))
        dialog = self.session.message_box(timeout=10.0)
        wait_for_text(dialog, "Delete", timeout=10.0)
        click_message_box_button(dialog, "Yes", "&Yes", "Oui", "&Oui")


class ImportWizardPage:
    def __init__(self, dialog: UIAWrapper, session: DesktopSession) -> None:
        self.dialog = dialog
        self.session = session

    @classmethod
    def wait(cls, session: DesktopSession) -> ImportWizardPage:
        return cls(session.window(auto_id="immoImportDialog", timeout=20.0), session)

    def upload_file(self, file_path: Path) -> None:
        click(child(self.dialog, auto_id="importUploadChooseFileButton"))
        open_dialog = self.session.window(title_re=".*Select import file.*", timeout=15.0)
        choose_file(open_dialog, file_path)
        child(self.dialog, auto_id="importStepMapping", timeout=60.0)

    def continue_mapping(self) -> None:
        click(child(self.dialog, auto_id="importMappingContinueButton"))
        child(self.dialog, auto_id="importStepExecution", timeout=20.0)

    def wait_for_review(self) -> None:
        child(self.dialog, auto_id="importStepReview", timeout=60.0)

    def submit_review(
        self,
        *,
        action: str = "update_existing",
        candidate_hint: str | None = None,
        corrections: dict[str, str] | None = None,
    ) -> None:
        review = child(self.dialog, auto_id="importStepReview", timeout=60.0)
        group_table = child(review, auto_id="importReviewGroupTable")
        select_first_row(group_table)
        item_table = child(review, auto_id="importReviewItemTable")
        select_first_row(item_table)
        detail_scroll = child(
            review, auto_id="importReviewDetailScroll", timeout=20.0, visible_only=False
        )
        current_card = wait_for(
            "current import review card",
            lambda: (
                matching_descendants(
                    detail_scroll,
                    auto_id="ImportReviewCard",
                    control_type="Custom",
                    visible_only=False,
                )[-1]
                if matching_descendants(
                    detail_scroll,
                    auto_id="ImportReviewCard",
                    control_type="Custom",
                    visible_only=False,
                )
                else None
            ),
            timeout=20.0,
        )
        for field_name, value in dict(corrections or {}).items():
            clear_and_type(
                child(
                    current_card,
                    auto_id=f"importReviewField_{field_name}",
                    timeout=20.0,
                    visible_only=False,
                ),
                value,
            )
        action_combo = child(current_card, auto_id="importReviewActionCombo", timeout=20.0)
        normalized_action = str(action or "").strip().lower()
        action_label = {
            "create": "Add as new",
            "create_new": "Add as new",
            "update": "Use existing record",
            "update_existing": "Use existing record",
            "review": "Keep for later",
            "review_ambiguous": "Keep for later",
            "skip": "Do not import this line",
        }.get(normalized_action)
        if action_label is None:
            raise AssertionError(f"Unsupported import review action {action!r}")
        if normalized_action in {"create", "create_new"}:
            try:
                group_action_button = child(
                    review,
                    auto_id="importReviewGroupActionCreateButton",
                    timeout=5.0,
                )
            except AssertionError:
                group_action_button = None
            if group_action_button is not None and group_action_button.is_enabled():
                click(group_action_button)
            else:
                select_combo_item(action_combo, action_label)
        else:
            select_combo_item(action_combo, action_label)
        focus_anchor = child(
            current_card,
            auto_id="importReviewField_family_name",
            timeout=5.0,
            visible_only=False,
        )
        click(focus_anchor)
        if normalized_action in {"update", "update_existing"}:
            candidate_combo = child(
                current_card, auto_id="importReviewCandidateCombo", timeout=20.0
            )
            wait_for(
                "review candidate combobox enabled",
                lambda: candidate_combo if candidate_combo.is_enabled() else None,
                timeout=15.0,
            )
            if candidate_hint:
                select_combo_popup_item_containing(candidate_combo, candidate_hint)
            else:
                select_combo_index(candidate_combo, 1)
        click(child(review, auto_id="importReviewSubmitButton"))

    def wait_for_summary(self) -> None:
        summary = child(self.dialog, auto_id="importStepSummary", timeout=90.0)
        child(summary, auto_id="importSummaryFinishButton", timeout=20.0)

    def wait_for_summary_headline(self, expected_text: str) -> None:
        summary = child(self.dialog, auto_id="importStepSummary", timeout=90.0)
        wait_for_text(summary, expected_text, timeout=30.0)

    def finish(self) -> None:
        summary = child(self.dialog, auto_id="importStepSummary", timeout=20.0)
        click(child(summary, auto_id="importSummaryFinishButton"))
        wait_for(
            "import dialog close",
            lambda: (
                None if self.session.try_window(auto_id="immoImportDialog", timeout=0.3) else True
            ),
            timeout=20.0,
        )

    def wait_for_blocking_message(self, expected_text: str) -> None:
        mapping = child(self.dialog, auto_id="importStepMapping", timeout=30.0)
        wait_for_text(mapping, expected_text, timeout=30.0)

    def cancel_execution(self) -> str:
        def _resolve() -> str | None:
            try:
                summary = child(self.dialog, auto_id="importStepSummary", timeout=0.5)
                summary_text = " ".join(wrapper_texts(summary)).lower()
                if "cancelled" in summary_text:
                    return "summary"
            except AssertionError:
                pass

            try:
                execution = child(self.dialog, auto_id="importStepExecution", timeout=0.5)
            except AssertionError:
                return None

            execution_text = " ".join(wrapper_texts(execution)).lower()
            if (
                "cancelling your import" in execution_text
                or "cancellation requested" in execution_text
            ):
                return "execution"

            cancel_button = child(execution, auto_id="importExecutionCancelButton", timeout=0.5)
            if cancel_button.is_enabled():
                click(cancel_button)
            return None

        return str(
            wait_for(
                "cancel acknowledgement in import execution",
                _resolve,
                timeout=30.0,
            )
        )

    def close_execution(self) -> None:
        execution = child(self.dialog, auto_id="importStepExecution", timeout=20.0)
        click(child(execution, auto_id="importExecutionCloseButton"))
        wait_for(
            "import dialog close from execution step",
            lambda: (
                None if self.session.try_window(auto_id="immoImportDialog", timeout=0.3) else True
            ),
            timeout=20.0,
        )

    def wait_for_execution_status(self, expected_text: str) -> None:
        execution = child(self.dialog, auto_id="importStepExecution", timeout=20.0)
        wait_for_text(execution, expected_text, timeout=60.0)

    def wait_for_execution_status_absent(self, expected_text: str) -> None:
        execution = child(self.dialog, auto_id="importStepExecution", timeout=20.0)
        wait_for_absent_text(execution, expected_text, timeout=30.0)

    def wait_for_cancellation_transition(self) -> str:
        def _resolve() -> str | None:
            for step_id, label in (
                ("importStepSummary", "summary"),
                ("importStepExecution", "execution"),
            ):
                try:
                    child(self.dialog, auto_id=step_id, timeout=0.5)
                    return label
                except AssertionError:
                    continue
            return None

        return str(
            wait_for(
                "import cancellation transition",
                _resolve,
                timeout=30.0,
            )
        )


def login_to_main_window(
    session: DesktopSession,
    *,
    username: str,
    password: str,
    base_url: str,
) -> MainWindowPage:
    def _resolve() -> MainWindowPage | None:
        main = session.try_window(auto_id="immoMainWindow", timeout=0.5)
        if main is not None:
            return MainWindowPage(main, session)

        setup = session.try_window(auto_id="immoSetupWizardDialog", timeout=0.5)
        if setup is not None:
            raise AssertionError(
                "Unexpected setup wizard during a preseeded desktop E2E run. "
                "Setup wizard coverage must use the verified Caddy front-door fixture, "
                "not the direct backend E2E base URL."
            )

        quick_start = session.try_window(title_re=".*Get started.*", timeout=0.5)
        if quick_start is not None:
            QuickStartPage(quick_start).choose_sign_in()
            return None

        login = session.try_window(auto_id="immoLoginDialog", timeout=0.5)
        if login is not None:
            LoginPage(login).sign_in(username=username, password=password, base_url=base_url)
            return MainWindowPage.wait(session)

        return None

    return cast(MainWindowPage, wait_for("desktop login or main window", _resolve, timeout=60.0))
