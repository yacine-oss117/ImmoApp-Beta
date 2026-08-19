"""ALE field policy definitions.

This module is the single source of truth for how each sensitive field is
masked, encrypted, and indexed at write-time.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from enum import StrEnum

from core.utils.common import phone_digits


class AlePublicMode(StrEnum):
    """Public-column storage mode for sensitive fields."""

    MASK = "mask"
    BLIND_INDEX = "blind_index"
    ZERO = "zero"


@dataclass(frozen=True)
class AleFieldPolicy:
    """Policy for a single ALE-protected field."""

    name: str
    encrypt: bool
    searchable: bool
    public_mode: AlePublicMode = AlePublicMode.MASK
    index_normalizer: Callable[[str], str] | None = None


def _mask(name: str, *, searchable: bool = False) -> AleFieldPolicy:
    return AleFieldPolicy(
        name=name, encrypt=True, searchable=searchable, public_mode=AlePublicMode.MASK
    )


def _blind_index(
    name: str,
    *,
    searchable: bool = True,
    normalizer: Callable[[str], str] | None = None,
) -> AleFieldPolicy:
    return AleFieldPolicy(
        name=name,
        encrypt=True,
        searchable=searchable,
        public_mode=AlePublicMode.BLIND_INDEX,
        index_normalizer=normalizer,
    )


def _zero(name: str, *, searchable: bool = False) -> AleFieldPolicy:
    return AleFieldPolicy(
        name=name, encrypt=True, searchable=searchable, public_mode=AlePublicMode.ZERO
    )


CLIENT_ALE_POLICIES: tuple[AleFieldPolicy, ...] = (
    _mask("family_name", searchable=True),
    _blind_index("phone", searchable=True, normalizer=phone_digits),
    _mask("remarks", searchable=False),
)


LISTING_ALE_POLICIES: tuple[AleFieldPolicy, ...] = (
    _mask("family_name", searchable=True),
    _blind_index("phone", searchable=True, normalizer=phone_digits),
    _mask("remarks", searchable=False),
)


DEMANDE_ALE_POLICIES: tuple[AleFieldPolicy, ...] = (
    _mask("remarks", searchable=False),
    _mask("locations", searchable=False),
)


OFFER_ALE_POLICIES: tuple[AleFieldPolicy, ...] = (
    _mask("remarks", searchable=False),
    _mask("location", searchable=False),
)


CRM_CONTRACT_ALE_POLICIES: tuple[AleFieldPolicy, ...] = (
    _zero("amount", searchable=False),
    _zero("deposit", searchable=False),
    _mask("terms", searchable=False),
    _mask("notes", searchable=False),
)


CRM_VISIT_ALE_POLICIES: tuple[AleFieldPolicy, ...] = (_mask("notes", searchable=False),)

REGISTRATION_REQUEST_ALE_POLICIES: tuple[AleFieldPolicy, ...] = (
    _mask("owner_first_name", searchable=False),
    _mask("owner_last_name", searchable=False),
    _mask("owner_phone", searchable=False),
    _mask("agency_name", searchable=False),
    _mask("legal_name", searchable=False),
    _mask("registry_number", searchable=False),
    _mask("agency_address", searchable=False),
    _mask("agency_city", searchable=False),
    _mask("agency_postal_code", searchable=False),
)

USER_INVITE_ALE_POLICIES: tuple[AleFieldPolicy, ...] = (_mask("invite_name", searchable=False),)

AGENCY_ALE_POLICIES: tuple[AleFieldPolicy, ...] = (
    _blind_index("phone_number", searchable=True, normalizer=phone_digits),
    _mask("address_line1", searchable=False),
    _mask("address_line2", searchable=False),
    _mask("city", searchable=False),
)

USER_ALE_POLICIES: tuple[AleFieldPolicy, ...] = (
    _mask("first_name", searchable=True),
    _mask("last_name", searchable=True),
    _mask("mfa_totp_secret", searchable=False),
)


def as_policies(policies: Sequence[AleFieldPolicy]) -> tuple[AleFieldPolicy, ...]:
    """Normalize policy collections to an immutable tuple."""

    return tuple(policies)


__all__ = [
    "AleFieldPolicy",
    "AlePublicMode",
    "CLIENT_ALE_POLICIES",
    "REGISTRATION_REQUEST_ALE_POLICIES",
    "USER_INVITE_ALE_POLICIES",
    "AGENCY_ALE_POLICIES",
    "USER_ALE_POLICIES",
    "CRM_CONTRACT_ALE_POLICIES",
    "CRM_VISIT_ALE_POLICIES",
    "DEMANDE_ALE_POLICIES",
    "LISTING_ALE_POLICIES",
    "OFFER_ALE_POLICIES",
    "as_policies",
]
