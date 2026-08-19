"""Runtime schema cutover parity cleanup for existing databases.

Revision ID: 20260220_0015
Revises: 20260219_0014
Create Date: 2026-02-20
"""

from __future__ import annotations

from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path
from types import ModuleType

revision = "20260220_0015"
down_revision = "20260219_0014"
branch_labels = None
depends_on = None


def _baseline() -> ModuleType:
    baseline_path = Path(__file__).with_name("20260204_0001_baseline.py")
    spec = spec_from_file_location("immoapp_alembic_20260204_0001", baseline_path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Could not load baseline migration module from {baseline_path}")
    module = module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def upgrade() -> None:
    baseline = _baseline()
    baseline._create_extensions()
    baseline._create_tables()
    baseline._create_search_functions()
    baseline._create_guard_triggers()
    baseline._apply_acl_defaults()
    baseline._apply_tenant_isolation()
    baseline._create_special_tenant_indexes()
    baseline._seed_meta_defaults()


def downgrade() -> None:
    # Cutover cleanup is intentionally restore-based.
    return None
