"""
ASGI config for immoapp_server project.

It exposes the ASGI callable as a module-level variable named ``application``.

For more information on this file, see
https://docs.djangoproject.com/en/6.0/howto/deployment/asgi/
"""

import logging
import os
from pathlib import Path

from channels.routing import ProtocolTypeRouter, URLRouter
from channels.security.websocket import AllowedHostsOriginValidator
from django.core.asgi import get_asgi_application

from server.immoapp_server.observability import setup_observability
from server.immoapp_server.pycache import configure_pycache
from server.secret_store import load_secrets

logger = logging.getLogger(__name__)

BASE_DIR = Path(__file__).resolve().parent.parent
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "server.immoapp_server.settings")
configure_pycache()
load_secrets()
setup_observability(service_name=os.environ.get("OTEL_SERVICE_NAME", "immoapp-server"))
from server.services.cache_layers import ensure_single_flight_backend_ready  # noqa: E402

ensure_single_flight_backend_ready()

django_asgi_app = get_asgi_application()

try:
    from server.api.ws_auth import JwtAuthMiddlewareStack, WebSocketDenyAnonymousMiddleware
    from server.api.ws_routing import websocket_urlpatterns

    application = ProtocolTypeRouter(
        {
            "http": django_asgi_app,
            "websocket": AllowedHostsOriginValidator(
                JwtAuthMiddlewareStack(
                    WebSocketDenyAnonymousMiddleware(URLRouter(websocket_urlpatterns))
                )
            ),
        }
    )
except Exception:
    logger.exception("Failed to initialize WebSocket ASGI stack")
    if os.environ.get("IMMOAPP_ALLOW_HTTP_ONLY_ASGI_FALLBACK", "0") == "1":
        logger.warning("IMMOAPP_ALLOW_HTTP_ONLY_ASGI_FALLBACK=1: starting HTTP-only ASGI app")
        application = django_asgi_app
    else:
        raise
