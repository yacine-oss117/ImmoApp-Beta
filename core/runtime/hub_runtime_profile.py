"""Central Hub runtime capacity detection and safety limits."""

from __future__ import annotations

import hashlib
import json
import math
import os
import subprocess
from dataclasses import asdict, dataclass, field, replace
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Mapping

from core.env_flags import EnvBoolError, parse_bool_env_value
from core.paths import config_path

try:  # pragma: no cover - dependency is optional in narrow script contexts
    import psutil
except Exception:  # pragma: no cover
    psutil = None

PROFILE_ORDER = ("tiny", "small", "medium", "large")
EXPLICIT_PROFILES = PROFILE_ORDER + ("developer",)
PROFILE_INPUT_NAMES = EXPLICIT_PROFILES + ("custom",)
PROFILE_RANK = {name: index for index, name in enumerate(PROFILE_ORDER)}
PROFILE_PATH_NAME = "hub_runtime_profile.json"
PROFILE_SCHEMA_VERSION = 2

PROFILE_SOURCE_AUTO = "auto"
PROFILE_SOURCE_ENV_OVERRIDE = "env_override"
PROFILE_SOURCE_PERSISTED = "persisted_config"
PROFILE_SOURCE_PINNED = "pinned"
PROFILE_SOURCE_CUSTOM = "custom"

DETECTION_SOURCE_HOST = "host_capacity"
DETECTION_SOURCE_CONTAINER = "container_limits"
DETECTION_SOURCE_OVERRIDE = "env_override"

PRESSURE_GREEN = "green"
PRESSURE_YELLOW = "yellow"
PRESSURE_RED = "red"
RAW_FREE_RAM_DIAGNOSTICS_ONLY = True
PROFILE_EXPORT_MODE_ENV = "IMMOAPP_HUB_PROFILE_EXPORT_MODE"
PROFILE_EXPORT_MODE_RESOLVED = "resolved_startup_exports"

_BYTES_PER_GB = 1024**3
_BYTES_PER_MB = 1024**2
_MEMORY_OVERRIDE_TOLERANCE_BYTES = 64 * _BYTES_PER_MB
_UNREALISTIC_CGROUP_MEMORY_LIMIT = 1 << 60
_RED_MEMORY_STREAK_REQUIRED = 3
_RED_MEMORY_STREAK = 0

_OVERRIDE_ENV_NAMES: dict[str, tuple[str, ...]] = {
    "profile_name": ("IMMOAPP_HUB_PROFILE",),
    "cpu_budget": ("IMMOAPP_HUB_CPU_BUDGET",),
    "memory_gb": ("IMMOAPP_HUB_MEMORY_GB",),
    "worker_concurrency": ("IMMOAPP_HUB_WORKER_CONCURRENCY",),
    "import_concurrency": ("IMMOAPP_HUB_IMPORT_CONCURRENCY",),
    "match_concurrency": ("IMMOAPP_HUB_MATCH_CONCURRENCY",),
    "db_pool_size": ("IMMOAPP_HUB_DB_POOL_MAX", "IMMOAPP_HUB_DB_POOL_SIZE"),
    "default_batch_size": ("IMMOAPP_HUB_DEFAULT_BATCH_SIZE",),
}

_NUMERIC_OVERRIDE_FIELDS = {
    "worker_concurrency",
    "import_concurrency",
    "match_concurrency",
    "db_pool_size",
    "default_batch_size",
}

_CUSTOM_REQUIRED_FIELDS = {
    "cpu_budget",
    "memory_gb",
    "worker_concurrency",
    "import_concurrency",
    "match_concurrency",
    "db_pool_size",
}


class HubRuntimeProfileError(ValueError):
    """Raised when Hub runtime profile resolution cannot safely continue."""


@dataclass(frozen=True)
class MachineCapacity:
    cpu_count: int
    total_ram_bytes: int
    available_ram_bytes: int
    total_ram_gb: float
    available_ram_gb: float
    db_capacity_class: str = "large"
    container_cpu_quota: float | None = None
    container_memory_limit_bytes: int | None = None
    effective_cpu_budget: int | None = None
    effective_memory_bytes: int | None = None


@dataclass(frozen=True)
class HubRuntimeLimits:
    worker_concurrency: int
    import_concurrency: int
    match_concurrency: int
    rebuild_concurrency: int
    max_background_jobs: int
    db_pool_size: int
    db_max_overflow: int
    default_batch_size: int
    match_batch_size: int
    import_batch_size: int
    polling_interval_seconds: float
    max_media_thumbnail_concurrency: int
    startup_warmup_enabled: bool
    web_concurrency: int = 1
    asgi_threads: int = 8
    defer_non_urgent_background_jobs: bool = False

    def to_env(self) -> dict[str, str]:
        return {
            "IMMOAPP_HUB_RESOLVED_PROFILE": "",
            PROFILE_EXPORT_MODE_ENV: "",
            "IMMOAPP_HUB_PROFILE_DOCKER": "",
            "IMMOAPP_HUB_PROFILE_SOURCE": "",
            "IMMOAPP_HUB_PROFILE_SOURCE_DOCKER": "",
            "IMMOAPP_HUB_WORKER_CONCURRENCY": str(self.worker_concurrency),
            "IMMOAPP_HUB_IMPORT_CONCURRENCY": str(self.import_concurrency),
            "IMMOAPP_HUB_MATCH_CONCURRENCY": str(self.match_concurrency),
            "IMMOAPP_HUB_DB_POOL_MAX": str(self.db_pool_size),
            "IMMOAPP_HUB_DB_POOL_SIZE": str(self.db_pool_size),
            "IMMOAPP_HUB_DEFAULT_BATCH_SIZE": str(self.default_batch_size),
            "IMMOAPP_HUB_MEDIA_THUMBNAIL_CONCURRENCY": str(self.max_media_thumbnail_concurrency),
            "IMMOAPP_HUB_DEFER_NON_URGENT_BACKGROUND_JOBS": (
                "1" if self.defer_non_urgent_background_jobs else "0"
            ),
            "CELERY_WORKER_CONCURRENCY_DOCKER": str(self.worker_concurrency),
            "CELERY_IMPORT_CONCURRENCY_DOCKER": str(self.import_concurrency),
            "CELERY_MATCH_PAIRS_CONCURRENCY_DOCKER": str(self.match_concurrency),
            "CELERY_REBUILD_CONCURRENCY_DOCKER": str(self.rebuild_concurrency),
            "GUNICORN_WORKERS_DOCKER": str(self.web_concurrency),
            "ASGI_THREADS_DOCKER": str(self.asgi_threads),
            "PG_POOL_MAX_WEB_DOCKER": str(self.db_pool_size),
            "PG_POOL_MAX_WORKER_DOCKER": str(
                max(1, min(self.db_pool_size, self.worker_concurrency + 1))
            ),
            "PG_POOL_MAX_IMPORT_DOCKER": str(
                max(1, min(self.db_pool_size, self.import_concurrency + 2))
            ),
            "PG_POOL_MAX_MATCH_DOCKER": str(
                max(1, min(self.db_pool_size, self.match_concurrency + 1))
            ),
            "PG_POOL_MAX_REBUILD_DOCKER": str(
                max(1, min(self.db_pool_size, self.rebuild_concurrency + 1))
            ),
            "PG_POOL_MAX_BEAT_DOCKER": "1",
            "IMMOAPP_MATCH_PAIRS_DEMANDE_BATCH_SIZE_DOCKER": str(self.match_batch_size),
            "MATCH_CACHE_DB_BATCH_SIZE_DOCKER": str(self.match_batch_size),
            "IMMOAPP_HUB_DEFAULT_BATCH_SIZE_RESOLVED": str(self.default_batch_size),
            "IMMOAPP_HUB_IMPORT_BATCH_SIZE_RESOLVED": str(self.import_batch_size),
            "IMMOAPP_HUB_MATCH_BATCH_SIZE_RESOLVED": str(self.match_batch_size),
            "IMMOAPP_HUB_POLLING_INTERVAL_SECONDS_RESOLVED": str(self.polling_interval_seconds),
            "IMMOAPP_HUB_STARTUP_WARMUP_ENABLED_RESOLVED": (
                "1" if self.startup_warmup_enabled else "0"
            ),
        }


@dataclass(frozen=True)
class HubMemoryPressureSnapshot:
    state: str
    reason: str
    memory_load_percent: float | None = None
    commit_headroom_gb: float | None = None
    process_rss_mb: float | None = None
    process_private_bytes_mb: float | None = None
    sustained_red_samples: int = 0
    captured_at_utc: str = field(default_factory=lambda: datetime.now(tz=UTC).isoformat())

    def to_json_dict(self) -> dict[str, object]:
        return {
            "state": self.state,
            "reason": self.reason,
            "memory_load_percent": self.memory_load_percent,
            "commit_headroom_gb": self.commit_headroom_gb,
            "process_rss_mb": self.process_rss_mb,
            "process_private_bytes_mb": self.process_private_bytes_mb,
            "sustained_red_samples": self.sustained_red_samples,
            "captured_at_utc": self.captured_at_utc,
        }


@dataclass(frozen=True)
class HubRuntimeProfile:
    profile_name: str
    detected_cpu_count: int
    detected_total_ram_bytes: int
    detected_available_ram_bytes: int
    detected_total_ram_gb: float
    detected_available_ram_gb: float
    runtime_mode: str
    limits: HubRuntimeLimits
    effective_cpu_budget: int
    effective_memory_bytes: int
    effective_memory_gb: float
    container_cpu_quota: float | None = None
    container_memory_limit_bytes: int | None = None
    container_memory_limit_gb: float | None = None
    source: str = PROFILE_SOURCE_AUTO
    profile_source: str = PROFILE_SOURCE_AUTO
    detection_source: str = DETECTION_SOURCE_HOST
    db_capacity_class: str = "large"
    capacity_fingerprint: str = ""
    stale_config_regenerated: bool = False
    raw_free_ram_diagnostics_only: bool = RAW_FREE_RAM_DIAGNOSTICS_ONLY
    reasons: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    override_sources: dict[str, str] = field(default_factory=dict)
    generated_at_utc: str = field(default_factory=lambda: datetime.now(tz=UTC).isoformat())
    build_identity: str | None = None

    @property
    def generated_at(self) -> str:
        return self.generated_at_utc

    @property
    def explanation(self) -> str:
        return "; ".join(self.reasons)

    def effective_limits(
        self, pressure: HubMemoryPressureSnapshot | None = None
    ) -> HubRuntimeLimits:
        return limits_for_memory_pressure(
            self.limits,
            pressure or snapshot_hub_memory_pressure(capacity=_capacity_from_profile(self)),
        )

    def to_json_dict(self) -> dict[str, Any]:
        generated_at = self.generated_at_utc or _utc_now()
        limits_payload = asdict(self.limits)
        return {
            "schema_version": PROFILE_SCHEMA_VERSION,
            "generated_at_utc": generated_at,
            "generated_at": generated_at,
            "build_identity": self.build_identity or _build_identity(),
            "source": self.source,
            "profile_source": self.profile_source,
            "detection_source": self.detection_source,
            "capacity_fingerprint": self.capacity_fingerprint,
            "stale_config_regenerated": self.stale_config_regenerated,
            "raw_free_ram_diagnostics_only": self.raw_free_ram_diagnostics_only,
            "effective_runtime_envelope_source": self.detection_source,
            "planned_wsl_memory_gb": None,
            "planned_wsl_processors": None,
            "cap_is_ceiling_not_reservation": True,
            "sustained_pressure_backoff_required": True,
            "detected_cpu_count": self.detected_cpu_count,
            "detected_total_memory_gb": self.detected_total_ram_gb,
            "selected_profile": self.profile_name,
            "profile_limits": limits_payload,
            "detected_machine_facts": {
                "cpu_count": self.detected_cpu_count,
                "total_ram_bytes": self.detected_total_ram_bytes,
                "available_ram_bytes": self.detected_available_ram_bytes,
                "total_ram_gb": self.detected_total_ram_gb,
                "available_ram_gb": self.detected_available_ram_gb,
                "db_capacity_class": self.db_capacity_class,
                "container_cpu_quota": self.container_cpu_quota,
                "container_memory_limit_bytes": self.container_memory_limit_bytes,
                "container_memory_limit_gb": self.container_memory_limit_gb,
                "effective_cpu_budget": self.effective_cpu_budget,
                "effective_memory_bytes": self.effective_memory_bytes,
                "effective_memory_gb": self.effective_memory_gb,
            },
            "selected_profile_name": self.profile_name,
            "runtime_mode": self.runtime_mode,
            "explanation": self.explanation,
            "selected_profile_limits": limits_payload,
            "final_resolved_limits": limits_payload,
            "reasons": list(self.reasons),
            "warnings": list(self.warnings),
            "override_sources": dict(self.override_sources),
        }

    def to_env(self) -> dict[str, str]:
        env = self.limits.to_env()
        env["IMMOAPP_HUB_RESOLVED_PROFILE"] = self.profile_name
        env[PROFILE_EXPORT_MODE_ENV] = PROFILE_EXPORT_MODE_RESOLVED
        env["IMMOAPP_HUB_PROFILE_DOCKER"] = self.profile_name
        env["IMMOAPP_HUB_PROFILE_SOURCE"] = self.source
        env["IMMOAPP_HUB_PROFILE_SOURCE_DOCKER"] = self.source
        env["IMMOAPP_HUB_PROFILE_SOURCE_DETAIL"] = self.profile_source
        env["IMMOAPP_HUB_DETECTION_SOURCE"] = self.detection_source
        env["IMMOAPP_HUB_CPU_BUDGET"] = str(self.effective_cpu_budget)
        env["IMMOAPP_HUB_MEMORY_GB"] = f"{self.effective_memory_bytes / _BYTES_PER_GB:.6f}".rstrip(
            "0"
        ).rstrip(".")
        env["IMMOAPP_HUB_CPU_BUDGET_RESOLVED"] = str(self.effective_cpu_budget)
        env["IMMOAPP_HUB_MEMORY_GB_RESOLVED"] = str(self.effective_memory_gb)
        return env


_DEFAULT_LIMITS: dict[str, HubRuntimeLimits] = {
    "tiny": HubRuntimeLimits(
        worker_concurrency=1,
        import_concurrency=1,
        match_concurrency=1,
        rebuild_concurrency=1,
        max_background_jobs=1,
        db_pool_size=2,
        db_max_overflow=0,
        default_batch_size=50,
        match_batch_size=50,
        import_batch_size=50,
        polling_interval_seconds=1.0,
        max_media_thumbnail_concurrency=1,
        startup_warmup_enabled=False,
        web_concurrency=1,
        asgi_threads=8,
    ),
    "small": HubRuntimeLimits(
        worker_concurrency=2,
        import_concurrency=1,
        match_concurrency=1,
        rebuild_concurrency=1,
        max_background_jobs=2,
        db_pool_size=4,
        db_max_overflow=1,
        default_batch_size=100,
        match_batch_size=100,
        import_batch_size=100,
        polling_interval_seconds=0.75,
        max_media_thumbnail_concurrency=2,
        startup_warmup_enabled=False,
        web_concurrency=2,
        asgi_threads=16,
    ),
    "medium": HubRuntimeLimits(
        worker_concurrency=4,
        import_concurrency=2,
        match_concurrency=2,
        rebuild_concurrency=1,
        max_background_jobs=4,
        db_pool_size=8,
        db_max_overflow=2,
        default_batch_size=250,
        match_batch_size=200,
        import_batch_size=250,
        polling_interval_seconds=0.5,
        max_media_thumbnail_concurrency=3,
        startup_warmup_enabled=True,
        web_concurrency=3,
        asgi_threads=32,
    ),
    "large": HubRuntimeLimits(
        worker_concurrency=6,
        import_concurrency=3,
        match_concurrency=3,
        rebuild_concurrency=2,
        max_background_jobs=6,
        db_pool_size=12,
        db_max_overflow=4,
        default_batch_size=500,
        match_batch_size=250,
        import_batch_size=500,
        polling_interval_seconds=0.25,
        max_media_thumbnail_concurrency=4,
        startup_warmup_enabled=True,
        web_concurrency=4,
        asgi_threads=48,
    ),
}

_SAFE_MAX = HubRuntimeLimits(
    worker_concurrency=8,
    import_concurrency=4,
    match_concurrency=4,
    rebuild_concurrency=3,
    max_background_jobs=8,
    db_pool_size=16,
    db_max_overflow=6,
    default_batch_size=1000,
    match_batch_size=500,
    import_batch_size=1000,
    polling_interval_seconds=2.0,
    max_media_thumbnail_concurrency=6,
    startup_warmup_enabled=True,
    web_concurrency=6,
    asgi_threads=64,
)


def _utc_now() -> str:
    return datetime.now(tz=UTC).isoformat()


def _gb_from_bytes(value: int | None) -> float:
    return round(float(value or 0) / _BYTES_PER_GB, 2)


def _profile_class_for_limits(profile_name: str) -> str:
    return "large" if profile_name == "developer" else profile_name


def _detection_source_for_capacity(
    capacity: MachineCapacity,
    values: Mapping[str, object],
) -> str:
    if "cpu_budget" in values or "memory_gb" in values:
        return DETECTION_SOURCE_OVERRIDE
    if (
        capacity.container_cpu_quota is not None
        or capacity.container_memory_limit_bytes is not None
    ):
        return DETECTION_SOURCE_CONTAINER
    return DETECTION_SOURCE_HOST


def _json_stable(value: Mapping[str, object]) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def _capacity_fingerprint_payload(
    *,
    effective_cpu_budget: int,
    effective_memory_gb: float,
    container_cpu_quota: float | None,
    container_memory_limit_gb: float | None,
    db_capacity_class: str,
    selected_profile: str,
) -> dict[str, object]:
    return {
        "effective_cpu_budget": int(effective_cpu_budget),
        "effective_memory_gb": round(float(effective_memory_gb), 2),
        "container_cpu_quota": (
            round(float(container_cpu_quota), 3) if container_cpu_quota is not None else None
        ),
        "container_memory_limit_gb": (
            round(float(container_memory_limit_gb), 2)
            if container_memory_limit_gb is not None
            else None
        ),
        "db_capacity_class": db_capacity_class,
        "selected_profile": selected_profile,
    }


def _capacity_fingerprint_from_payload(payload: Mapping[str, object]) -> str:
    digest = hashlib.sha256(_json_stable(payload).encode("utf-8")).hexdigest()
    return digest[:16]


def _capacity_fingerprint_for_profile(
    *,
    effective_cpu_budget: int,
    effective_memory_gb: float,
    container_cpu_quota: float | None,
    container_memory_limit_gb: float | None,
    db_capacity_class: str,
    selected_profile: str,
) -> str:
    return _capacity_fingerprint_from_payload(
        _capacity_fingerprint_payload(
            effective_cpu_budget=effective_cpu_budget,
            effective_memory_gb=effective_memory_gb,
            container_cpu_quota=container_cpu_quota,
            container_memory_limit_gb=container_memory_limit_gb,
            db_capacity_class=db_capacity_class,
            selected_profile=selected_profile,
        )
    )


def _profile_source_for_resolved(
    *,
    source: str,
    profile_name: str,
    explicit_profile: object | None,
    custom: bool,
) -> str:
    if profile_name == "custom" or custom:
        return PROFILE_SOURCE_CUSTOM
    if source == PROFILE_SOURCE_ENV_OVERRIDE:
        return PROFILE_SOURCE_ENV_OVERRIDE
    if explicit_profile is not None:
        return PROFILE_SOURCE_PINNED
    return PROFILE_SOURCE_AUTO


def _profile_source_for_loaded(
    *,
    profile_name: str,
    original_source: str,
    persisted_profile_source: str,
    override_sources: Mapping[str, str],
) -> str:
    if profile_name == "custom" or persisted_profile_source == PROFILE_SOURCE_CUSTOM:
        return PROFILE_SOURCE_CUSTOM
    if persisted_profile_source == PROFILE_SOURCE_PINNED:
        return PROFILE_SOURCE_PINNED
    if "profile_name" in override_sources:
        return PROFILE_SOURCE_PINNED
    if original_source == PROFILE_SOURCE_ENV_OVERRIDE:
        return PROFILE_SOURCE_ENV_OVERRIDE
    return PROFILE_SOURCE_PERSISTED


def _build_identity() -> str:
    for name in ("IMMOAPP_BUILD_IDENTITY", "IMMOAPP_COMMIT_SHA", "GIT_COMMIT"):
        value = (os.environ.get(name) or "").strip()
        if value:
            return value
    try:
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            check=False,
            capture_output=True,
            text=True,
            timeout=2,
        )
    except Exception:
        return ""
    return result.stdout.strip() if result.returncode == 0 else ""


def hub_runtime_profile_path() -> Path:
    return config_path(PROFILE_PATH_NAME)


def _read_text(path: Path) -> str | None:
    try:
        return path.read_text(encoding="utf-8").strip()
    except OSError:
        return None


def _parse_cgroup_int(text: str | None) -> int | None:
    if not text or text == "max":
        return None
    try:
        value = int(text)
    except ValueError:
        return None
    if value <= 0 or value >= _UNREALISTIC_CGROUP_MEMORY_LIMIT:
        return None
    return value


def _detect_container_cpu_quota(cgroup_root: Path) -> float | None:
    cpu_max = _read_text(cgroup_root / "cpu.max")
    if cpu_max:
        parts = cpu_max.split()
        if len(parts) >= 2 and parts[0] != "max":
            try:
                quota = float(parts[0])
                period = float(parts[1])
            except ValueError:
                quota = 0.0
                period = 0.0
            if quota > 0 and period > 0:
                return max(0.1, quota / period)

    quota_text = _read_text(cgroup_root / "cpu" / "cpu.cfs_quota_us")
    period_text = _read_text(cgroup_root / "cpu" / "cpu.cfs_period_us")
    if quota_text and period_text:
        try:
            quota = float(quota_text)
            period = float(period_text)
        except ValueError:
            quota = 0.0
            period = 0.0
        if quota > 0 and period > 0:
            return max(0.1, quota / period)
    return None


def _detect_container_memory_limit(cgroup_root: Path) -> int | None:
    for relative in (
        Path("memory.max"),
        Path("memory") / "memory.limit_in_bytes",
    ):
        value = _parse_cgroup_int(_read_text(cgroup_root / relative))
        if value is not None:
            return value
    return None


def _effective_cpu_budget(capacity: MachineCapacity) -> int:
    if capacity.effective_cpu_budget is not None:
        return max(1, int(capacity.effective_cpu_budget))
    if capacity.container_cpu_quota is not None:
        return max(1, min(int(capacity.cpu_count), int(math.floor(capacity.container_cpu_quota))))
    return max(1, int(capacity.cpu_count))


def _effective_memory_bytes(capacity: MachineCapacity) -> int:
    if capacity.effective_memory_bytes is not None:
        return max(0, int(capacity.effective_memory_bytes))
    total = max(0, int(capacity.total_ram_bytes))
    limit = capacity.container_memory_limit_bytes
    if limit is not None and limit > 0:
        return min(total, int(limit)) if total > 0 else int(limit)
    return total


def detect_machine_capacity(
    *, cgroup_root: str | os.PathLike[str] | None = None
) -> MachineCapacity:
    cpu_count = max(1, int(os.cpu_count() or 1))
    total = 0
    available = 0
    if psutil is not None:
        try:
            memory = psutil.virtual_memory()
            total = int(memory.total)
            available = int(memory.available)
        except Exception:
            total = 0
            available = 0
    root = Path(cgroup_root) if cgroup_root is not None else Path("/sys/fs/cgroup")
    cpu_quota = _detect_container_cpu_quota(root)
    memory_limit = _detect_container_memory_limit(root)
    db_class = _normalize_capacity_class(os.environ.get("IMMOAPP_HUB_DB_CAPACITY_CLASS"), "large")
    capacity = MachineCapacity(
        cpu_count=cpu_count,
        total_ram_bytes=total,
        available_ram_bytes=available,
        total_ram_gb=_gb_from_bytes(total),
        available_ram_gb=_gb_from_bytes(available),
        db_capacity_class=db_class,
        container_cpu_quota=cpu_quota,
        container_memory_limit_bytes=memory_limit,
    )
    return MachineCapacity(
        **{
            **asdict(capacity),
            "effective_cpu_budget": _effective_cpu_budget(capacity),
            "effective_memory_bytes": _effective_memory_bytes(capacity),
        }
    )


def _normalize_capacity_class(raw: str | None, default: str) -> str:
    value = str(raw or default).strip().lower()
    if value not in PROFILE_RANK:
        return default
    return value


def _class_for_cpu(cpu_count: int) -> str:
    if cpu_count <= 2:
        return "tiny"
    if cpu_count <= 4:
        return "small"
    if cpu_count <= 8:
        return "medium"
    return "large"


def _class_for_memory(total_ram_gb: float) -> str:
    if total_ram_gb <= 4:
        return "tiny"
    if total_ram_gb <= 8:
        return "small"
    if total_ram_gb <= 16:
        return "medium"
    return "large"


def _min_profile(*profiles: str) -> str:
    return min(profiles, key=lambda item: PROFILE_RANK.get(item, 0))


def _runtime_mode() -> str:
    raw = (
        os.environ.get("IMMOAPP_HUB_RUNTIME_MODE") or os.environ.get("IMMOAPP_ENV") or ""
    ).strip()
    value = raw.lower()
    if value in {"local_dev", "office_hub", "vps", "ci", "unknown"}:
        return value
    if value in {"dev", "development", "test"}:
        return "local_dev"
    if value in {"production", "prod", "staging"}:
        return "vps"
    if os.environ.get("CI"):
        return "ci"
    return "unknown"


def _is_prod_like() -> bool:
    values = {
        (os.environ.get("IMMOAPP_ENV") or "").strip().lower(),
        (os.environ.get("DJANGO_ENV") or "").strip().lower(),
        (os.environ.get("IMMOAPP_HUB_RUNTIME_MODE") or "").strip().lower(),
    }
    return bool(values & {"production", "prod", "staging", "vps"})


def _parse_env_bool(name: str, *, default: bool = False) -> bool:
    try:
        return parse_bool_env_value(name, os.environ.get(name), default=default)
    except EnvBoolError as exc:
        raise HubRuntimeProfileError(str(exc)) from exc


def _unsafe_overrides_allowed(runtime_mode: str) -> bool:
    return _parse_env_bool("IMMOAPP_HUB_ALLOW_UNSAFE_OVERRIDES") and runtime_mode in {
        "local_dev",
        "ci",
    }


def _invalid_profile_fallback_allowed(runtime_mode: str) -> bool:
    return _parse_env_bool("IMMOAPP_HUB_ALLOW_INVALID_PROFILE_FALLBACK") and runtime_mode in {
        "local_dev",
        "ci",
    }


def _parse_positive_int(name: str, raw: object) -> int:
    text = str(raw).strip()
    try:
        value = int(text)
    except ValueError as exc:
        raise HubRuntimeProfileError(f"{name} must be an integer; got {raw!r}.") from exc
    if value <= 0:
        raise HubRuntimeProfileError(f"{name} must be > 0; got {value}.")
    return value


def _parse_positive_float(name: str, raw: object) -> float:
    text = str(raw).strip()
    try:
        value = float(text)
    except ValueError as exc:
        raise HubRuntimeProfileError(f"{name} must be a number; got {raw!r}.") from exc
    if value <= 0:
        raise HubRuntimeProfileError(f"{name} must be > 0; got {value}.")
    return value


def _collect_overrides(
    overrides: Mapping[str, object] | None,
) -> tuple[dict[str, object], dict[str, str]]:
    values: dict[str, object] = {}
    sources: dict[str, str] = {}
    export_mode = (os.environ.get(PROFILE_EXPORT_MODE_ENV) or "").strip()
    if export_mode != PROFILE_EXPORT_MODE_RESOLVED:
        for field_name, env_names in _OVERRIDE_ENV_NAMES.items():
            seen_env: tuple[str, str] | None = None
            for env_name in env_names:
                env_value = os.environ.get(env_name)
                if env_value is not None and str(env_value).strip() != "":
                    normalized_value = str(env_value).strip()
                    if seen_env is None:
                        seen_env = (env_name, normalized_value)
                        continue
                    if normalized_value != seen_env[1]:
                        raise HubRuntimeProfileError(
                            f"Conflicting Hub runtime overrides for {field_name}: "
                            f"{seen_env[0]}={seen_env[1]!r} and {env_name}={normalized_value!r}."
                        )
            if seen_env is not None:
                values[field_name] = seen_env[1]
                sources[field_name] = seen_env[0]
    aliases = {"db_pool_max": "db_pool_size", "memory_budget_gb": "memory_gb"}
    for key, value in dict(overrides or {}).items():
        normalized = aliases.get(str(key), str(key))
        values[normalized] = value
        sources[normalized] = "argument"
    return values, sources


def _apply_capacity_overrides(
    detected: MachineCapacity,
    values: Mapping[str, object],
    warnings: list[str],
    *,
    unsafe_allowed: bool,
) -> MachineCapacity:
    payload = asdict(detected)
    if "cpu_budget" in values:
        parsed = _parse_positive_int("cpu_budget", values["cpu_budget"])
        detected_cpu = max(1, int(detected.cpu_count))
        if parsed > detected_cpu:
            if _is_prod_like():
                raise HubRuntimeProfileError(
                    f"cpu_budget={parsed} exceeds detected CPU count {detected_cpu} in production/staging."
                )
            if unsafe_allowed:
                warnings.append(
                    f"cpu_budget={parsed} exceeds detected CPU count {detected_cpu}; allowed for local/dev."
                )
            else:
                warnings.append(
                    f"cpu_budget={parsed} clamped to detected CPU count {detected_cpu}."
                )
                parsed = detected_cpu
        payload["effective_cpu_budget"] = parsed
    else:
        payload["effective_cpu_budget"] = _effective_cpu_budget(detected)

    if "memory_gb" in values:
        parsed_gb = _parse_positive_float("memory_gb", values["memory_gb"])
        parsed_bytes = int(parsed_gb * _BYTES_PER_GB)
        detected_total = max(0, int(detected.total_ram_bytes))
        if (
            detected_total > 0
            and parsed_bytes > detected_total
            and parsed_bytes - detected_total <= _MEMORY_OVERRIDE_TOLERANCE_BYTES
        ):
            parsed_bytes = detected_total
        if detected_total > 0 and parsed_bytes > detected_total:
            if _is_prod_like():
                raise HubRuntimeProfileError(
                    f"memory_gb={parsed_gb:g} exceeds detected total RAM {detected.total_ram_gb:g} GB in production/staging."
                )
            if unsafe_allowed:
                warnings.append(
                    f"memory_gb={parsed_gb:g} exceeds detected total RAM {detected.total_ram_gb:g} GB; allowed for local/dev."
                )
            else:
                warnings.append(
                    f"memory_gb={parsed_gb:g} clamped to detected total RAM {detected.total_ram_gb:g} GB."
                )
                parsed_bytes = detected_total
        payload["effective_memory_bytes"] = parsed_bytes
    else:
        payload["effective_memory_bytes"] = _effective_memory_bytes(detected)

    return MachineCapacity(**payload)


def _apply_numeric_override(
    *,
    field_name: str,
    value: object,
    limits: HubRuntimeLimits,
    safe_limits: HubRuntimeLimits,
    warnings: list[str],
    unsafe_allowed: bool,
    custom_profile: bool,
) -> HubRuntimeLimits:
    parsed = _parse_positive_int(field_name, value)
    hard_max = int(getattr(_SAFE_MAX, field_name))
    if parsed > hard_max:
        raise HubRuntimeProfileError(f"{field_name}={parsed} exceeds hard safe maximum {hard_max}.")
    profile_max = int(getattr(safe_limits, field_name))
    if parsed > profile_max:
        if custom_profile:
            raise HubRuntimeProfileError(
                f"{field_name}={parsed} exceeds selected capacity safe limit "
                f"{profile_max} for custom profile."
            )
        if not unsafe_allowed:
            raise HubRuntimeProfileError(
                f"{field_name}={parsed} exceeds selected capacity safe limit {profile_max}."
            )
        warnings.append(
            f"{field_name}={parsed} exceeds selected capacity safe limit "
            f"{profile_max}; allowed for local/dev."
        )
    payload = asdict(limits)
    payload[field_name] = parsed
    if field_name == "default_batch_size":
        payload["import_batch_size"] = min(int(payload["import_batch_size"]), parsed)
        payload["match_batch_size"] = min(int(payload["match_batch_size"]), parsed)
    return HubRuntimeLimits(**payload)


def _profile_from_json(data: Mapping[str, Any]) -> HubRuntimeProfile:
    schema_version = int(data.get("schema_version") or 1)
    if schema_version > PROFILE_SCHEMA_VERSION:
        raise HubRuntimeProfileError(
            f"Hub runtime profile schema_version={schema_version} is newer than supported "
            f"{PROFILE_SCHEMA_VERSION}."
        )
    if schema_version >= PROFILE_SCHEMA_VERSION:
        required = (
            "generated_at_utc",
            "source",
            "profile_source",
            "detection_source",
            "capacity_fingerprint",
            "selected_profile",
            "profile_limits",
        )
        missing = [name for name in required if name not in data]
        if missing:
            raise HubRuntimeProfileError(
                "Hub runtime profile JSON is missing required schema v2 fields: "
                + ", ".join(missing)
            )
    facts = dict(data.get("detected_machine_facts") or {})
    profile_name = str(
        data.get("selected_profile")
        or data.get("selected_profile_name")
        or data.get("profile_name")
        or ""
    ).lower()
    if profile_name not in set(PROFILE_INPUT_NAMES):
        raise HubRuntimeProfileError(
            f"Hub runtime profile JSON has invalid profile: {profile_name!r}"
        )
    effective_cpu_budget = int(facts.get("effective_cpu_budget") or facts.get("cpu_count") or 1)
    effective_memory_bytes = int(
        facts.get("effective_memory_bytes")
        or facts.get("container_memory_limit_bytes")
        or facts.get("total_ram_bytes")
        or 0
    )
    effective_memory_gb = float(
        facts.get("effective_memory_gb") or _gb_from_bytes(effective_memory_bytes)
    )
    db_class = _normalize_capacity_class(str(facts.get("db_capacity_class") or "large"), "large")
    default_profile_name = (
        _min_profile(
            _class_for_cpu(effective_cpu_budget),
            _class_for_memory(effective_memory_gb),
            db_class,
        )
        if profile_name == "custom"
        else _profile_class_for_limits(profile_name)
    )
    limits_data = dict(data.get("profile_limits") or data.get("final_resolved_limits") or {})
    default_limits = _DEFAULT_LIMITS.get(default_profile_name, _DEFAULT_LIMITS["small"])
    limits_payload = {**asdict(default_limits), **limits_data}
    try:
        limits = HubRuntimeLimits(**limits_payload)
    except TypeError as exc:
        raise HubRuntimeProfileError("Hub runtime profile JSON has invalid limits.") from exc
    _validate_persisted_limits(
        profile_name,
        limits,
        effective_cpu_budget=effective_cpu_budget,
        effective_memory_gb=effective_memory_gb,
        db_capacity_class=db_class,
        schema_version=schema_version,
        limits_data=limits_data,
    )
    override_sources = {str(k): str(v) for k, v in dict(data.get("override_sources") or {}).items()}
    original_source = str(data.get("source") or PROFILE_SOURCE_AUTO)
    persisted_profile_source = str(data.get("profile_source") or original_source)
    profile_source = _profile_source_for_loaded(
        profile_name=profile_name,
        original_source=original_source,
        persisted_profile_source=persisted_profile_source,
        override_sources=override_sources,
    )
    container_cpu_quota = (
        float(facts["container_cpu_quota"])
        if facts.get("container_cpu_quota") is not None
        else None
    )
    container_memory_limit_bytes = (
        int(facts["container_memory_limit_bytes"])
        if facts.get("container_memory_limit_bytes") is not None
        else None
    )
    container_memory_limit_gb = (
        float(facts["container_memory_limit_gb"])
        if facts.get("container_memory_limit_gb") is not None
        else (
            _gb_from_bytes(container_memory_limit_bytes)
            if container_memory_limit_bytes is not None
            else None
        )
    )
    capacity_fingerprint = str(data.get("capacity_fingerprint") or "")
    if not capacity_fingerprint:
        capacity_fingerprint = _capacity_fingerprint_for_profile(
            effective_cpu_budget=effective_cpu_budget,
            effective_memory_gb=effective_memory_gb,
            container_cpu_quota=container_cpu_quota,
            container_memory_limit_gb=container_memory_limit_gb,
            db_capacity_class=db_class,
            selected_profile=profile_name,
        )
    return HubRuntimeProfile(
        profile_name=profile_name,
        detected_cpu_count=int(facts.get("cpu_count") or data.get("detected_cpu_count") or 1),
        detected_total_ram_bytes=int(facts.get("total_ram_bytes") or 0),
        detected_available_ram_bytes=int(facts.get("available_ram_bytes") or 0),
        detected_total_ram_gb=float(facts.get("total_ram_gb") or 0.0),
        detected_available_ram_gb=float(facts.get("available_ram_gb") or 0.0),
        runtime_mode=str(data.get("runtime_mode") or "unknown"),
        limits=limits,
        effective_cpu_budget=effective_cpu_budget,
        effective_memory_bytes=effective_memory_bytes,
        effective_memory_gb=effective_memory_gb,
        container_cpu_quota=container_cpu_quota,
        container_memory_limit_bytes=container_memory_limit_bytes,
        container_memory_limit_gb=container_memory_limit_gb,
        source=PROFILE_SOURCE_PERSISTED,
        profile_source=profile_source,
        detection_source=str(data.get("detection_source") or DETECTION_SOURCE_HOST),
        db_capacity_class=db_class,
        capacity_fingerprint=capacity_fingerprint,
        stale_config_regenerated=bool(data.get("stale_config_regenerated") or False),
        raw_free_ram_diagnostics_only=bool(
            data.get("raw_free_ram_diagnostics_only")
            if "raw_free_ram_diagnostics_only" in data
            else RAW_FREE_RAM_DIAGNOSTICS_ONLY
        ),
        reasons=[str(item) for item in list(data.get("reasons") or [])],
        warnings=[str(item) for item in list(data.get("warnings") or [])],
        override_sources=override_sources,
        generated_at_utc=str(data.get("generated_at_utc") or data.get("generated_at") or ""),
        build_identity=str(data.get("build_identity") or ""),
    )


def load_hub_runtime_profile(
    path: str | os.PathLike[str] | None = None,
) -> HubRuntimeProfile | None:
    profile_path = Path(path) if path is not None else hub_runtime_profile_path()
    if not profile_path.exists():
        return None
    try:
        data = json.loads(profile_path.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError) as exc:
        raise HubRuntimeProfileError(
            f"Hub runtime profile file is invalid: {profile_path}"
        ) from exc
    if not isinstance(data, Mapping):
        raise HubRuntimeProfileError(f"Hub runtime profile JSON has invalid shape: {profile_path}")
    return _profile_from_json(data)


def _normalize_profile_override(raw: object, warnings: list[str]) -> str:
    requested = str(raw).strip().lower()
    if requested == "dev":
        warnings.append("IMMOAPP_HUB_PROFILE=dev is deprecated; using developer.")
        requested = "developer"
    if requested not in PROFILE_INPUT_NAMES:
        raise HubRuntimeProfileError(
            "IMMOAPP_HUB_PROFILE must be one of tiny, small, medium, large, developer, custom; "
            f"got {raw!r}."
        )
    return requested


def _validate_persisted_limits(
    profile_name: str,
    limits: HubRuntimeLimits,
    *,
    effective_cpu_budget: int,
    effective_memory_gb: float,
    db_capacity_class: str,
    schema_version: int,
    limits_data: Mapping[str, object],
) -> None:
    safe_upper = _SAFE_MAX
    int_fields = (
        "worker_concurrency",
        "import_concurrency",
        "match_concurrency",
        "rebuild_concurrency",
        "max_background_jobs",
        "db_pool_size",
        "default_batch_size",
        "match_batch_size",
        "import_batch_size",
        "max_media_thumbnail_concurrency",
        "web_concurrency",
        "asgi_threads",
    )
    for field_name in int_fields:
        value = getattr(limits, field_name)
        maximum = int(getattr(safe_upper, field_name))
        if type(value) is not int or value <= 0 or value > maximum:
            raise HubRuntimeProfileError(
                f"Hub runtime profile JSON has unsafe {field_name}: {value!r}."
            )

    if (
        type(limits.db_max_overflow) is not int
        or limits.db_max_overflow < 0
        or limits.db_max_overflow > safe_upper.db_max_overflow
    ):
        raise HubRuntimeProfileError(
            f"Hub runtime profile JSON has unsafe db_max_overflow: {limits.db_max_overflow!r}."
        )
    if (
        not isinstance(limits.polling_interval_seconds, (int, float))
        or limits.polling_interval_seconds <= 0
        or limits.polling_interval_seconds > safe_upper.polling_interval_seconds
    ):
        raise HubRuntimeProfileError(
            "Hub runtime profile JSON has unsafe polling_interval_seconds: "
            f"{limits.polling_interval_seconds!r}."
        )
    if not isinstance(limits.startup_warmup_enabled, bool):
        raise HubRuntimeProfileError("Hub runtime profile JSON has invalid startup_warmup_enabled.")
    if not isinstance(limits.defer_non_urgent_background_jobs, bool):
        raise HubRuntimeProfileError(
            "Hub runtime profile JSON has invalid defer_non_urgent_background_jobs."
        )

    if profile_name == "custom":
        if schema_version >= PROFILE_SCHEMA_VERSION:
            missing = sorted(
                {
                    "worker_concurrency",
                    "import_concurrency",
                    "match_concurrency",
                    "db_pool_size",
                }
                - set(limits_data)
            )
            if missing:
                raise HubRuntimeProfileError(
                    "Hub runtime custom profile JSON is missing required limits: "
                    + ", ".join(missing)
                )
        baseline_name = _min_profile(
            _class_for_cpu(effective_cpu_budget),
            _class_for_memory(effective_memory_gb),
            _normalize_capacity_class(db_capacity_class, "large"),
        )
        baseline = _DEFAULT_LIMITS[baseline_name]
    else:
        baseline = _DEFAULT_LIMITS[_profile_class_for_limits(profile_name)]
    pressure_fields = (
        "worker_concurrency",
        "import_concurrency",
        "match_concurrency",
        "rebuild_concurrency",
        "max_background_jobs",
        "db_pool_size",
        "db_max_overflow",
        "default_batch_size",
        "match_batch_size",
        "import_batch_size",
        "max_media_thumbnail_concurrency",
        "web_concurrency",
        "asgi_threads",
    )
    for field_name in pressure_fields:
        value = getattr(limits, field_name)
        maximum = getattr(baseline, field_name)
        if value > maximum:
            raise HubRuntimeProfileError(
                f"Hub runtime profile JSON has {field_name}={value!r}, "
                f"above {profile_name} baseline {maximum!r}; use a safe custom profile."
            )
    if limits.polling_interval_seconds < baseline.polling_interval_seconds:
        raise HubRuntimeProfileError(
            "Hub runtime profile JSON has polling_interval_seconds="
            f"{limits.polling_interval_seconds!r}, below {profile_name} baseline "
            f"{baseline.polling_interval_seconds!r}; use custom profile."
        )
    if limits.startup_warmup_enabled and not baseline.startup_warmup_enabled:
        raise HubRuntimeProfileError(
            "Hub runtime profile JSON enables startup warmup above "
            f"{profile_name} baseline; use custom profile."
        )


def resolve_hub_runtime_profile(
    overrides: Mapping[str, object] | None = None,
    *,
    capacity: MachineCapacity | None = None,
) -> HubRuntimeProfile:
    detected_base = capacity or detect_machine_capacity()
    runtime_mode = _runtime_mode()
    values, sources = _collect_overrides(overrides)
    warnings: list[str] = []
    reasons: list[str] = []
    unsafe_allowed = _unsafe_overrides_allowed(runtime_mode)
    explicit_profile = values.get("profile_name")
    requested_profile = (
        _normalize_profile_override(explicit_profile, warnings)
        if explicit_profile is not None
        else None
    )
    custom_profile_requested = requested_profile == "custom"
    if custom_profile_requested:
        missing = sorted(_CUSTOM_REQUIRED_FIELDS - set(values))
        if missing:
            raise HubRuntimeProfileError(
                "IMMOAPP_HUB_PROFILE=custom requires overrides for: " + ", ".join(missing)
            )
    detected = _apply_capacity_overrides(
        detected_base,
        values,
        warnings,
        unsafe_allowed=unsafe_allowed,
    )
    effective_cpu = _effective_cpu_budget(detected)
    effective_memory = _effective_memory_bytes(detected)
    effective_memory_gb = _gb_from_bytes(effective_memory)
    cpu_class = _class_for_cpu(effective_cpu)
    memory_class = _class_for_memory(effective_memory_gb)
    db_class = _normalize_capacity_class(detected.db_capacity_class, "large")
    base_profile = _min_profile(cpu_class, memory_class, db_class)
    reasons.append(
        "minimum_bottleneck("
        f"cpu={cpu_class}, memory={memory_class}, db={db_class}; "
        f"effective_cpu={effective_cpu}, effective_memory_gb={effective_memory_gb:g}"
        f") -> {base_profile}"
    )

    profile_name = base_profile
    if requested_profile is not None:
        if requested_profile == "custom":
            profile_name = "custom"
            reasons.append("explicit custom profile override")
        elif requested_profile == "developer":
            if _is_prod_like() or runtime_mode not in {"local_dev", "ci"}:
                raise HubRuntimeProfileError(
                    "IMMOAPP_HUB_PROFILE=developer is allowed only in local_dev/ci "
                    "and is forbidden in production/staging."
                )
            profile_name = "developer"
            reasons.append("explicit developer profile override")
        else:
            if PROFILE_RANK[requested_profile] > PROFILE_RANK[base_profile]:
                if not unsafe_allowed:
                    raise HubRuntimeProfileError(
                        f"IMMOAPP_HUB_PROFILE={requested_profile} exceeds detected safe profile {base_profile}."
                    )
                warnings.append(
                    f"IMMOAPP_HUB_PROFILE={requested_profile} exceeds detected safe profile "
                    f"{base_profile}; allowed for local/dev."
                )
            profile_name = requested_profile
            reasons.append(f"explicit profile override: {requested_profile}")

    default_key = (
        base_profile if profile_name == "custom" else _profile_class_for_limits(profile_name)
    )
    limits = _DEFAULT_LIMITS.get(default_key, _DEFAULT_LIMITS["small"])
    safe_limits = _DEFAULT_LIMITS[base_profile]

    if _is_prod_like() and any(field in values for field in _NUMERIC_OVERRIDE_FIELDS):
        for field in _NUMERIC_OVERRIDE_FIELDS:
            value = values.get(field)
            if value is None:
                continue
            parsed = _parse_positive_int(field, value)
            max_value = int(getattr(_DEFAULT_LIMITS[base_profile], field))
            if parsed > max_value:
                raise HubRuntimeProfileError(
                    f"{field}={parsed} exceeds {base_profile} safe limit {max_value} in production/staging."
                )

    numeric_override_applied = False
    for field in _NUMERIC_OVERRIDE_FIELDS:
        if field in values:
            numeric_override_applied = True
            limits = _apply_numeric_override(
                field_name=field,
                value=values[field],
                limits=limits,
                safe_limits=safe_limits,
                warnings=warnings,
                unsafe_allowed=unsafe_allowed,
                custom_profile=custom_profile_requested,
            )
    if numeric_override_applied and not custom_profile_requested:
        reasons.append("numeric runtime override applied")

    source = PROFILE_SOURCE_ENV_OVERRIDE if sources else PROFILE_SOURCE_AUTO
    profile_source = _profile_source_for_resolved(
        source=source,
        profile_name=profile_name,
        explicit_profile=explicit_profile,
        custom=custom_profile_requested,
    )
    detection_source = _detection_source_for_capacity(detected, values)
    container_memory_limit_gb = (
        _gb_from_bytes(detected.container_memory_limit_bytes)
        if detected.container_memory_limit_bytes is not None
        else None
    )
    capacity_fingerprint = _capacity_fingerprint_for_profile(
        effective_cpu_budget=effective_cpu,
        effective_memory_gb=effective_memory_gb,
        container_cpu_quota=detected.container_cpu_quota,
        container_memory_limit_gb=container_memory_limit_gb,
        db_capacity_class=db_class,
        selected_profile=profile_name,
    )
    return HubRuntimeProfile(
        profile_name=profile_name,
        detected_cpu_count=detected.cpu_count,
        detected_total_ram_bytes=detected.total_ram_bytes,
        detected_available_ram_bytes=detected.available_ram_bytes,
        detected_total_ram_gb=detected.total_ram_gb,
        detected_available_ram_gb=detected.available_ram_gb,
        runtime_mode=runtime_mode,
        limits=limits,
        effective_cpu_budget=effective_cpu,
        effective_memory_bytes=effective_memory,
        effective_memory_gb=effective_memory_gb,
        container_cpu_quota=detected.container_cpu_quota,
        container_memory_limit_bytes=detected.container_memory_limit_bytes,
        container_memory_limit_gb=container_memory_limit_gb,
        source=source,
        profile_source=profile_source,
        detection_source=detection_source,
        db_capacity_class=db_class,
        capacity_fingerprint=capacity_fingerprint,
        reasons=reasons,
        warnings=warnings,
        override_sources=sources,
        generated_at_utc=_utc_now(),
        build_identity=_build_identity(),
    )


def _is_auto_like_persisted_profile(profile: HubRuntimeProfile) -> bool:
    return (
        profile.source == PROFILE_SOURCE_PERSISTED
        and profile.profile_source in {PROFILE_SOURCE_AUTO, PROFILE_SOURCE_PERSISTED, ""}
        and profile.profile_name != "custom"
        and not profile.override_sources
    )


def _is_pinned_or_custom_persisted_profile(profile: HubRuntimeProfile) -> bool:
    return profile.source == PROFILE_SOURCE_PERSISTED and (
        profile.profile_source in {PROFILE_SOURCE_PINNED, PROFILE_SOURCE_CUSTOM}
        or profile.profile_name == "custom"
        or bool(profile.override_sources)
    )


def _auto_persisted_profile_is_stale(
    loaded: HubRuntimeProfile,
    current: HubRuntimeProfile,
) -> bool:
    if not _is_auto_like_persisted_profile(loaded):
        return False
    if loaded.effective_cpu_budget != current.effective_cpu_budget:
        return True
    if abs(float(loaded.effective_memory_gb) - float(current.effective_memory_gb)) >= 0.5:
        return True
    if _class_for_memory(loaded.effective_memory_gb) != _class_for_memory(
        current.effective_memory_gb
    ):
        return True
    if loaded.container_cpu_quota != current.container_cpu_quota:
        return True
    if loaded.container_memory_limit_bytes != current.container_memory_limit_bytes:
        return True
    if loaded.db_capacity_class != current.db_capacity_class:
        return True
    if loaded.profile_name != current.profile_name:
        return True
    return False


def _validate_persisted_profile_against_current_capacity(
    loaded: HubRuntimeProfile,
    current: HubRuntimeProfile,
) -> None:
    baseline = current.limits
    for field_name in (
        "worker_concurrency",
        "import_concurrency",
        "match_concurrency",
        "rebuild_concurrency",
        "max_background_jobs",
        "db_pool_size",
        "db_max_overflow",
        "default_batch_size",
        "match_batch_size",
        "import_batch_size",
        "max_media_thumbnail_concurrency",
        "web_concurrency",
        "asgi_threads",
    ):
        value = getattr(loaded.limits, field_name)
        maximum = getattr(baseline, field_name)
        if value > maximum:
            raise HubRuntimeProfileError(
                f"Persisted Hub runtime profile {loaded.profile_name!r} has "
                f"{field_name}={value!r}, above current stable-capacity limit "
                f"{maximum!r} for {current.profile_name!r}."
            )
    if loaded.limits.polling_interval_seconds < baseline.polling_interval_seconds:
        raise HubRuntimeProfileError(
            "Persisted Hub runtime profile polling_interval_seconds="
            f"{loaded.limits.polling_interval_seconds!r}, below current stable-capacity "
            f"limit {baseline.polling_interval_seconds!r}."
        )
    if loaded.limits.startup_warmup_enabled and not baseline.startup_warmup_enabled:
        raise HubRuntimeProfileError(
            "Persisted Hub runtime profile enables startup warmup above current "
            "stable-capacity limit."
        )


def ensure_hub_runtime_profile(
    path: str | os.PathLike[str] | None = None,
    *,
    overrides: Mapping[str, object] | None = None,
    capacity: MachineCapacity | None = None,
) -> HubRuntimeProfile:
    values, sources = _collect_overrides(overrides)
    profile_path = Path(path) if path is not None else hub_runtime_profile_path()
    if sources:
        profile = resolve_hub_runtime_profile(overrides=values, capacity=capacity)
        write_hub_runtime_profile(profile, profile_path)
        return profile
    current = resolve_hub_runtime_profile(capacity=capacity)
    try:
        loaded = load_hub_runtime_profile(profile_path)
    except HubRuntimeProfileError as exc:
        runtime_mode = _runtime_mode()
        if not _invalid_profile_fallback_allowed(runtime_mode):
            raise
        profile = resolve_hub_runtime_profile(capacity=capacity)
        profile = replace(
            profile,
            warnings=[
                *profile.warnings,
                f"invalid persisted profile ignored for local/dev fallback: {exc}",
            ],
        )
        write_hub_runtime_profile(profile, profile_path)
        return profile
    if loaded is not None:
        if _auto_persisted_profile_is_stale(loaded, current):
            regenerated = replace(
                current,
                stale_config_regenerated=True,
                warnings=[
                    *current.warnings,
                    "stale auto-generated Hub runtime profile regenerated after "
                    "stable capacity changed.",
                ],
                reasons=[
                    *current.reasons,
                    "persisted auto profile capacity fingerprint changed",
                ],
            )
            write_hub_runtime_profile(regenerated, profile_path)
            return regenerated
        if _is_pinned_or_custom_persisted_profile(loaded):
            _validate_persisted_profile_against_current_capacity(loaded, current)
        write_hub_runtime_profile(loaded, profile_path)
        return loaded
    write_hub_runtime_profile(current, profile_path)
    return current


def write_hub_runtime_profile(
    profile: HubRuntimeProfile,
    path: str | os.PathLike[str] | None = None,
) -> Path:
    profile_path = Path(path) if path is not None else hub_runtime_profile_path()
    profile_path.parent.mkdir(parents=True, exist_ok=True)
    profile_path.write_text(
        json.dumps(profile.to_json_dict(), indent=2, sort_keys=True, ensure_ascii=True),
        encoding="utf-8",
    )
    return profile_path


def _capacity_from_profile(profile: HubRuntimeProfile) -> MachineCapacity:
    return MachineCapacity(
        cpu_count=profile.detected_cpu_count,
        total_ram_bytes=profile.detected_total_ram_bytes,
        available_ram_bytes=profile.detected_available_ram_bytes,
        total_ram_gb=profile.detected_total_ram_gb,
        available_ram_gb=profile.detected_available_ram_gb,
        db_capacity_class=profile.db_capacity_class,
        container_cpu_quota=profile.container_cpu_quota,
        container_memory_limit_bytes=profile.container_memory_limit_bytes,
        effective_cpu_budget=profile.effective_cpu_budget,
        effective_memory_bytes=profile.effective_memory_bytes,
    )


def snapshot_hub_memory_pressure(
    *,
    memory_load_percent: float | None = None,
    commit_headroom_gb: float | None = None,
    process_rss_bytes: int | None = None,
    process_private_bytes: int | None = None,
    capacity: MachineCapacity | None = None,
    reset_streak: bool = False,
) -> HubMemoryPressureSnapshot:
    global _RED_MEMORY_STREAK
    if reset_streak:
        _RED_MEMORY_STREAK = 0
    detected = capacity or detect_machine_capacity()
    if psutil is not None and memory_load_percent is None:
        try:
            memory = psutil.virtual_memory()
            memory_load_percent = float(memory.percent)
        except Exception:
            memory_load_percent = None
    if psutil is not None and commit_headroom_gb is None:
        try:
            swap = psutil.swap_memory()
            if int(getattr(swap, "total", 0) or 0) > 0:
                commit_headroom_gb = _gb_from_bytes(
                    max(0, int(swap.total) - int(getattr(swap, "used", 0) or 0))
                )
        except Exception:
            commit_headroom_gb = None
    if psutil is not None and (process_rss_bytes is None or process_private_bytes is None):
        try:
            process = psutil.Process(os.getpid())
            memory_info = process.memory_info()
            if process_rss_bytes is None:
                process_rss_bytes = int(getattr(memory_info, "rss", 0) or 0)
            if process_private_bytes is None:
                try:
                    full_info = process.memory_full_info()
                    private = getattr(full_info, "private", None)
                    if private is None:
                        private = getattr(full_info, "uss", None)
                    process_private_bytes = int(private or 0)
                except Exception:
                    process_private_bytes = 0
        except Exception:
            process_rss_bytes = process_rss_bytes or 0
            process_private_bytes = process_private_bytes or 0

    effective_memory = max(0, _effective_memory_bytes(detected))
    process_basis = max(int(process_private_bytes or 0), int(process_rss_bytes or 0))
    process_ratio = (
        float(process_basis) / float(effective_memory)
        if effective_memory > 0 and process_basis > 0
        else 0.0
    )
    load = float(memory_load_percent) if memory_load_percent is not None else None
    severe_commit = commit_headroom_gb is not None and commit_headroom_gb <= 0.5
    severe_process = process_ratio >= 0.75
    red_candidate = load is not None and load >= 95.0
    yellow_candidate = (
        (load is not None and load >= 88.0)
        or (commit_headroom_gb is not None and commit_headroom_gb <= 2.0)
        or process_ratio >= 0.5
    )

    if severe_commit:
        _RED_MEMORY_STREAK = max(_RED_MEMORY_STREAK, _RED_MEMORY_STREAK_REQUIRED)
        state = PRESSURE_RED
        reason = "critical_commit_headroom"
    elif severe_process:
        _RED_MEMORY_STREAK = max(_RED_MEMORY_STREAK, _RED_MEMORY_STREAK_REQUIRED)
        state = PRESSURE_RED
        reason = "process_memory_pressure"
    elif red_candidate:
        _RED_MEMORY_STREAK += 1
        if _RED_MEMORY_STREAK >= _RED_MEMORY_STREAK_REQUIRED:
            state = PRESSURE_RED
            reason = "sustained_high_memory_load"
        else:
            state = PRESSURE_YELLOW
            reason = "high_memory_load_sample"
    elif yellow_candidate:
        _RED_MEMORY_STREAK = 0
        state = PRESSURE_YELLOW
        reason = "moderate_memory_pressure"
    else:
        _RED_MEMORY_STREAK = 0
        state = PRESSURE_GREEN
        reason = "normal"

    return HubMemoryPressureSnapshot(
        state=state,
        reason=reason,
        memory_load_percent=round(load, 2) if load is not None else None,
        commit_headroom_gb=commit_headroom_gb,
        process_rss_mb=(
            round(float(process_rss_bytes or 0) / _BYTES_PER_MB, 2)
            if process_rss_bytes is not None
            else None
        ),
        process_private_bytes_mb=(
            round(float(process_private_bytes or 0) / _BYTES_PER_MB, 2)
            if process_private_bytes is not None
            else None
        ),
        sustained_red_samples=_RED_MEMORY_STREAK,
    )


def limits_for_memory_pressure(
    limits: HubRuntimeLimits,
    pressure: HubMemoryPressureSnapshot,
) -> HubRuntimeLimits:
    if pressure.state == PRESSURE_GREEN:
        return limits
    payload = asdict(limits)
    if pressure.state == PRESSURE_RED:
        payload["import_concurrency"] = 1
        payload["match_concurrency"] = 1
        payload["rebuild_concurrency"] = 1
        payload["max_background_jobs"] = 1
        payload["max_media_thumbnail_concurrency"] = 1
        payload["polling_interval_seconds"] = max(2.0, float(limits.polling_interval_seconds) * 4)
        payload["defer_non_urgent_background_jobs"] = True
        return HubRuntimeLimits(**payload)
    payload["import_concurrency"] = max(1, math.ceil(limits.import_concurrency / 2))
    payload["match_concurrency"] = max(1, math.ceil(limits.match_concurrency / 2))
    payload["rebuild_concurrency"] = max(1, math.ceil(limits.rebuild_concurrency / 2))
    payload["max_background_jobs"] = max(1, math.ceil(limits.max_background_jobs / 2))
    payload["max_media_thumbnail_concurrency"] = max(
        1,
        math.ceil(limits.max_media_thumbnail_concurrency / 2),
    )
    payload["polling_interval_seconds"] = max(1.0, float(limits.polling_interval_seconds) * 2)
    return HubRuntimeLimits(**payload)


def summarize_hub_runtime_profile(
    profile: HubRuntimeProfile,
    *,
    pressure: HubMemoryPressureSnapshot | None = None,
) -> dict[str, object]:
    pressure_snapshot = pressure or snapshot_hub_memory_pressure(
        capacity=_capacity_from_profile(profile)
    )
    effective_limits = profile.effective_limits(pressure_snapshot)
    limits_payload = asdict(profile.limits)
    return {
        "selected_profile": profile.profile_name,
        "source": profile.source,
        "profile_source": profile.profile_source,
        "detection_source": profile.detection_source,
        "runtime_mode": profile.runtime_mode,
        "reason": profile.explanation,
        "config_path": str(hub_runtime_profile_path()),
        "capacity_fingerprint": profile.capacity_fingerprint,
        "stale_config_regenerated": profile.stale_config_regenerated,
        "raw_free_ram_diagnostics_only": profile.raw_free_ram_diagnostics_only,
        "detected_cpu_count": profile.detected_cpu_count,
        "detected_total_ram_gb": profile.detected_total_ram_gb,
        "detected_total_memory_gb": profile.detected_total_ram_gb,
        "effective_cpu_budget": profile.effective_cpu_budget,
        "effective_memory_gb": profile.effective_memory_gb,
        "container_cpu_quota": profile.container_cpu_quota,
        "container_memory_limit_gb": profile.container_memory_limit_gb,
        "selected_profile_limits": limits_payload,
        "worker_concurrency": profile.limits.worker_concurrency,
        "import_concurrency": profile.limits.import_concurrency,
        "match_concurrency": profile.limits.match_concurrency,
        "db_pool_size": profile.limits.db_pool_size,
        "default_batch_size": profile.limits.default_batch_size,
        "import_batch_size": profile.limits.import_batch_size,
        "match_batch_size": profile.limits.match_batch_size,
        "effective_import_concurrency": effective_limits.import_concurrency,
        "effective_match_concurrency": effective_limits.match_concurrency,
        "effective_max_background_jobs": effective_limits.max_background_jobs,
        "effective_polling_interval_seconds": effective_limits.polling_interval_seconds,
        "defer_non_urgent_background_jobs": effective_limits.defer_non_urgent_background_jobs,
        "current_pressure_state": pressure_snapshot.state,
        "pressure": pressure_snapshot.to_json_dict(),
        "warnings": list(profile.warnings),
    }


__all__ = [
    "HubMemoryPressureSnapshot",
    "HubRuntimeLimits",
    "HubRuntimeProfile",
    "HubRuntimeProfileError",
    "MachineCapacity",
    "detect_machine_capacity",
    "ensure_hub_runtime_profile",
    "hub_runtime_profile_path",
    "limits_for_memory_pressure",
    "load_hub_runtime_profile",
    "resolve_hub_runtime_profile",
    "snapshot_hub_memory_pressure",
    "summarize_hub_runtime_profile",
    "write_hub_runtime_profile",
]
