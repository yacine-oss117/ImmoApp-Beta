from __future__ import annotations

import os


def _ensure_django() -> None:
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "server.immoapp_server.settings")
    import django
    from django.apps import apps

    if not apps.ready:
        django.setup()


def test_enqueue_post_import_rebuilds_preserves_actor_identity_for_client_follow_up(
    monkeypatch,
) -> None:
    _ensure_django()
    from server.logging_config import set_correlation_id
    from server.pg.uow import use_actor_context, use_schema, use_security_context
    from server.services.import_constants import ENTITY_TYPE_CLIENT
    from server.services.import_rebuild_handoff import enqueue_post_import_rebuilds

    captured: dict[str, object] = {}
    monkeypatch.setattr(
        "server.api.tasks.rebuild_match_cache_dirty.delay",
        lambda **kwargs: captured.update(dict(kwargs)),
    )

    set_correlation_id("corr-import")
    try:
        with use_schema("public"):
            with use_security_context(agency_id=12, is_superuser=False):
                with use_actor_context(actor_id=77, actor_role="manager", actor_is_owner=True):
                    enqueue_post_import_rebuilds(
                        entity_type=ENTITY_TYPE_CLIENT,
                        agency_id=12,
                        listing_wilaya_ids=set(),
                        demande_ids=set(),
                        demande_client_ids=set(),
                        offer_ids=set(),
                    )
    finally:
        set_correlation_id(None)

    assert captured == {
        "schema": "public",
        "agency_id": 12,
        "correlation_id": "corr-import",
        "actor_id": 77,
        "actor_role": "manager",
    }
