# Matching And Cache Architecture

This document explains the matching engine, durable pair rebuild flow, and
match-count cache flow.

## What It Owns

The matching subsystem owns:

- demande-to-offer matching logic
- detailed match result retrieval
- tenant-wide or scoped match count computation
- durable precomputed match pairs
- durable count cache refresh
- rebuild coalescing and rerun tracking

The subsystem is intentionally split into two related paths:

- pair computation: durable candidate/pair state
- count cache: fast counts for list and dashboard surfaces

## Core Logic

Primary domain logic lives under `core/matcher/`.

Important files:

- `core/matcher/match_details.py`
- `core/matcher/match_counter.py`
- `core/matcher/match_query_sql.py`
- `core/matcher/match_scoring.py`
- `core/matcher/match_models.py`

Primary persistence and rebuild state lives under `core/data/`.

Important files:

- `core/data/match_pairs.py`
- `core/data/match_cache.py`
- `core/data/match_cache_read.py`
- `core/data/match_cache_write.py`
- `core/data/match_rebuild_state.py`
- `core/data/match_candidates.py`

## Public API Surface

Detailed results:

- `matches/client/<client_id>/`
- `matches/demandes/<demande_id>/`
- `matches/demandes/<demande_id>/expand/`

Count APIs:

- `matches/clients/counts/`
- `matches/demandes/counts/`
- `matches/listings/counts/`
- `matches/offers/counts/`
- `matches/clients/wilaya/`

Tenant-wide async endpoints:

- `matches/clients/all/`
- `matches/demandes/all/`
- `matches/listings/all/`
- `matches/offers/all/`

Cache status and mutation APIs:

- `cache/match/status/`
- `cache/match/dirty/`
- `cache/match/missing/`
- `cache/match/get/`
- `cache/match/batch/`
- `cache/match/count/`
- `cache/match/counts/`
- `cache/match/mark-all/`
- `cache/match/mark-client/`
- `cache/match/mark-wilaya/`
- `cache/match/clear/`
- `cache/match/all/`
- `cache/match/rebuild/`
- `cache/match/rebuild/dirty/`
- `cache/match/rebuild/client/`
- `cache/match/rebuild/wilaya/`

HTTP view owners:

- `server/api/views_matches.py`
- `server/api/views_cache_status.py`
- `server/api/views_cache_mutations.py`
- `server/api/views_cache_tasks.py`

## Service And Task Owners

Read/query facade:

- `server/services/matches.py`

Count cache service facade:

- `server/services/match_cache.py`

Task scheduling helpers:

- `server/services/match_jobs.py`
- `server/services/match_all_scheduler.py`
- `server/services/match_runtime_profile.py`
- `server/services/rebuild_leases.py`

Task execution:

- `server/api/tasks_match_pairs.py`
- `server/api/tasks_match_cache.py`

## Desktop Client Surface

UI entrypoints:

- `app/views/match.py`
- `app/views/match_tab.py`
- `app/views/match_results.py`
- `app/views/match_workers.py`

Client service facade:

- `app/services/match_service.py`

Detailed result fetch:

- `app/services/match_fetch.py`

Count and task polling:

- `app/services/match_counts.py`
- `app/services/task_status.py`

The desktop client never computes matches. It only fetches results, requests
expansion or background counts, and renders the returned models.

## Detailed Result Flow

Single client flow:

1. desktop calls `app/services/match_fetch.py`
2. API request lands in `server/api/views_matches.py`
3. view delegates to `server/services/matches.py`
4. service loads active demandes for the client
5. `core/matcher/match_details.py` builds ranked results per demande
6. response is serialized back to the client

Important behavior in `server/services/matches.py`:

- in cache-only mode, missing active pairs can trigger a rebuild enqueue
- there is also an inline pair hydration fallback on cache miss for a demande

That is why a read path can sometimes repair stale pair state instead of only
returning empty data.

## Pair Rebuild Flow

Pair rebuild tasks live in `server/api/tasks_match_pairs.py`.

Important task entrypoints:

- `rebuild_match_pairs_for_demande`
- `rebuild_match_pairs_for_demandes_batch`
- `expand_match_pairs_for_demande`
- `rebuild_match_pairs_for_wilaya`
- `rebuild_match_pairs_for_client`
- `rebuild_match_pairs_for_offer`

The durable rerun contract lives in `core/data/match_rebuild_state.py`.

`match_rebuild_state` records:

- scope
- scope id
- generation
- pending flag
- stale detection

The task pattern is:

1. request rebuild and note generation
2. acquire scoped lock
3. compute pairs
4. finalize generation
5. rerun if another generation was requested during execution
6. cascade count-cache refresh

This is the mechanism that prevents missed rebuilds when concurrent changes
arrive during an in-flight task.

## Count Cache Flow

Count cache tasks live in `server/api/tasks_match_cache.py`.

Important task entrypoints:

- `rebuild_match_cache_all`
- `rebuild_match_cache_dirty`
- `rebuild_match_cache_client`
- `rebuild_match_cache_wilaya`
- `count_matches_all_clients_task`
- `count_matches_all_demandes_task`
- `count_matches_all_listings_task`
- `count_matches_all_offers_task`

The service wrapper is `server/services/match_cache.py`.

The underlying persistence contract is `core/data/match_cache.py`.

Important behaviors:

- dirty and missing cache entries are tracked separately
- large rebuilds use batching and checkpoint/lease helpers
- tenant-wide async endpoints are backpressured through
  `tenant_resource_governor`
- completion can emit notifications

## When This Subsystem Is Touched

Matching state is indirectly affected by other domains.

Notable examples:

- CRM contract activation/cancellation marks client and wilaya cache state dirty
- listing/offer changes can require pair and count refresh
- importer execution can create or update entities that later need rebuilds

This is why the matching subsystem is not just a read service. It is a runtime
maintenance surface.

## Where To Debug

Bad scores or wrong ranking:

- `core/matcher/`
- `server/services/matches.py`

Pair rebuild loops or missed refreshes:

- `server/api/tasks_match_pairs.py`
- `core/data/match_rebuild_state.py`

Count cache drift or backlog:

- `server/api/tasks_match_cache.py`
- `server/services/match_cache.py`
- `core/data/match_cache.py`

API and task scheduling behavior:

- `server/api/views_matches.py`
- `server/api/views_cache_tasks.py`
- `server/services/match_all_scheduler.py`
