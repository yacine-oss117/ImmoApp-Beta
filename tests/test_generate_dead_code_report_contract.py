from __future__ import annotations

import importlib.util
from pathlib import Path
from types import ModuleType

REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT_PATH = REPO_ROOT / "scripts" / "generate_dead_code_report.py"


def _load_dead_code_report_module() -> ModuleType:
    spec = importlib.util.spec_from_file_location("dead_code_report_contract", SCRIPT_PATH)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_dead_code_report_keeps_dynamic_and_contract_modules() -> None:
    module = _load_dead_code_report_module()
    candidates = {name: path for name, path in module.collect_dead_code_candidates()}

    assert "app.ui.ui_copy_contract" not in candidates
    assert "server.alembic.env" not in candidates
    assert "server.alembic.versions.20260204_0001_baseline" not in candidates
    assert "server.pg.schema_authority_registry" not in candidates
    assert "server.pg.tenant_surface_audit" not in candidates
    assert "server.services.import_trace_snapshot" not in candidates


def test_dead_code_report_candidates_stay_within_candidate_roots() -> None:
    module = _load_dead_code_report_module()

    for _name, path in module.collect_dead_code_candidates():
        rel = path.relative_to(module.ROOT)
        assert rel.parts[0] in {"app", "server", "core"}
