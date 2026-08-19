# Observability

This repo uses SigNoz OSS for traces, metrics, and logs.

## Public commands

Observability only:

```powershell
docker compose --project-directory . -f deployment/compose/compose.observability.yml up -d
```

or:

```bash
make signoz-up
make signoz-down
make signoz-health
```

Full local stack with observability:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File scripts/stack.ps1 -Action up-full -UseWindowsVolumes
```

## Endpoints

- SigNoz UI: `http://localhost:3301`
- OTLP gRPC: `localhost:4317`
- OTLP HTTP: `localhost:4318`

## Runtime contract

The server enables OTEL when `OTEL_EXPORTER_OTLP_ENDPOINT` is set.

Typical local values:

```text
OTEL_EXPORTER_OTLP_ENDPOINT=http://localhost:4318
OTEL_EXPORTER_OTLP_PROTOCOL=http/protobuf
```

What is expected to remain instrumented:

- Django request tracing
- Celery task tracing
- outbound HTTP tracing
- DB/query metrics
- Python logs export

## Policy checks

This doc is intentionally small. The real guardrails are the commands and
verifiers:

- `make signoz-health`
- `python scripts/verify_observability_stack.py`
- `python scripts/verify_signoz_live_rules.py`

For alerting and operational handling, see
`../../ops/runbooks/OBSERVABILITY_RUNBOOK.md`.
