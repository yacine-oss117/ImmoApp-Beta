from __future__ import annotations

import django
from rest_framework.test import APIRequestFactory, force_authenticate

_DJANGO_READY = False


def _ensure_django() -> None:
    global _DJANGO_READY
    if _DJANGO_READY:
        return
    django.setup()
    _DJANGO_READY = True


class _User:
    is_authenticated = True
    is_active = True
    is_superuser = False
    agency_id = 1
    id = 7
    role = "owner"


def test_create_article_response_includes_item(monkeypatch) -> None:
    _ensure_django()

    import server.api.views_crm_articles as module
    from server.api.views_crm_articles import crm_contract_articles

    monkeypatch.setattr(module.crm, "create_article", lambda *args, **kwargs: 41)
    monkeypatch.setattr(
        module.crm,
        "get_articles_for_contract",
        lambda contract_id: [
            {"id": 41, "contract_id": contract_id, "article_number": 1, "title": "Clause"}
        ],
    )

    request = APIRequestFactory().post(
        "/api/v1/crm/contracts/9/articles/",
        {
            "article_number": 1,
            "title": "Clause",
            "content": "Body",
            "is_standard": False,
            "is_required": False,
        },
        format="json",
    )
    force_authenticate(request, user=_User())

    response = crm_contract_articles(request, 9)

    assert response.status_code == 201
    assert response.data["id"] == 41
    assert response.data["item"]["id"] == 41
    assert response.data["item"]["contract_id"] == 9
