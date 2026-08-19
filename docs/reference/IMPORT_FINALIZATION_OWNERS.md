# Import Finalization Owners

| Concern | Owner module |
| --- | --- |
| Import terminal-state truth | `server/services/import_finalize_service.py` |
| Follow-up shaping, normalization, and persistence | `server/services/import_follow_up.py` |
| Rebuild handoff enqueue and after-commit scheduling | `server/services/import_rebuild_handoff.py` |
| Load-mode orchestration | `server/services/import_load_service.py` |
| Load-phase progress snapshots and transactional success tails | `server/services/import_load_shared.py` |
| Review conflict and preflight detection | `server/services/import_review_conflicts.py` |
| Review row-action collection and pending apply staging | `server/services/import_review_row_actions.py` |
| Review row identity, lookup-key normalization, and audit shaping | `server/services/import_review_shapes.py` |
| Compatibility row projection and review-item enrichment | `server/services/import_review_compatibility.py` |
| Review submit request normalization, effective-resolution shaping, and response payload builders | `server/services/import_review_payloads.py` |
| Review paged read-model queries | `server/services/import_review_queries.py` |
| Job topology inference | `server/services/import_job_topology.py` |
| Importer execution metrics | `server/services/import_execution_metrics.py` |
| Derived public status summary shaping | `server/services/import_status_summary.py` |
| Public status payload projection | `server/services/import_status_payload.py` |
| Queue-depth and polling policy | `server/services/import_status_policy.py` |
