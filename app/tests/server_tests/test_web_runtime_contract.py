from __future__ import annotations

from scripts.repo_layout import COMPOSE_PROD_YML, COMPOSE_YML, RUN_WEB_SH


def test_web_entrypoint_supports_daphne_and_gunicorn_uvicorn() -> None:
    text = RUN_WEB_SH.read_text(encoding="utf-8")
    assert 'runtime="${IMMOAPP_WEB_RUNTIME:-gunicorn_uvicorn}"' in text
    assert "uvicorn_worker.UvicornWorker" in text
    assert "server.immoapp_server.asgi:application" in text
    assert "exec daphne -b 0.0.0.0 -p 8000 server.immoapp_server.asgi:application" in text


def test_compose_web_runtime_defaults_and_prod_override() -> None:
    compose = COMPOSE_YML.read_text(encoding="utf-8")
    prod = COMPOSE_PROD_YML.read_text(encoding="utf-8")
    assert "IMMOAPP_WEB_RUNTIME: ${IMMOAPP_WEB_RUNTIME_DOCKER:-gunicorn_uvicorn}" in compose
    assert "IMMOAPP_MATCH_BUILD_PIPELINE: ${IMMOAPP_MATCH_BUILD_PIPELINE_DOCKER:-direct}" in compose
    assert "GUNICORN_WORKERS: ${GUNICORN_WORKERS_DOCKER:?hub_runtime_profile_required}" in compose
    assert "ASGI_THREADS: ${ASGI_THREADS_DOCKER:?hub_runtime_profile_required}" in compose
    assert (
        '"${IMMOAPP_WEB_BIND_HOST:-127.0.0.1}:${IMMOAPP_BACKEND_HOST_PORT:-8000}:8000"' in compose
    )
    assert "exec /app/deployment/docker/run_web.sh" in compose
    assert "IMMOAPP_WEB_RUNTIME: ${IMMOAPP_WEB_RUNTIME_DOCKER:-gunicorn_uvicorn}" in prod
