"""
Delta sync endpoints (changes since timestamp).
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Protocol

from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response

from server.api.route_registry import route
from server.api.secured_view import secured_api_view
from server.api.throttling import HeaderScopedRateThrottle as ScopedRateThrottle
from server.services import sync

from .response_schemas import (
    AgencySettingResponseSerializer,
    ClientResponseSerializer,
    ContractArticleResponseSerializer,
    ContractResponseSerializer,
    CustomLocationResponseSerializer,
    DemandeResponseSerializer,
    ListingResponseSerializer,
    OfferPhotoResponseSerializer,
    OfferResponseSerializer,
    TemplateResponseSerializer,
    VisitResponseSerializer,
)
from .view_helpers import error, parse_int, parse_timestamp

SyncItems = Sequence[object]
SyncFetchResult = tuple[SyncItems, str | None, int | None]


class SyncFetcherWithAfterId(Protocol):
    def __call__(
        self,
        *,
        since: str,
        limit: int = 1000,
        after_id: int | None = None,
    ) -> SyncFetchResult: ...


class SyncFetcherWithoutAfterId(Protocol):
    def __call__(
        self,
        *,
        since: str,
        limit: int = 1000,
    ) -> SyncFetchResult: ...


class SerializerInstanceLike(Protocol):
    @property
    def data(self) -> object: ...


class SyncSerializerFactory(Protocol):
    def __call__(
        self,
        instance: object | None = ...,
        data: object = ...,
        **kwargs: object,
    ) -> SerializerInstanceLike: ...


def _sync_params(request: Request) -> tuple[str | None, int, int | None, Response | None]:
    since_raw = request.query_params.get("since")
    since = parse_timestamp(since_raw)
    if since_raw is not None and since is None:
        return None, 0, None, error("since must be ISO-8601 timestamp", status.HTTP_400_BAD_REQUEST)
    if since is None:
        since = "1970-01-01T00:00:00+00:00"
    limit = parse_int(request.query_params.get("limit"), default=1000) or 1000
    limit = max(1, min(limit, 5000))
    after_id_raw = request.query_params.get("after_id")
    after_id: int | None = None
    if after_id_raw is not None and after_id_raw.strip():
        after_id = parse_int(after_id_raw)
        if after_id is None:
            return (
                None,
                0,
                None,
                error(
                    "after_id must be an integer",
                    status.HTTP_400_BAD_REQUEST,
                ),
            )
        if after_id < 0:
            return (
                None,
                0,
                None,
                error(
                    "after_id must be >= 0",
                    status.HTTP_400_BAD_REQUEST,
                ),
            )
    return since, limit, after_id, None


def _sync_response(
    *,
    items: object,
    next_since: str | None,
    next_after_id: int | None,
) -> Response:
    payload: dict[str, object] = {"items": items}
    if next_since is not None:
        payload["next_since"] = next_since
    if next_after_id is not None:
        payload["next_after_id"] = next_after_id
    return Response(payload)


def _serialize_sync_items(
    *,
    items: SyncItems,
    serializer: SyncSerializerFactory,
    next_since: str | None,
    next_after_id: int | None,
) -> Response:
    data = serializer(items, many=True).data
    return _sync_response(items=data, next_since=next_since, next_after_id=next_after_id)


def _sync_endpoint(
    request: Request,
    *,
    fetcher: SyncFetcherWithAfterId,
    serializer: SyncSerializerFactory,
) -> Response:
    since, limit, after_id, error_response = _sync_params(request)
    if error_response:
        return error_response
    items, next_since, next_after_id = fetcher(since=since or "", limit=limit, after_id=after_id)
    return _serialize_sync_items(
        items=items,
        serializer=serializer,
        next_since=next_since,
        next_after_id=next_after_id,
    )


def _sync_endpoint_without_after_id(
    request: Request,
    *,
    fetcher: SyncFetcherWithoutAfterId,
    serializer: SyncSerializerFactory,
) -> Response:
    since, limit, _, error_response = _sync_params(request)
    if error_response:
        return error_response
    items, next_since, next_after_id = fetcher(since=since or "", limit=limit)
    return _serialize_sync_items(
        items=items,
        serializer=serializer,
        next_since=next_since,
        next_after_id=next_after_id,
    )


@route("clients/changes/", order=10)
@secured_api_view(
    ["GET"],
    permission_classes=[IsAuthenticated],
    throttle_classes=[ScopedRateThrottle],
)
def clients_changes(request: Request) -> Response:
    return _sync_endpoint(
        request,
        fetcher=sync.fetch_client_changes,
        serializer=ClientResponseSerializer,
    )


@route("listings/changes/", order=24)
@secured_api_view(
    ["GET"],
    permission_classes=[IsAuthenticated],
    throttle_classes=[ScopedRateThrottle],
)
def listings_changes(request: Request) -> Response:
    return _sync_endpoint(
        request,
        fetcher=sync.fetch_listing_changes,
        serializer=ListingResponseSerializer,
    )


@route("demandes/changes/", order=18)
@secured_api_view(
    ["GET"],
    permission_classes=[IsAuthenticated],
    throttle_classes=[ScopedRateThrottle],
)
def demandes_changes(request: Request) -> Response:
    return _sync_endpoint(
        request,
        fetcher=sync.fetch_demande_changes,
        serializer=DemandeResponseSerializer,
    )


@route("offers/changes/", order=32)
@secured_api_view(
    ["GET"],
    permission_classes=[IsAuthenticated],
    throttle_classes=[ScopedRateThrottle],
)
def offers_changes(request: Request) -> Response:
    return _sync_endpoint(
        request,
        fetcher=sync.fetch_offer_changes,
        serializer=OfferResponseSerializer,
    )


@route("offers/photos/changes/", order=33)
@secured_api_view(
    ["GET"],
    permission_classes=[IsAuthenticated],
    throttle_classes=[ScopedRateThrottle],
)
def offer_photos_changes(request: Request) -> Response:
    return _sync_endpoint(
        request,
        fetcher=sync.fetch_offer_photo_changes,
        serializer=OfferPhotoResponseSerializer,
    )


@route("crm/visits/changes/", order=105)
@secured_api_view(
    ["GET"],
    permission_classes=[IsAuthenticated],
    throttle_classes=[ScopedRateThrottle],
)
def visits_changes(request: Request) -> Response:
    return _sync_endpoint(
        request,
        fetcher=sync.fetch_visit_changes,
        serializer=VisitResponseSerializer,
    )


@route("crm/contracts/changes/", order=91)
@secured_api_view(
    ["GET"],
    permission_classes=[IsAuthenticated],
    throttle_classes=[ScopedRateThrottle],
)
def contracts_changes(request: Request) -> Response:
    return _sync_endpoint(
        request,
        fetcher=sync.fetch_contract_changes,
        serializer=ContractResponseSerializer,
    )


@route("crm/articles/changes/", order=103)
@secured_api_view(
    ["GET"],
    permission_classes=[IsAuthenticated],
    throttle_classes=[ScopedRateThrottle],
)
def contract_articles_changes(request: Request) -> Response:
    return _sync_endpoint(
        request,
        fetcher=sync.fetch_contract_article_changes,
        serializer=ContractArticleResponseSerializer,
    )


@route("locations/changes/", order=74)
@secured_api_view(
    ["GET"],
    permission_classes=[IsAuthenticated],
    throttle_classes=[ScopedRateThrottle],
)
def custom_locations_changes(request: Request) -> Response:
    return _sync_endpoint(
        request,
        fetcher=sync.fetch_custom_location_changes,
        serializer=CustomLocationResponseSerializer,
    )


@route("templates/changes/", order=87)
@secured_api_view(
    ["GET"],
    permission_classes=[IsAuthenticated],
    throttle_classes=[ScopedRateThrottle],
)
def templates_changes(request: Request) -> Response:
    return _sync_endpoint(
        request,
        fetcher=sync.fetch_template_changes,
        serializer=TemplateResponseSerializer,
    )


@route("settings/agency/changes/", order=76)
@secured_api_view(
    ["GET"],
    permission_classes=[IsAuthenticated],
    throttle_classes=[ScopedRateThrottle],
)
def agency_settings_changes(request: Request) -> Response:
    return _sync_endpoint_without_after_id(
        request,
        fetcher=sync.fetch_agency_settings_changes,
        serializer=AgencySettingResponseSerializer,
    )


clients_changes.throttle_scope = "sync"  # type: ignore[attr-defined]
listings_changes.throttle_scope = "sync"  # type: ignore[attr-defined]
demandes_changes.throttle_scope = "sync"  # type: ignore[attr-defined]
offers_changes.throttle_scope = "sync"  # type: ignore[attr-defined]
offer_photos_changes.throttle_scope = "sync"  # type: ignore[attr-defined]
visits_changes.throttle_scope = "sync"  # type: ignore[attr-defined]
contracts_changes.throttle_scope = "sync"  # type: ignore[attr-defined]
contract_articles_changes.throttle_scope = "sync"  # type: ignore[attr-defined]
custom_locations_changes.throttle_scope = "sync"  # type: ignore[attr-defined]
templates_changes.throttle_scope = "sync"  # type: ignore[attr-defined]
agency_settings_changes.throttle_scope = "sync"  # type: ignore[attr-defined]
