from __future__ import annotations

import ast
from pathlib import Path

_ROOT = Path("server")
_IMMO_ROOT = _ROOT / "immoapp_server"
_DELETED_SINK = _IMMO_ROOT / "business_metrics.py"
_CORE = _IMMO_ROOT / "business_metrics_core.py"
_GOVERNANCE = _IMMO_ROOT / "business_metrics_governance.py"
_IMPORTS = _IMMO_ROOT / "business_metrics_imports.py"
_MATCH = _IMMO_ROOT / "business_metrics_match.py"
_RUNTIME = _IMMO_ROOT / "business_metrics_runtime.py"


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _module(path: Path) -> ast.Module:
    return ast.parse(_read(path))


def _functions(path: Path) -> set[str]:
    return {node.name for node in _module(path).body if isinstance(node, ast.FunctionDef)}


def _public_functions(path: Path) -> set[str]:
    return {name for name in _functions(path) if not name.startswith("_")}


def _classes(path: Path) -> set[str]:
    return {node.name for node in _module(path).body if isinstance(node, ast.ClassDef)}


def _imports(path: Path) -> set[str]:
    modules: set[str] = set()
    for node in ast.walk(_module(path)):
        if isinstance(node, ast.Import):
            for alias in node.names:
                modules.add(alias.name)
        elif isinstance(node, ast.ImportFrom) and node.module:
            modules.add(node.module)
    return modules


def _imports_deleted_sink(path: Path) -> bool:
    for node in ast.walk(_module(path)):
        if isinstance(node, ast.Import):
            if any(alias.name == "server.immoapp_server.business_metrics" for alias in node.names):
                return True
        elif isinstance(node, ast.ImportFrom):
            if node.module == "server.immoapp_server.business_metrics":
                return True
            if node.module == "server.immoapp_server" and any(
                alias.name == "business_metrics" for alias in node.names
            ):
                return True
    return False


def test_business_metrics_sink_stays_deleted() -> None:
    assert not _DELETED_SINK.exists()


def test_business_metrics_core_stays_core_only() -> None:
    assert _classes(_CORE) == {"_NoopCounter", "_NoopHistogram"}
    assert _functions(_CORE) == {
        "_meter",
        "_counter",
        "_histogram",
        "_histogram_ms",
        "_observable_gauge",
    }
    assert "record_" not in _read(_CORE)


def test_business_metrics_import_owner_stays_import_only() -> None:
    assert _public_functions(_IMPORTS) == {
        "record_import_execution",
        "record_import_execution_budget_decision",
        "record_import_execution_profile",
        "record_import_status_signal",
    }
    text = _read(_IMPORTS)
    imports = _imports(_IMPORTS)
    assert "server.immoapp_server.business_metrics_governance" in imports
    assert "server.immoapp_server.business_metrics_runtime" not in imports
    assert "record_match_" not in text
    assert "record_http_request_latency" not in text
    assert "record_queue_saturation" not in text
    assert "record_tenant_usage_gauge" not in text


def test_business_metrics_match_owner_stays_match_and_cache_only() -> None:
    assert _public_functions(_MATCH) == {
        "read_match_artifact_timeout_counters",
        "record_cache_event",
        "record_cache_fill_latency",
        "record_cache_payload_bytes",
        "record_cache_pressure",
        "record_match_artifact_pipeline",
        "record_match_artifact_timeout",
        "record_match_cache_lookup",
        "record_match_pair_rebuild",
        "record_match_runtime_profile_state",
        "record_match_runtime_profile_transition",
    }
    text = _read(_MATCH)
    assert "record_import_" not in text
    assert "record_http_request_latency" not in text
    assert "record_queue_saturation" not in text
    assert "record_tenant_usage_gauge" not in text


def test_business_metrics_governance_owner_stays_queue_budget_and_usage_only() -> None:
    assert _public_functions(_GOVERNANCE) == {
        "record_queue_saturation",
        "record_tenant_budget_event",
        "record_tenant_usage_gauge",
    }
    text = _read(_GOVERNANCE)
    assert "record_import_" not in text
    assert "record_match_" not in text
    assert "record_http_request_latency" not in text


def test_business_metrics_runtime_owner_stays_runtime_only() -> None:
    assert _public_functions(_RUNTIME) == {"record_http_request_latency"}
    text = _read(_RUNTIME)
    assert "record_import_" not in text
    assert "record_match_" not in text
    assert "read_match_artifact_timeout_counters" not in text
    assert "record_queue_saturation" not in text
    assert "record_tenant_budget_event" not in text
    assert "record_tenant_usage_gauge" not in text


def test_only_domain_metric_owners_import_metrics_core() -> None:
    direct_core_importers = {
        str(path).replace("\\", "/")
        for path in _IMMO_ROOT.glob("*.py")
        if "server.immoapp_server.business_metrics_core" in _read(path)
    }
    assert direct_core_importers == {
        "server/immoapp_server/business_metrics_governance.py",
        "server/immoapp_server/business_metrics_imports.py",
        "server/immoapp_server/business_metrics_match.py",
        "server/immoapp_server/business_metrics_runtime.py",
    }


def test_production_modules_import_domain_metric_owners_directly() -> None:
    expected = {
        "server/api/views_import_execute.py": {"server.immoapp_server.business_metrics_imports"},
        "server/api/views_import_preview.py": {"server.immoapp_server.business_metrics_imports"},
        "server/api/tasks_maintenance.py": {"server.immoapp_server.business_metrics_imports"},
        "server/services/import_execution_metrics.py": {
            "server.immoapp_server.business_metrics_imports"
        },
        "server/api/match_pairs_compute.py": {"server.immoapp_server.business_metrics_match"},
        "server/services/cache_layers.py": {"server.immoapp_server.business_metrics_match"},
        "server/services/match_cache.py": {"server.immoapp_server.business_metrics_match"},
        "server/services/match_runtime_profile.py": {
            "server.immoapp_server.business_metrics_match"
        },
        "server/api/secured_view.py": {"server.immoapp_server.business_metrics_runtime"},
        "server/services/tenant_resource_governor.py": {
            "server.immoapp_server.business_metrics_governance"
        },
        "server/services/tenant_usage_gauge.py": {
            "server.immoapp_server.business_metrics_governance"
        },
        "server/api/views_cache_tasks.py": {
            "server.immoapp_server.business_metrics_governance",
            "server.immoapp_server.business_metrics_match",
        },
    }
    for rel_path, required_modules in expected.items():
        path = Path(rel_path)
        imports = _imports(path)
        assert required_modules.issubset(imports), rel_path
        assert not _imports_deleted_sink(path)


def test_no_production_module_imports_governance_metrics_from_runtime_owner() -> None:
    assert "server.immoapp_server.business_metrics_runtime" not in _imports(_IMPORTS)
    assert "server.immoapp_server.business_metrics_runtime" not in _imports(
        Path("server/services/tenant_resource_governor.py")
    )
    assert "server.immoapp_server.business_metrics_runtime" not in _imports(
        Path("server/services/tenant_usage_gauge.py")
    )
    assert "server.immoapp_server.business_metrics_runtime" not in _imports(
        Path("server/api/views_cache_tasks.py")
    )


def test_no_production_module_imports_deleted_business_metrics_sink() -> None:
    offenders: list[str] = []
    for base in (_ROOT / "api", _ROOT / "services", _IMMO_ROOT):
        for path in base.rglob("*.py"):
            if _imports_deleted_sink(path):
                offenders.append(str(path).replace("\\", "/"))
    assert offenders == []
