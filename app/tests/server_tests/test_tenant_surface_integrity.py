from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

from server.pg import schema_tenant_constants, tenant_surface_audit


def test_tenant_surface_manifest_has_no_cross_category_overlap() -> None:
    tenant_owned = set(schema_tenant_constants.TENANT_OWNED_TABLES)
    global_system = set(schema_tenant_constants.GLOBAL_SYSTEM_TABLES)
    special = set(schema_tenant_constants.SPECIAL_POLYMORPHIC_TABLES)

    assert tenant_owned.isdisjoint(global_system)
    assert tenant_owned.isdisjoint(special)
    assert global_system.isdisjoint(special)
    assert "record_acl" in special
    assert "record_acl" not in tenant_owned


def test_tenant_surface_audit_matches_manifest_version() -> None:
    audit = tenant_surface_audit.audit_tenant_surfaces()

    assert (
        audit.classification_version
        == schema_tenant_constants.tenant_surface_classification_version()
    )
    assert len(audit.client_local_stores) == len(schema_tenant_constants.CLIENT_LOCAL_STORES)
    assert "offline_sync_op_log" in audit.client_local_stores
    assert "upload_queue" in audit.client_local_stores


def test_tenant_surface_verifier_reports_ok_json() -> None:
    repo_root = Path(__file__).resolve().parents[3]
    output = subprocess.check_output(
        [sys.executable, "scripts/verify_tenant_surface_integrity.py", "--json"],
        cwd=repo_root,
        text=True,
    )
    payload = json.loads(output)

    assert payload["ok"] is True
    assert payload["tenant_owned_count"] >= 1
    assert payload["client_local_store_count"] >= 1
    assert payload["overlaps"] == {
        "global_vs_special": [],
        "tenant_vs_global": [],
        "tenant_vs_special": [],
    }
    assert payload["null_ok_outside_tenant"] == []
