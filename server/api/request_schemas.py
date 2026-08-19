"""
Request schema aggregator.

Split schemas live in focused modules to keep files small and modular.
"""

from .request_schemas_agency_media import (
    AgencyMediaCompleteSerializer,
    AgencyMediaPresignSerializer,
    AgencyMediaSerializer,
)
from .request_schemas_cache import (
    CacheClientSerializer,
    CacheIdsSerializer,
    CacheStoreCountSerializer,
    CacheStoreCountsSerializer,
    CacheWilayaSerializer,
    SimulationStartSerializer,
)
from .request_schemas_clients import ClientPayloadSerializer, ListingPayloadSerializer
from .request_schemas_crm import (
    ContractArticleSerializer,
    ContractArticleUpdateSerializer,
    ContractCancelSerializer,
    ContractPayloadSerializer,
    CopyClausesSerializer,
    VisitPayloadSerializer,
    VisitUpdateSerializer,
)
from .request_schemas_demandes_offers import DemandePayloadSerializer, OfferPayloadSerializer
from .request_schemas_import import (
    ImportCompleteSerializer,
    ImportExecuteSerializer,
    ImportPresignSerializer,
    ImportPreviewSerializer,
)
from .request_schemas_locations import (
    LocationCreateSerializer,
    LocationDeleteSerializer,
    LocationRenameSerializer,
)
from .request_schemas_notifications import NotificationsMarkSerializer
from .request_schemas_storage import (
    OfferPhotoCreateSerializer,
    StorageCompleteUploadSerializer,
    StorageDeleteSerializer,
    StoragePresignSerializer,
    StoragePresignUploadSerializer,
)
from .request_schemas_templates import (
    AgencySerialSerializer,
    AgencySettingSerializer,
    TemplatePayloadSerializer,
)
from .request_schemas_user_settings import UserSettingsSerializer
from .request_schemas_users import UserCreateSerializer, UserUpdateSerializer
from .request_schemas_visibility import RecordVisibilitySerializer

__all__ = [
    "ClientPayloadSerializer",
    "ListingPayloadSerializer",
    "DemandePayloadSerializer",
    "OfferPayloadSerializer",
    "TemplatePayloadSerializer",
    "AgencySettingSerializer",
    "AgencySerialSerializer",
    "AgencyMediaSerializer",
    "AgencyMediaPresignSerializer",
    "AgencyMediaCompleteSerializer",
    "LocationCreateSerializer",
    "LocationRenameSerializer",
    "LocationDeleteSerializer",
    "CacheIdsSerializer",
    "CacheStoreCountSerializer",
    "CacheStoreCountsSerializer",
    "CacheClientSerializer",
    "CacheWilayaSerializer",
    "SimulationStartSerializer",
    "UserSettingsSerializer",
    "ContractPayloadSerializer",
    "ContractCancelSerializer",
    "ContractArticleSerializer",
    "ContractArticleUpdateSerializer",
    "CopyClausesSerializer",
    "VisitPayloadSerializer",
    "VisitUpdateSerializer",
    "NotificationsMarkSerializer",
    "StoragePresignSerializer",
    "StoragePresignUploadSerializer",
    "StorageCompleteUploadSerializer",
    "StorageDeleteSerializer",
    "OfferPhotoCreateSerializer",
    "ImportPreviewSerializer",
    "ImportExecuteSerializer",
    "ImportPresignSerializer",
    "ImportCompleteSerializer",
    "RecordVisibilitySerializer",
    "UserCreateSerializer",
    "UserUpdateSerializer",
]
