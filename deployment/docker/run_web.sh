#!/bin/sh
set -eu

python -m server.secret_store.openbao_runtime_bootstrap
python -c 'import json; from core.runtime.hub_runtime_profile import ensure_hub_runtime_profile; print(json.dumps(ensure_hub_runtime_profile().to_json_dict(), sort_keys=True))' >/tmp/immoapp_hub_runtime_profile.json || {
  echo "Hub runtime profile resolution failed" >&2
  exit 64
}
echo "Hub runtime profile: ${IMMOAPP_HUB_RESOLVED_PROFILE:-unknown}"

runtime="${IMMOAPP_WEB_RUNTIME:-gunicorn_uvicorn}"

case "$runtime" in
  gunicorn_uvicorn)
    exec gunicorn server.immoapp_server.asgi:application \
      -k uvicorn_worker.UvicornWorker \
      -w "${GUNICORN_WORKERS:?hub_runtime_profile_required}" \
      -b 0.0.0.0:8000 \
      --timeout "${GUNICORN_TIMEOUT:-120}" \
      --graceful-timeout "${GUNICORN_GRACEFUL_TIMEOUT:-30}" \
      --keep-alive "${GUNICORN_KEEPALIVE:-5}"
    ;;
  daphne)
    exec daphne -b 0.0.0.0 -p 8000 server.immoapp_server.asgi:application
    ;;
  *)
    echo "Unsupported IMMOAPP_WEB_RUNTIME: $runtime" >&2
    exit 64
    ;;
esac
