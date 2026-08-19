from __future__ import annotations

from contextlib import contextmanager

import pytest

from server.pg.migrations import migrate_default_agency as module
from server.pg.tenant_fk_hardening import TenantIntegrityReport


def _report(*, ok: bool = True) -> TenantIntegrityReport:
    return TenantIntegrityReport(generated_at="2026-03-20T00:00:00+00:00", ok=ok, findings=[])


class _FakeSession:
    pass


class _FakeAdminTx:
    def __init__(self) -> None:
        self.entered = 0
        self.committed = 0
        self.rolled_back = 0
        self.session = _FakeSession()

    @contextmanager
    def context(self):
        self.entered += 1
        try:
            yield self.session
        except Exception:
            self.rolled_back += 1
            raise
        else:
            self.committed += 1


def _patch_common(monkeypatch: pytest.MonkeyPatch, fake_tx: _FakeAdminTx) -> None:
    monkeypatch.setattr(module, "admin_transaction", lambda: fake_tx.context())
    monkeypatch.setattr(module, "_require_accounts_tables", lambda _session: None)
    monkeypatch.setattr(module, "audit_tenant_integrity", lambda _session: _report(ok=True))
    monkeypatch.setattr(module, "repair_tenant_integrity", lambda _session: _report(ok=True))
    monkeypatch.setattr(module, "assert_report_ok", lambda report: None)
    monkeypatch.setattr(
        module,
        "_null_agency_counts",
        lambda _session, tables: {str(table): 0 for table in tables},
    )


def test_default_agency_bootstrap_uses_single_admin_transaction(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake_tx = _FakeAdminTx()
    _patch_common(monkeypatch, fake_tx)
    monkeypatch.setattr(module, "_agency_count", lambda _session: 1)
    monkeypatch.setattr(module, "_first_agency", lambda _session: (7, "SOLE"))
    monkeypatch.setattr(module, "_adopt_manager_if_needed", lambda _session, agency_id: None)
    monkeypatch.setattr(
        module,
        "_backfill_root_rows",
        lambda _session, agency_id: {"clients": 0, "listings": 0},
    )
    monkeypatch.setattr(
        module,
        "_backfill_bootstrap_metadata_rows",
        lambda _session, agency_id: {key: 0 for key in module._BOOTSTRAP_METADATA_TABLES},
    )

    report = module.migrate_to_default_agency()

    assert fake_tx.entered == 1
    assert fake_tx.committed == 1
    assert fake_tx.rolled_back == 0
    assert report.mode == "noop"


def test_default_agency_bootstrap_creates_default_when_no_agencies_exist(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake_tx = _FakeAdminTx()
    _patch_common(monkeypatch, fake_tx)
    monkeypatch.setattr(module, "_agency_count", lambda _session: 0)
    monkeypatch.setattr(module, "_create_default_agency", lambda _session: (10, "DEFAULT"))
    monkeypatch.setattr(module, "_adopt_manager_if_needed", lambda _session, agency_id: 22)
    monkeypatch.setattr(
        module,
        "_backfill_root_rows",
        lambda _session, agency_id: {"clients": 3, "listings": 4},
    )
    monkeypatch.setattr(
        module,
        "_backfill_bootstrap_metadata_rows",
        lambda _session, agency_id: {
            "custom_locations": 1,
            "wa_templates": 0,
            "agency_settings": 2,
            "audit_logs": 0,
        },
    )

    report = module.migrate_to_default_agency()

    assert report.mode == "applied"
    assert report.target_agency_id == 10
    assert report.target_agency_code == "DEFAULT"
    assert report.created_default_agency is True
    assert report.adopted_manager_user_id == 22
    assert report.root_backfill_counts == {"clients": 3, "listings": 4}


def test_default_agency_bootstrap_uses_existing_sole_agency(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake_tx = _FakeAdminTx()
    _patch_common(monkeypatch, fake_tx)
    monkeypatch.setattr(module, "_agency_count", lambda _session: 1)
    monkeypatch.setattr(module, "_first_agency", lambda _session: (7, "SOLE"))
    monkeypatch.setattr(
        module,
        "_create_default_agency",
        lambda _session: (_ for _ in ()).throw(AssertionError("must not create default agency")),
    )
    monkeypatch.setattr(module, "_adopt_manager_if_needed", lambda _session, agency_id: None)
    monkeypatch.setattr(
        module,
        "_backfill_root_rows",
        lambda _session, agency_id: {"clients": 2, "listings": 1},
    )
    monkeypatch.setattr(
        module,
        "_backfill_bootstrap_metadata_rows",
        lambda _session, agency_id: {key: 0 for key in module._BOOTSTRAP_METADATA_TABLES},
    )

    report = module.migrate_to_default_agency()

    assert report.target_agency_id == 7
    assert report.target_agency_code == "SOLE"
    assert report.created_default_agency is False
    assert report.mode == "applied"


def test_default_agency_bootstrap_aborts_on_multi_agency_null_root_rows(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake_tx = _FakeAdminTx()
    _patch_common(monkeypatch, fake_tx)
    monkeypatch.setattr(module, "_agency_count", lambda _session: 2)

    def _null_counts(_session, tables: tuple[str, ...]) -> dict[str, int]:
        return {str(table): (1 if str(table) == "clients" else 0) for table in tables}

    monkeypatch.setattr(module, "_null_agency_counts", _null_counts)

    with pytest.raises(RuntimeError, match="multiple agencies exist"):
        module.migrate_to_default_agency()

    assert fake_tx.committed == 0
    assert fake_tx.rolled_back == 1


def test_default_agency_bootstrap_rolls_back_when_post_verify_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake_tx = _FakeAdminTx()
    _patch_common(monkeypatch, fake_tx)
    monkeypatch.setattr(module, "_agency_count", lambda _session: 1)
    monkeypatch.setattr(module, "_first_agency", lambda _session: (7, "SOLE"))
    monkeypatch.setattr(module, "_adopt_manager_if_needed", lambda _session, agency_id: None)
    monkeypatch.setattr(
        module,
        "_backfill_root_rows",
        lambda _session, agency_id: {"clients": 1, "listings": 0},
    )
    monkeypatch.setattr(
        module,
        "_backfill_bootstrap_metadata_rows",
        lambda _session, agency_id: {key: 0 for key in module._BOOTSTRAP_METADATA_TABLES},
    )
    monkeypatch.setattr(module, "repair_tenant_integrity", lambda _session: _report(ok=False))
    monkeypatch.setattr(
        module,
        "assert_report_ok",
        lambda report: (_ for _ in ()).throw(RuntimeError("tenant_fk_integrity: issues found")),
    )

    with pytest.raises(RuntimeError, match="tenant_fk_integrity"):
        module.migrate_to_default_agency()

    assert fake_tx.committed == 0
    assert fake_tx.rolled_back == 1
