from __future__ import annotations

import argparse
import concurrent.futures
import csv
import io
import json
import math
import statistics
import sys
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit, urlunsplit

import requests

SERVICE_HOST_OVERRIDES = {
    "web": "127.0.0.1",
    "minio": "127.0.0.1",
    "db": "127.0.0.1",
    "rabbitmq": "127.0.0.1",
    "toxiproxy": "127.0.0.1",
    "openbao": "127.0.0.1",
    "valkey": "127.0.0.1",
}


@dataclass(frozen=True)
class SeedUser:
    username: str
    password: str
    role: str
    agency_id: int | None
    is_superuser: bool


@dataclass(frozen=True)
class AgencyActor:
    username: str
    password: str
    agency_id: int
    token: str
    client_ids: list[int]
    listing_ids: list[int]


@dataclass(frozen=True)
class ScenarioConfig:
    name: str
    entity_type: str
    anchor_kind: str
    headers: list[str]


@dataclass
class ImportRunResult:
    scenario: str
    agency_id: int
    actor_username: str
    rows_requested: int
    row_review_interval: int
    session_id: str = ""
    parse_task_id: str = ""
    execute_task_id: str = ""
    terminal_status: str = ""
    terminal_stage: str = ""
    presign_ms: float = 0.0
    upload_ms: float = 0.0
    complete_ms: float = 0.0
    parse_ms: float = 0.0
    execute_ms: float = 0.0
    total_ms: float = 0.0
    preview_ms: float = 0.0
    previewed: bool = False
    created_count: int = 0
    updated_count: int = 0
    skipped_count: int = 0
    error_count: int = 0
    review_count: int = 0
    status_polls: int = 0
    execute_rows_per_second: float = 0.0
    end_to_end_rows_per_second: float = 0.0
    error: str = ""
    inference_summary: dict[str, Any] | None = None
    progress_detail: dict[str, Any] | None = None


SCENARIOS: dict[str, ScenarioConfig] = {
    "demande": ScenarioConfig(
        name="demande",
        entity_type="demande",
        anchor_kind="client",
        headers=[
            "client_id",
            "action",
            "type",
            "wilaya",
            "locations",
            "budget_min",
            "budget_max",
            "surface_min",
            "surface_max",
            "beds_min",
            "floor_min",
            "floor_max",
            "furnished",
            "elevator",
            "accessibility_required",
            "remarks",
        ],
    ),
    "offer": ScenarioConfig(
        name="offer",
        entity_type="offer",
        anchor_kind="listing",
        headers=[
            "listing_id",
            "action",
            "type",
            "wilaya",
            "location",
            "budget",
            "surface",
            "beds",
            "floor",
            "furnished",
            "elevator",
            "accessibility_supported",
            "remarks",
        ],
    ),
}


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run end-to-end importer latency/throughput benchmarks against the live stack.",
    )
    parser.add_argument("--base-url", default="http://127.0.0.1:8000")
    parser.add_argument("--seed-file", required=True)
    parser.add_argument("--output-file", required=True)
    parser.add_argument(
        "--scenario",
        choices=["demande", "offer", "child_mix"],
        default="child_mix",
    )
    parser.add_argument("--tenants", type=int, default=12)
    parser.add_argument("--imports-per-tenant", type=int, default=1)
    parser.add_argument("--rows-per-import", type=int, default=800)
    parser.add_argument("--review-every", type=int, default=0)
    parser.add_argument("--anchor-pool-size", type=int, default=48)
    parser.add_argument("--concurrency", type=int, default=6)
    parser.add_argument("--duplicate-strategy", default="skip")
    parser.add_argument("--poll-interval-seconds", type=float, default=0.5)
    parser.add_argument("--timeout-seconds", type=float, default=600.0)
    parser.add_argument("--preview-fraction", type=float, default=0.0)
    parser.add_argument("--host-header", default="localhost")
    parser.add_argument("--auth-retry-max", type=int, default=8)
    parser.add_argument("--auth-retry-sleep-seconds", type=float, default=1.0)
    return parser.parse_args()


def _load_seed_users(seed_file: str) -> tuple[list[SeedUser], SeedUser | None]:
    payload = json.loads(Path(seed_file).read_text(encoding="utf-8"))
    managers = [
        SeedUser(
            username=str(item["username"]),
            password=str(item["password"]),
            role=str(item["role"]),
            agency_id=int(item["agency_id"]) if item.get("agency_id") is not None else None,
            is_superuser=bool(item.get("is_superuser", False)),
        )
        for item in payload.get("managers", [])
    ]
    superuser_payload = payload.get("superuser")
    superuser = None
    if isinstance(superuser_payload, dict):
        superuser = SeedUser(
            username=str(superuser_payload["username"]),
            password=str(superuser_payload["password"]),
            role=str(superuser_payload["role"]),
            agency_id=None,
            is_superuser=bool(superuser_payload.get("is_superuser", False)),
        )
    return managers, superuser


def _rewrite_service_url(url: str) -> str:
    parts = urlsplit(url)
    host = parts.hostname or ""
    override = SERVICE_HOST_OVERRIDES.get(host)
    if not override:
        return url
    netloc = override
    if parts.port is not None:
        netloc = f"{override}:{parts.port}"
    return urlunsplit((parts.scheme, netloc, parts.path, parts.query, parts.fragment))


def _request_headers(token: str | None, host_header: str) -> dict[str, str]:
    headers = {"Accept": "application/json", "Host": host_header}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    return headers


def _request_json(
    session: requests.Session,
    *,
    method: str,
    url: str,
    host_header: str,
    token: str | None = None,
    json_body: dict[str, Any] | None = None,
    timeout: float = 30.0,
    expected_statuses: set[int] | None = None,
) -> tuple[dict[str, Any], float, int]:
    started = time.perf_counter()
    response = session.request(
        method=method,
        url=url,
        headers=_request_headers(token, host_header),
        json=json_body,
        timeout=timeout,
    )
    elapsed_ms = (time.perf_counter() - started) * 1000.0
    if expected_statuses is None:
        expected_statuses = {200}
    if response.status_code not in expected_statuses:
        detail = response.text[:500]
        raise RuntimeError(f"{method} {url} returned {response.status_code}: {detail}")
    payload = response.json() if response.content else {}
    if not isinstance(payload, dict):
        raise RuntimeError(f"{method} {url} returned non-object JSON payload")
    return payload, elapsed_ms, response.status_code


def _login_token(
    session: requests.Session,
    *,
    base_url: str,
    username: str,
    password: str,
    host_header: str,
    auth_retry_max: int,
    auth_retry_sleep_seconds: float,
) -> str:
    url = f"{base_url}/api/auth/token/"
    for attempt in range(1, auth_retry_max + 1):
        response = session.post(
            url,
            headers={"Content-Type": "application/json", "Host": host_header},
            json={"username": username, "password": password},
            timeout=30.0,
        )
        if response.status_code == 200:
            payload = response.json()
            access = payload.get("access")
            if isinstance(access, str) and access:
                return access
            raise RuntimeError(f"Auth response missing access token for {username}")
        if response.status_code in {429, 500, 502, 503, 504} and attempt < auth_retry_max:
            time.sleep(auth_retry_sleep_seconds * attempt)
            continue
        raise RuntimeError(
            f"Auth failed for {username}: {response.status_code} {response.text[:300]}"
        )
    raise RuntimeError(f"Auth retry budget exhausted for {username}")


def _extract_ids(payload: dict[str, Any]) -> list[int]:
    items = payload.get("items")
    if not isinstance(items, list):
        return []
    ids: list[int] = []
    for item in items:
        if isinstance(item, dict) and isinstance(item.get("id"), int):
            ids.append(int(item["id"]))
    return ids


def _fetch_anchor_ids(
    session: requests.Session,
    *,
    base_url: str,
    token: str,
    host_header: str,
    anchor_pool_size: int,
) -> tuple[list[int], list[int]]:
    clients_payload, _, _ = _request_json(
        session,
        method="GET",
        url=f"{base_url}/api/v1/clients/?limit={anchor_pool_size}&offset=0",
        host_header=host_header,
        token=token,
        expected_statuses={200},
    )
    listings_payload, _, _ = _request_json(
        session,
        method="GET",
        url=f"{base_url}/api/v1/listings/?limit={anchor_pool_size}&offset=0",
        host_header=host_header,
        token=token,
        expected_statuses={200},
    )
    client_ids = _extract_ids(clients_payload)
    listing_ids = _extract_ids(listings_payload)
    if not client_ids:
        raise RuntimeError("No client anchors were returned for importer benchmark")
    if not listing_ids:
        raise RuntimeError("No listing anchors were returned for importer benchmark")
    return client_ids, listing_ids


def _scenario_name(raw_scenario: str, index: int) -> str:
    if raw_scenario != "child_mix":
        return raw_scenario
    return "demande" if index % 2 == 0 else "offer"


def _build_csv_bytes(
    *,
    scenario: ScenarioConfig,
    anchor_ids: list[int],
    rows_per_import: int,
    review_every: int,
    unique_tag: str,
) -> bytes:
    if not anchor_ids:
        raise RuntimeError(f"Missing anchors for scenario {scenario.name}")
    buffer = io.StringIO()
    writer = csv.writer(buffer, lineterminator="\n")
    writer.writerow(scenario.headers)
    for idx in range(rows_per_import):
        anchor_id = anchor_ids[idx % len(anchor_ids)]
        review_row = review_every > 0 and (idx + 1) % review_every == 0
        if scenario.name == "demande":
            location = "Hydra"
            budget_min = "1200000"
            budget_max = "2400000"
            remark = f"{unique_tag}_DEM_OK_{idx}"
            if review_row:
                location = f"Unknown Sector {idx}"
                budget_min = ""
                remark = f"{unique_tag}_DEM_REVIEW_{idx}"
            writer.writerow(
                [
                    anchor_id,
                    "buy",
                    "apartment",
                    16,
                    location,
                    budget_min,
                    budget_max,
                    60,
                    130,
                    2,
                    0,
                    6,
                    "any",
                    "yes",
                    "no",
                    remark,
                ]
            )
        else:
            location = "Ben Aknoun"
            budget = "15000000"
            remark = f"{unique_tag}_OFF_OK_{idx}"
            if review_row:
                location = f"Unknown District {idx}"
                budget = ""
                remark = f"{unique_tag}_OFF_REVIEW_{idx}"
            writer.writerow(
                [
                    anchor_id,
                    "sell",
                    "apartment",
                    16,
                    location,
                    budget,
                    110,
                    3,
                    2,
                    "no",
                    "yes",
                    "no",
                    remark,
                ]
            )
    return buffer.getvalue().encode("utf-8")


def _column_mapping_for_scenario(scenario: ScenarioConfig) -> dict[str, str]:
    return {header: header for header in scenario.headers}


def _poll_status(
    session: requests.Session,
    *,
    base_url: str,
    task_id: str,
    token: str,
    host_header: str,
    timeout_seconds: float,
    poll_interval_seconds: float,
    initial_poll_interval_seconds: float | None = None,
    terminal_statuses: set[str],
) -> tuple[dict[str, Any], float, int]:
    def _coerce_poll_after_seconds(value: object, fallback_seconds: float) -> float:
        if isinstance(value, bool):
            return max(0.05, min(float(int(value)) / 1000.0, 5.0))
        if isinstance(value, int):
            return max(0.05, min(float(value) / 1000.0, 5.0))
        if isinstance(value, float):
            return max(0.05, min(value / 1000.0, 5.0))
        if isinstance(value, str):
            try:
                parsed = int(value)
            except ValueError:
                return max(0.05, min(float(fallback_seconds), 5.0))
            return max(0.05, min(float(parsed) / 1000.0, 5.0))
        return max(0.05, min(float(fallback_seconds), 5.0))

    started = time.perf_counter()
    polls = 0
    last_payload: dict[str, Any] = {}
    next_poll_interval_seconds = _coerce_poll_after_seconds(
        (
            None
            if initial_poll_interval_seconds is None
            else int(initial_poll_interval_seconds * 1000.0)
        ),
        poll_interval_seconds,
    )
    while True:
        last_payload, _, _ = _request_json(
            session,
            method="GET",
            url=f"{base_url}/api/v1/import/status/{task_id}/",
            host_header=host_header,
            token=token,
            expected_statuses={200},
            timeout=max(10.0, poll_interval_seconds * 10.0),
        )
        polls += 1
        status_value = str(last_payload.get("status", "") or "")
        if status_value in terminal_statuses:
            elapsed_ms = (time.perf_counter() - started) * 1000.0
            return last_payload, elapsed_ms, polls
        if (time.perf_counter() - started) >= timeout_seconds:
            raise TimeoutError(f"Timed out waiting for import status {terminal_statuses}")
        next_poll_interval_seconds = _coerce_poll_after_seconds(
            last_payload.get("poll_after_ms"), next_poll_interval_seconds
        )
        time.sleep(next_poll_interval_seconds)


def _maybe_preview(
    session: requests.Session,
    *,
    base_url: str,
    session_id: str,
    token: str,
    host_header: str,
    column_mapping: dict[str, str],
    scenario_entity_type: str,
    preview_fraction: float,
    import_index: int,
) -> tuple[bool, float]:
    if preview_fraction <= 0.0:
        return False, 0.0
    denominator = max(1, int(round(1.0 / preview_fraction)))
    if import_index % denominator != 0:
        return False, 0.0
    _, elapsed_ms, _ = _request_json(
        session,
        method="POST",
        url=f"{base_url}/api/v1/import/preview/",
        host_header=host_header,
        token=token,
        json_body={
            "session_id": session_id,
            "entity_type": scenario_entity_type,
            "column_mapping": column_mapping,
            "limit": 5,
        },
        expected_statuses={200},
        timeout=60.0,
    )
    return True, elapsed_ms


def _run_one_import(
    actor: AgencyActor,
    *,
    base_url: str,
    host_header: str,
    scenario_name: str,
    import_index: int,
    rows_per_import: int,
    review_every: int,
    duplicate_strategy: str,
    poll_interval_seconds: float,
    timeout_seconds: float,
    preview_fraction: float,
) -> ImportRunResult:
    scenario = SCENARIOS[scenario_name]
    anchor_ids = actor.client_ids if scenario.anchor_kind == "client" else actor.listing_ids
    unique_tag = f"perf_{actor.agency_id}_{import_index}_{int(time.time() * 1000)}"
    filename = f"{scenario.name}_{unique_tag}.csv"
    csv_bytes = _build_csv_bytes(
        scenario=scenario,
        anchor_ids=anchor_ids,
        rows_per_import=rows_per_import,
        review_every=review_every,
        unique_tag=unique_tag,
    )
    result = ImportRunResult(
        scenario=scenario.name,
        agency_id=actor.agency_id,
        actor_username=actor.username,
        rows_requested=rows_per_import,
        row_review_interval=review_every,
    )
    session = requests.Session()
    overall_started = time.perf_counter()
    try:
        presign_payload, presign_ms, _ = _request_json(
            session,
            method="POST",
            url=f"{base_url}/api/v1/import/presign/",
            host_header=host_header,
            token=actor.token,
            json_body={
                "filename": filename,
                "content_type": "text/csv",
                "size_bytes": len(csv_bytes),
            },
            expected_statuses={200},
            timeout=30.0,
        )
        result.presign_ms = presign_ms
        storage_id = str(presign_payload["storage_id"])
        upload_url = _rewrite_service_url(str(presign_payload["url"]))
        upload_fields = presign_payload.get("fields")
        if not isinstance(upload_fields, dict):
            raise RuntimeError("Presign response missing upload form fields")

        upload_started = time.perf_counter()
        upload_response = session.post(
            upload_url,
            data={str(key): str(value) for key, value in upload_fields.items()},
            files={"file": (filename, csv_bytes, "text/csv")},
            timeout=max(60.0, timeout_seconds / 4.0),
        )
        result.upload_ms = (time.perf_counter() - upload_started) * 1000.0
        if upload_response.status_code not in {200, 201, 204}:
            raise RuntimeError(
                f"Upload failed with {upload_response.status_code}: {upload_response.text[:300]}"
            )

        complete_payload, complete_ms, _ = _request_json(
            session,
            method="POST",
            url=f"{base_url}/api/v1/import/complete/",
            host_header=host_header,
            token=actor.token,
            json_body={
                "storage_id": storage_id,
                "filename": filename,
                "entity_type": scenario.entity_type,
            },
            expected_statuses={202},
            timeout=30.0,
        )
        result.complete_ms = complete_ms
        result.session_id = str(complete_payload["session_id"])
        result.parse_task_id = str(complete_payload["task_id"])

        parse_payload, parse_ms, parse_polls = _poll_status(
            session,
            base_url=base_url,
            task_id=result.parse_task_id,
            token=actor.token,
            host_header=host_header,
            timeout_seconds=timeout_seconds,
            poll_interval_seconds=poll_interval_seconds,
            initial_poll_interval_seconds=(
                max(
                    0.05,
                    float(int(complete_payload.get("poll_after_ms", 0) or 0)) / 1000.0,
                )
                if complete_payload.get("poll_after_ms") is not None
                else None
            ),
            terminal_statuses={"ready", "failed"},
        )
        result.parse_ms = parse_ms
        result.status_polls += parse_polls
        result.inference_summary = (
            dict(parse_payload.get("inference_summary", {}))
            if isinstance(parse_payload.get("inference_summary"), dict)
            else None
        )
        if str(parse_payload.get("status", "")) != "ready":
            raise RuntimeError(
                f"Parse did not reach ready state: {json.dumps(parse_payload, default=str)[:500]}"
            )

        previewed, preview_ms = _maybe_preview(
            session,
            base_url=base_url,
            session_id=result.session_id,
            token=actor.token,
            host_header=host_header,
            column_mapping=_column_mapping_for_scenario(scenario),
            scenario_entity_type=scenario.entity_type,
            preview_fraction=preview_fraction,
            import_index=import_index,
        )
        result.previewed = previewed
        result.preview_ms = preview_ms

        execute_payload, _, _ = _request_json(
            session,
            method="POST",
            url=f"{base_url}/api/v1/import/execute/",
            host_header=host_header,
            token=actor.token,
            json_body={
                "session_id": result.session_id,
                "entity_type": scenario.entity_type,
                "column_mapping": _column_mapping_for_scenario(scenario),
                "duplicate_strategy": duplicate_strategy,
                "skip_review_rows": False,
            },
            expected_statuses={202},
            timeout=30.0,
        )
        result.execute_task_id = str(execute_payload["task_id"])

        execute_payload_final, execute_ms, execute_polls = _poll_status(
            session,
            base_url=base_url,
            task_id=result.execute_task_id,
            token=actor.token,
            host_header=host_header,
            timeout_seconds=timeout_seconds,
            poll_interval_seconds=poll_interval_seconds,
            initial_poll_interval_seconds=(
                max(
                    0.05,
                    float(int(execute_payload.get("poll_after_ms", 0) or 0)) / 1000.0,
                )
                if execute_payload.get("poll_after_ms") is not None
                else None
            ),
            terminal_statuses={"completed", "review", "failed"},
        )
        result.execute_ms = execute_ms
        result.status_polls += execute_polls
        result.total_ms = (time.perf_counter() - overall_started) * 1000.0
        result.terminal_status = str(execute_payload_final.get("status", "") or "")
        result.terminal_stage = str(execute_payload_final.get("stage", "") or "")
        result.progress_detail = (
            dict(execute_payload_final.get("progress_detail", {}))
            if isinstance(execute_payload_final.get("progress_detail"), dict)
            else None
        )
        last_result = execute_payload_final.get("last_result")
        if isinstance(last_result, dict):
            result.created_count = int(last_result.get("created_count", 0) or 0)
            result.updated_count = int(last_result.get("updated_count", 0) or 0)
            result.skipped_count = int(last_result.get("skipped_count", 0) or 0)
            result.error_count = int(last_result.get("error_count", 0) or 0)
        result.review_count = int(execute_payload_final.get("review_count", 0) or 0)
        if result.execute_ms > 0:
            result.execute_rows_per_second = (rows_per_import * 1000.0) / result.execute_ms
        if result.total_ms > 0:
            result.end_to_end_rows_per_second = (rows_per_import * 1000.0) / result.total_ms
        if result.terminal_status == "failed":
            raise RuntimeError(json.dumps(execute_payload_final, default=str)[:500])
        return result
    except Exception as exc:
        result.total_ms = (time.perf_counter() - overall_started) * 1000.0
        result.terminal_status = result.terminal_status or "failed"
        result.error = str(exc)
        return result
    finally:
        session.close()


def _percentile(values: list[float], percentile: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    if len(ordered) == 1:
        return ordered[0]
    rank = max(0.0, min(100.0, percentile)) / 100.0 * (len(ordered) - 1)
    lower = int(math.floor(rank))
    upper = int(math.ceil(rank))
    if lower == upper:
        return ordered[lower]
    fraction = rank - lower
    return ordered[lower] + (ordered[upper] - ordered[lower]) * fraction


def _summarize_results(
    results: list[ImportRunResult],
    *,
    wall_seconds: float,
) -> dict[str, Any]:
    success_statuses = {"completed", "review"}
    successes = [item for item in results if item.terminal_status in success_statuses]
    failures = [item for item in results if item.terminal_status not in success_statuses]
    parse_values = [item.parse_ms for item in successes if item.parse_ms > 0]
    execute_values = [item.execute_ms for item in successes if item.execute_ms > 0]
    total_values = [item.total_ms for item in successes if item.total_ms > 0]
    total_rows = sum(item.rows_requested for item in successes)
    total_created = sum(item.created_count for item in successes)
    total_updated = sum(item.updated_count for item in successes)
    total_skipped = sum(item.skipped_count for item in successes)
    total_review = sum(item.review_count for item in successes)
    total_errors = sum(item.error_count for item in results)
    scenario_summary: dict[str, Any] = {}
    for scenario_name in sorted({item.scenario for item in results}):
        scenario_items = [item for item in results if item.scenario == scenario_name]
        scenario_success = [
            item for item in scenario_items if item.terminal_status in success_statuses
        ]
        scenario_summary[scenario_name] = {
            "imports_total": len(scenario_items),
            "imports_succeeded": len(scenario_success),
            "imports_failed": len(scenario_items) - len(scenario_success),
            "rows_total": sum(item.rows_requested for item in scenario_success),
            "parse_p95_ms": _percentile(
                [item.parse_ms for item in scenario_success if item.parse_ms > 0],
                95.0,
            ),
            "execute_p95_ms": _percentile(
                [item.execute_ms for item in scenario_success if item.execute_ms > 0],
                95.0,
            ),
            "end_to_end_p95_ms": _percentile(
                [item.total_ms for item in scenario_success if item.total_ms > 0],
                95.0,
            ),
            "rows_per_second": (
                sum(item.rows_requested for item in scenario_success) / wall_seconds
                if wall_seconds > 0
                else 0.0
            ),
        }
    return {
        "imports_total": len(results),
        "imports_succeeded": len(successes),
        "imports_failed": len(failures),
        "rows_total": total_rows,
        "rows_created": total_created,
        "rows_updated": total_updated,
        "rows_skipped": total_skipped,
        "rows_review": total_review,
        "row_errors_reported": total_errors,
        "throughput_rows_per_second": (total_rows / wall_seconds) if wall_seconds > 0 else 0.0,
        "parse_latency_ms": {
            "avg": statistics.fmean(parse_values) if parse_values else 0.0,
            "p50": _percentile(parse_values, 50.0),
            "p95": _percentile(parse_values, 95.0),
            "p99": _percentile(parse_values, 99.0),
            "max": max(parse_values) if parse_values else 0.0,
        },
        "execute_latency_ms": {
            "avg": statistics.fmean(execute_values) if execute_values else 0.0,
            "p50": _percentile(execute_values, 50.0),
            "p95": _percentile(execute_values, 95.0),
            "p99": _percentile(execute_values, 99.0),
            "max": max(execute_values) if execute_values else 0.0,
        },
        "end_to_end_latency_ms": {
            "avg": statistics.fmean(total_values) if total_values else 0.0,
            "p50": _percentile(total_values, 50.0),
            "p95": _percentile(total_values, 95.0),
            "p99": _percentile(total_values, 99.0),
            "max": max(total_values) if total_values else 0.0,
        },
        "scenario_breakdown": scenario_summary,
        "failures": [
            {
                "scenario": item.scenario,
                "agency_id": item.agency_id,
                "actor_username": item.actor_username,
                "error": item.error,
                "terminal_status": item.terminal_status,
            }
            for item in failures[:25]
        ],
    }


def _fetch_health_snapshot(
    *,
    base_url: str,
    superuser: SeedUser | None,
    host_header: str,
    auth_retry_max: int,
    auth_retry_sleep_seconds: float,
) -> dict[str, Any] | None:
    if superuser is None:
        return None
    session = requests.Session()
    try:
        token = _login_token(
            session,
            base_url=base_url,
            username=superuser.username,
            password=superuser.password,
            host_header=host_header,
            auth_retry_max=auth_retry_max,
            auth_retry_sleep_seconds=auth_retry_sleep_seconds,
        )
        payload, _, _ = _request_json(
            session,
            method="GET",
            url=f"{base_url}/api/v1/health/snapshot/",
            host_header=host_header,
            token=token,
            expected_statuses={200},
            timeout=60.0,
        )
        return payload
    except Exception as exc:
        return {"error": str(exc)}
    finally:
        session.close()


def main() -> None:
    args = _parse_args()
    base_url = args.base_url.rstrip("/")
    managers, superuser = _load_seed_users(args.seed_file)
    if not managers:
        raise SystemExit("Seed file does not contain any manager users")
    selected_managers = [
        item
        for item in managers[: max(1, min(int(args.tenants), len(managers)))]
        if item.agency_id is not None
    ]
    if not selected_managers:
        raise SystemExit("No tenant-scoped manager users were selected")

    auth_session = requests.Session()
    actors: list[AgencyActor] = []
    try:
        for manager in selected_managers:
            token = _login_token(
                auth_session,
                base_url=base_url,
                username=manager.username,
                password=manager.password,
                host_header=args.host_header,
                auth_retry_max=int(args.auth_retry_max),
                auth_retry_sleep_seconds=float(args.auth_retry_sleep_seconds),
            )
            client_ids, listing_ids = _fetch_anchor_ids(
                auth_session,
                base_url=base_url,
                token=token,
                host_header=args.host_header,
                anchor_pool_size=int(args.anchor_pool_size),
            )
            actors.append(
                AgencyActor(
                    username=manager.username,
                    password=manager.password,
                    agency_id=int(manager.agency_id or 0),
                    token=token,
                    client_ids=client_ids,
                    listing_ids=listing_ids,
                )
            )
    finally:
        auth_session.close()

    scheduled_runs: list[tuple[AgencyActor, str, int]] = []
    for actor_index, actor in enumerate(actors):
        for local_index in range(int(args.imports_per_tenant)):
            run_index = actor_index * max(1, int(args.imports_per_tenant)) + local_index
            scheduled_runs.append((actor, _scenario_name(str(args.scenario), run_index), run_index))

    results: list[ImportRunResult] = []
    started = time.perf_counter()
    with concurrent.futures.ThreadPoolExecutor(
        max_workers=max(1, int(args.concurrency))
    ) as executor:
        future_map = {
            executor.submit(
                _run_one_import,
                actor,
                base_url=base_url,
                host_header=args.host_header,
                scenario_name=scenario_name,
                import_index=run_index,
                rows_per_import=int(args.rows_per_import),
                review_every=int(args.review_every),
                duplicate_strategy=str(args.duplicate_strategy),
                poll_interval_seconds=float(args.poll_interval_seconds),
                timeout_seconds=float(args.timeout_seconds),
                preview_fraction=float(args.preview_fraction),
            ): (actor, scenario_name, run_index)
            for actor, scenario_name, run_index in scheduled_runs
        }
        for future in concurrent.futures.as_completed(future_map):
            results.append(future.result())
    wall_seconds = time.perf_counter() - started

    report = {
        "generated_at_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "base_url": base_url,
        "scenario": args.scenario,
        "rows_per_import": int(args.rows_per_import),
        "review_every": int(args.review_every),
        "tenants": len(actors),
        "imports_per_tenant": int(args.imports_per_tenant),
        "concurrency": int(args.concurrency),
        "duplicate_strategy": str(args.duplicate_strategy),
        "wall_seconds": wall_seconds,
        "summary": _summarize_results(results, wall_seconds=wall_seconds),
        "health_snapshot": _fetch_health_snapshot(
            base_url=base_url,
            superuser=superuser,
            host_header=args.host_header,
            auth_retry_max=int(args.auth_retry_max),
            auth_retry_sleep_seconds=float(args.auth_retry_sleep_seconds),
        ),
        "runs": [asdict(item) for item in sorted(results, key=lambda item: item.agency_id)],
    }
    output_path = Path(args.output_file)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(report, indent=2), encoding="utf-8")
    json.dump(report["summary"], sys.stdout, indent=2)
    sys.stdout.write("\n")


if __name__ == "__main__":
    main()
