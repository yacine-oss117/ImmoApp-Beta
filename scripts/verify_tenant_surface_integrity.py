"""Verify repo-wide tenant surface classification and enforcement coverage."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from server.pg import schema_tenant_constants, tenant_surface_audit


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--json",
        action="store_true",
        help="Emit JSON only.",
    )
    args = parser.parse_args()

    audit = tenant_surface_audit.audit_tenant_surfaces()
    overlaps = {
        "tenant_vs_global": sorted(set(audit.tenant_owned).intersection(audit.global_system)),
        "tenant_vs_special": sorted(
            set(audit.tenant_owned).intersection(audit.special_polymorphic)
        ),
        "global_vs_special": sorted(
            set(audit.global_system).intersection(audit.special_polymorphic)
        ),
    }
    null_ok_outside_tenant = sorted(
        set(schema_tenant_constants.TENANT_TABLES_NULL_OK).difference(audit.tenant_owned)
    )
    ok = not any(overlaps.values()) and not null_ok_outside_tenant
    payload = {
        "ok": ok,
        "classification_version": audit.classification_version,
        "tenant_owned_count": len(audit.tenant_owned),
        "global_system_count": len(audit.global_system),
        "special_polymorphic_count": len(audit.special_polymorphic),
        "client_local_store_count": len(audit.client_local_stores),
        "tenant_owned": sorted(audit.tenant_owned),
        "global_system": sorted(audit.global_system),
        "special_polymorphic": sorted(audit.special_polymorphic),
        "client_local_stores": sorted(audit.client_local_stores),
        "overlaps": overlaps,
        "null_ok_outside_tenant": null_ok_outside_tenant,
    }
    if args.json:
        print(json.dumps(payload, indent=2, sort_keys=True))
    else:
        print(f"tenant surface classification version: {audit.classification_version}")
        print(f"tenant-owned tables: {len(audit.tenant_owned)}")
        print(f"global-system tables: {len(audit.global_system)}")
        print(f"special-polymorphic tables: {len(audit.special_polymorphic)}")
        print(f"client-local stores: {len(audit.client_local_stores)}")
        if ok:
            print("tenant surface classification: OK")
        else:
            print("tenant surface classification: FAILED")
            print(json.dumps(payload, indent=2, sort_keys=True))
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
