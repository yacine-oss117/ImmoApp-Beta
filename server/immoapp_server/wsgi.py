"""
WSGI config for immoapp_server project.

It exposes the WSGI callable as a module-level variable named ``application``.

For more information on this file, see
https://docs.djangoproject.com/en/6.0/howto/deployment/wsgi/
"""

import os
from pathlib import Path

from django.core.wsgi import get_wsgi_application

from server.immoapp_server.observability import setup_observability
from server.immoapp_server.pycache import configure_pycache
from server.secret_store import load_secrets

BASE_DIR = Path(__file__).resolve().parent.parent
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "server.immoapp_server.settings")
configure_pycache()
load_secrets()
setup_observability(service_name=os.environ.get("OTEL_SERVICE_NAME", "immoapp-server"))
from server.services.cache_layers import ensure_single_flight_backend_ready  # noqa: E402

ensure_single_flight_backend_ready()

application = get_wsgi_application()
