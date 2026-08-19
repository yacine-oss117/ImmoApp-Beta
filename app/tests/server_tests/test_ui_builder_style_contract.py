from __future__ import annotations

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]

TARGET_BUILDERS: tuple[str, ...] = (
    "app/views/clients_v2_ui.py",
    "app/views/listings_v2_ui.py",
    "app/widgets/demande_form_ui.py",
    "app/widgets/offer_form_ui.py",
    "app/views/match_ui.py",
    "app/views/dashboard_ui.py",
    "app/views/crm_visits.py",
    "app/views/crm_contracts.py",
    "app/views/tree_view_helpers.py",
    "app/views/table_popups.py",
)

TARGET_DIALOGS: tuple[str, ...] = (
    "app/widgets/login_dialog_ui.py",
    "app/views/dialogs/visit_dialog.py",
    "app/views/dialogs/contract_dialog.py",
    "app/views/dialogs/contract_edit_dialog.py",
    "app/widgets/demande_edit_dialog_v2.py",
    "app/widgets/offer_edit_dialog.py",
    "app/views/imports/wizard_dialog.py",
    "app/views/imports/step_mapping.py",
    "app/views/imports/step_execution.py",
    "app/views/imports/step_summary.py",
    "app/views/imports/step_upload.py",
    "app/widgets/splash_startup.py",
    "app/views/dialogs/agency_settings_ui.py",
    "app/views/dialogs/contract_builder_article.py",
    "app/views/dialogs/contract_builder_dialog.py",
    "app/views/dialogs/contract_builder_ui.py",
    "app/views/dialogs/simulation_dialog_ui.py",
    "app/views/dialogs/wa_templates_ui.py",
)

TARGET_HIGH_TRAFFIC_WIDGETS: tuple[str, ...] = (
    "app/widgets/location_chip.py",
    "app/widgets/location_multi_select.py",
)

FORBIDDEN_SNIPPETS: tuple[str, ...] = (
    "setStyleSheet(",
    "setMaximumHeight(28",
    "setMaximumHeight(32",
    'setProperty("class"',
)

MIGRATED_THEME_FILES: tuple[str, ...] = (
    "app/views/tree_view_helpers.py",
    "app/views/table_popups.py",
    "app/views/dialogs/agency_settings_ui.py",
    "app/views/dialogs/contract_builder_article.py",
    "app/views/dialogs/contract_builder_dialog.py",
    "app/views/dialogs/contract_builder_ui.py",
    "app/views/dialogs/contract_edit_dialog.py",
    "app/views/dialogs/simulation_dialog_ui.py",
    "app/views/dialogs/wa_templates_ui.py",
)

MIGRATED_COMPACT_FILES: tuple[str, ...] = (
    "app/widgets/demande_form_ui.py",
    "app/widgets/offer_form_ui.py",
    "app/views/clients_v2_ui.py",
    "app/views/listings_v2_ui.py",
    "app/views/match_ui.py",
    "app/views/crm_visits.py",
    "app/views/crm_contracts.py",
)


def _read(path: str) -> str:
    return (REPO_ROOT / path).read_text(encoding="utf-8")


def test_builder_files_avoid_inline_styles_and_compact_height_hacks() -> None:
    violations: list[str] = []
    for rel in TARGET_BUILDERS:
        content = _read(rel)
        for snippet in FORBIDDEN_SNIPPETS:
            if snippet in content:
                violations.append(f"{rel}: contains forbidden snippet {snippet!r}")
    assert not violations, "\n".join(violations)


def test_key_dialog_files_avoid_inline_styles_and_legacy_class_properties() -> None:
    violations: list[str] = []
    for rel in TARGET_DIALOGS:
        content = _read(rel)
        for snippet in FORBIDDEN_SNIPPETS:
            if snippet in content:
                violations.append(f"{rel}: contains forbidden snippet {snippet!r}")
    assert not violations, "\n".join(violations)


def test_high_traffic_widget_files_avoid_inline_styles() -> None:
    violations: list[str] = []
    for rel in TARGET_HIGH_TRAFFIC_WIDGETS:
        content = _read(rel)
        for snippet in FORBIDDEN_SNIPPETS:
            if snippet in content:
                violations.append(f"{rel}: contains forbidden snippet {snippet!r}")
    assert not violations, "\n".join(violations)


def test_builder_files_use_variant_properties_for_actions() -> None:
    expected_variant_files = {
        "app/views/clients_v2_ui.py",
        "app/views/listings_v2_ui.py",
        "app/widgets/offer_form_ui.py",
        "app/views/match_ui.py",
        "app/views/dashboard_ui.py",
        "app/views/crm_visits.py",
        "app/views/crm_contracts.py",
    }
    missing: list[str] = []
    for rel in expected_variant_files:
        content = _read(rel)
        if 'setProperty("immoVariant"' not in content:
            missing.append(rel)
    assert not missing, f"Missing immoVariant usage in: {', '.join(missing)}"


def test_theme_qss_avoids_css_class_selectors_for_button_variants() -> None:
    qss = _read("app/ui/theme_qss.py")
    forbidden_selectors = ("QPushButton.primary-btn", "QPushButton.secondary-btn")
    for selector in forbidden_selectors:
        assert selector not in qss, f"Legacy selector still present: {selector}"


def test_migrated_theme_files_do_not_import_legacy_styles_module() -> None:
    violations: list[str] = []
    for rel in MIGRATED_THEME_FILES:
        content = _read(rel)
        if "app.utils.styles" in content:
            violations.append(f"{rel}: imports legacy app.utils.styles module")
    assert not violations, "\n".join(violations)


def test_compact_migrated_files_avoid_large_hardcoded_min_heights() -> None:
    forbidden = ("setMinimumHeight(38", "setMinimumHeight(40")
    violations: list[str] = []
    for rel in MIGRATED_COMPACT_FILES:
        content = _read(rel)
        for snippet in forbidden:
            if snippet in content:
                violations.append(f"{rel}: contains forbidden snippet {snippet!r}")
    assert not violations, "\n".join(violations)
