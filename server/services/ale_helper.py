from collections.abc import Collection, Sequence
from typing import Any

from core.ale_utils import (
    LEGACY_MASK_BIDX_PREFIX,
    LEGACY_MASK_ENC,
    MASK_BIDX_PREFIX,
    MASK_ENC,
    is_legacy_ale_mask,
    is_structured_ale_mask,
)
from core.blind_index import blind_index_for_write
from core.encryption import get_encryption_service
from core.utils.common import sanitize_text

from .ale_policy import AleFieldPolicy, AlePublicMode

FieldConfig = AleFieldPolicy | tuple[str, bool, bool]


def _coerce_policy(config: FieldConfig) -> AleFieldPolicy:
    if isinstance(config, AleFieldPolicy):
        return config
    name, encrypt, searchable = config
    return AleFieldPolicy(name=name, encrypt=encrypt, searchable=searchable)


def _public_value(
    policy: AleFieldPolicy,
    clean_value: str,
    *,
    agency_id: int | None = None,
) -> str | float | None:
    if policy.public_mode == AlePublicMode.ZERO:
        return 0.0
    if policy.public_mode == AlePublicMode.BLIND_INDEX:
        source = policy.index_normalizer(clean_value) if policy.index_normalizer else clean_value
        if not source:
            return None
        return MASK_BIDX_PREFIX + blind_index_for_write(source, agency_id=agency_id)
    return MASK_ENC


def _clear_field(processed: dict[str, Any], policy: AleFieldPolicy) -> None:
    processed[policy.name] = None if policy.public_mode == AlePublicMode.ZERO else ""
    if policy.encrypt:
        processed[policy.name + "_enc"] = ""
    if policy.searchable:
        processed[policy.name + "_search_src"] = ""


def normalize_ale_fields(
    processed: dict[str, Any],
    field_configs: Sequence[FieldConfig],
    *,
    changed_fields: Collection[str] | None = None,
    agency_id: int | None = None,
) -> None:
    """
    Ruthlessly hardens ALE processing.

    Ensures:
    1. Invisible Collision-Proof Masks.
    2. XSS Sanitization (Bleach-powered).
    3. Field-aware Normalization (Phone digits index sync).
    4. Reliable Deduplication.
    """
    enc = get_encryption_service()
    policies = tuple(_coerce_policy(config) for config in field_configs)

    for policy in policies:
        name = policy.name
        encrypt_it = policy.encrypt
        searchable = policy.searchable
        val = processed.get(name)
        provided = changed_fields is None or name in changed_fields

        # 1. Handle NULL/None/Undefined
        if val is None:
            _clear_field(processed, policy)
            continue

        # 2. String conversion
        val_str = str(val).strip()

        # 3. Handle Empty String
        if not val_str:
            _clear_field(processed, policy)
            continue

        # 4. Handle Existing ALE Masks (DEDUPLICATION)
        if is_structured_ale_mask(val_str):
            if encrypt_it and processed.get(name + "_enc"):
                processed[name] = _public_value(policy, "", agency_id=agency_id)
                continue

            # Non-printable mask without ciphertext is spoofing / corruption.
            _clear_field(processed, policy)
            continue

        if is_legacy_ale_mask(val_str) and encrypt_it and processed.get(name + "_enc"):
            # Legacy masked value persisted from an older release; canonicalize marker.
            if policy.public_mode == AlePublicMode.BLIND_INDEX and val_str.startswith(
                LEGACY_MASK_BIDX_PREFIX
            ):
                processed[name] = MASK_BIDX_PREFIX + val_str[len(LEGACY_MASK_BIDX_PREFIX) :]
            elif policy.public_mode == AlePublicMode.MASK and val_str == LEGACY_MASK_ENC:
                processed[name] = MASK_ENC
            else:
                processed[name] = _public_value(policy, "", agency_id=agency_id)
            continue

        # Legacy printable strings without ciphertext are treated as fresh user input.

        # 5. Sanitize (PREVENT XSS) for indexing/display, preserve raw for encryption
        clean_val = sanitize_text(val_str)

        # If field was not provided and encrypted value exists, preserve ciphertext.
        if not provided and encrypt_it and processed.get(name + "_enc"):
            processed[name] = _public_value(policy, clean_val, agency_id=agency_id)
            if searchable:
                # Preserve existing DB search index for untouched encrypted fields.
                processed[name + "_search_src"] = None
            continue

        # 6. Apply Masking (Public columns)
        processed[name] = _public_value(policy, clean_val, agency_id=agency_id)

        # 7. Encryption (store raw; sanitize on output)
        if encrypt_it:
            processed[name + "_enc"] = enc.encrypt(val_str)

        # 8. Search indexing source. DB computes hash trigrams via pg_trgm function.
        if searchable:
            processed[name + "_search_src"] = clean_val
