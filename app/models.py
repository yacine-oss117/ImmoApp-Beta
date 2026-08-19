"""Model exports for the client (re-export core models)."""

from core.models_audit import AuditLog
from core.models_client import Client, ClientDict
from core.models_crm import Contract, Visit
from core.models_demande import Demande, DemandeDict
from core.models_listing import Listing, ListingDict
from core.models_offer import Offer, OfferDict

__all__ = [
    "AuditLog",
    "Client",
    "ClientDict",
    "Contract",
    "Demande",
    "DemandeDict",
    "Listing",
    "ListingDict",
    "Offer",
    "OfferDict",
    "Visit",
]
