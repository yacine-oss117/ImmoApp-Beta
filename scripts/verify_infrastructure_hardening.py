"""
Zero-Trust Infrastructure Hardening Auditor.
Tests:
1. WebSocket Anonymous Rejection (ASGI Level)
2. MinIO Bucket Public Access Lockdown (S3 Level)
"""

import os
import sys
import asyncio
import logging
from pathlib import Path

# Setup logging
logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
logger = logging.getLogger("verify_infrastructure_hardening")

# Add repo root and server directory to path
REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))
sys.path.insert(0, str(REPO_ROOT / "server"))

# Setup Django
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "server.immoapp_server.settings")
try:
    import django

    django.setup()
    logger.info("INFO: Django initialized")
except Exception as e:
    logger.error(f"❌ Django setup failed: {e}")
    sys.exit(1)


async def test_websocket_security():
    logger.info("INFO: TEST 1: WebSocket Anonymous Rejection")
    from core.contracts.ws_protocol import WS_CLOSE_UNAUTHORIZED
    from channels.routing import ProtocolTypeRouter
    from server.immoapp_server.asgi import application
    from channels.testing import WebsocketCommunicator

    if not isinstance(application, ProtocolTypeRouter):
        logger.error("❌ ASGI app is not ProtocolTypeRouter; websocket stack is unavailable.")
        return False
    mapping = getattr(application, "application_mapping", None)
    if not isinstance(mapping, dict) or "websocket" not in mapping:
        logger.error("❌ ASGI app has no websocket protocol mapping.")
        return False

    # Include host+origin so origin validation reaches auth middleware.
    headers = [(b"host", b"localhost"), (b"origin", b"http://localhost")]
    communicator = WebsocketCommunicator(application, "/ws/notifications/", headers=headers)

    connected, detail = await communicator.connect()
    try:
        if connected:
            logger.error("❌ Anonymous websocket unexpectedly connected.")
            return False
        if isinstance(detail, int):
            if detail != WS_CLOSE_UNAUTHORIZED:
                logger.error(
                    "❌ WebSocket rejected anonymous client with wrong code: %s (expected %s)",
                    detail,
                    WS_CLOSE_UNAUTHORIZED,
                )
                return False
            logger.info("INFO: ✅ Anonymous websocket rejected with close code %s", detail)
            return True

        event = await communicator.receive_output(timeout=1.0)
        if event.get("type") != "websocket.close":
            logger.error("❌ Expected websocket.close for anonymous client, got: %s", event)
            return False
        code = event.get("code", 0)
        if code != WS_CLOSE_UNAUTHORIZED:
            logger.error(
                "❌ WebSocket rejected anonymous client with wrong code: %s (expected %s)",
                code,
                WS_CLOSE_UNAUTHORIZED,
            )
            return False
        logger.info("INFO: ✅ Anonymous websocket rejected with close code %s", code)
        return True
    except asyncio.TimeoutError:
        logger.error("❌ Anonymous websocket did not expose a close event or close code in time.")
        return False
    finally:
        if connected:
            await communicator.disconnect()


def test_minio_hardening():
    logger.info("INFO: TEST 2: MinIO Public Access Lockdown")
    import boto3
    from botocore import UNSIGNED
    from botocore.config import Config

    bucket_name = os.environ.get("STORAGE_BUCKET", "immoapp")
    minio_url = f"http://{os.environ.get('MINIO_HOST', 'localhost')}:9000"

    # Try to list objects without credentials (Anonymous)
    s3 = boto3.client("s3", endpoint_url=minio_url, config=Config(signature_version=UNSIGNED))

    try:
        s3.list_objects_v2(Bucket=bucket_name)
        logger.error(f"❌ LEAK: Anonymous listing allowed for bucket '{bucket_name}'!")
        return False
    except Exception as e:
        if "403" in str(e) or "Access Denied" in str(e):
            logger.info("INFO: ✅ MinIO correctly denied anonymous listing (403 Forbidden)")
            return True
        else:
            logger.warning(f"WARNING: Unexpected error during MinIO check: {e}")
            # If we can't connect at all, it's not strictly a leak but we should know
            return False


async def main():
    logger.info("🛡️  [STARTING INFRASTRUCTURE HARDENING AUDIT]")

    ws_success = await test_websocket_security()
    # MinIO check might fail if container isn't reachable during script run,
    # but we should at least try if reachable.
    minio_success = test_minio_hardening()

    if ws_success and minio_success:
        logger.info("🏆 ALL INFRASTRUCTURE HARDENING TESTS PASSED")
        sys.exit(0)
    else:
        logger.error("❌ INFRASTRUCTURE HARDENING AUDIT FAILED")
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())
