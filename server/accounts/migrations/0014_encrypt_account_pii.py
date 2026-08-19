from __future__ import annotations

from django.db import migrations


def _is_masked(value: str) -> bool:
    return value.startswith("\u0001\u0002[ALE:ENC]\u0003\u0004") or value.startswith(
        "\u0001\u0002[ALE:BIDX]\u0003\u0004"
    )


def _forward_encrypt_account_pii(apps, schema_editor) -> None:
    _ = schema_editor
    try:
        from core.blind_index import blind_index_for_agency
        from core.encryption import get_encryption_service
        from core.utils.common import phone_digits, sanitize_text
    except Exception:
        return

    try:
        enc = get_encryption_service()
    except Exception:
        return

    Agency = apps.get_model("accounts", "Agency")
    User = apps.get_model("accounts", "User")

    mask_enc = "\u0001\u0002[ALE:ENC]\u0003\u0004"
    mask_bidx_prefix = "\u0001\u0002[ALE:BIDX]\u0003\u0004"

    for agency in Agency.objects.all().iterator(chunk_size=200):
        update_fields: list[str] = []

        phone = str(getattr(agency, "phone_number", "") or "").strip()
        phone_enc = str(getattr(agency, "phone_number_enc", "") or "").strip()
        if phone and not phone_enc and not _is_masked(phone):
            digits = phone_digits(phone)
            if digits:
                agency.phone_number = mask_bidx_prefix + blind_index_for_agency(
                    digits, agency_id=int(agency.id)
                )
            else:
                agency.phone_number = mask_enc
            agency.phone_number_enc = enc.encrypt(phone)
            update_fields.extend(["phone_number", "phone_number_enc"])

        for field_name in ("address_line1", "address_line2", "city"):
            field_value = str(getattr(agency, field_name, "") or "").strip()
            enc_name = f"{field_name}_enc"
            field_enc = str(getattr(agency, enc_name, "") or "").strip()
            if field_value and not field_enc and not _is_masked(field_value):
                setattr(agency, field_name, mask_enc)
                setattr(agency, enc_name, enc.encrypt(field_value))
                update_fields.extend([field_name, enc_name])

        if update_fields:
            agency.save(update_fields=list(dict.fromkeys(update_fields)))

    for user in User.objects.all().iterator(chunk_size=500):
        update_fields: list[str] = []

        first_name = str(getattr(user, "first_name", "") or "").strip()
        first_name_enc = str(getattr(user, "first_name_enc", "") or "").strip()
        if first_name and not first_name_enc and not _is_masked(first_name):
            user.first_name = mask_enc
            user.first_name_enc = enc.encrypt(first_name)
            user.first_name_search_src = sanitize_text(first_name)
            update_fields.extend(["first_name", "first_name_enc", "first_name_search_src"])

        last_name = str(getattr(user, "last_name", "") or "").strip()
        last_name_enc = str(getattr(user, "last_name_enc", "") or "").strip()
        if last_name and not last_name_enc and not _is_masked(last_name):
            user.last_name = mask_enc
            user.last_name_enc = enc.encrypt(last_name)
            user.last_name_search_src = sanitize_text(last_name)
            update_fields.extend(["last_name", "last_name_enc", "last_name_search_src"])

        mfa_secret = str(getattr(user, "mfa_totp_secret", "") or "").strip()
        mfa_secret_enc = str(getattr(user, "mfa_totp_secret_enc", "") or "").strip()
        if mfa_secret and not mfa_secret_enc and not _is_masked(mfa_secret):
            user.mfa_totp_secret = mask_enc
            user.mfa_totp_secret_enc = enc.encrypt(mfa_secret)
            update_fields.extend(["mfa_totp_secret", "mfa_totp_secret_enc"])

        if update_fields:
            user.save(update_fields=list(dict.fromkeys(update_fields)))


def _reverse_noop(apps, schema_editor) -> None:
    _ = (apps, schema_editor)


class Migration(migrations.Migration):
    dependencies = [
        ("accounts", "0013_agency_address_line1_enc_agency_address_line2_enc_and_more"),
    ]

    operations = [
        migrations.RunPython(_forward_encrypt_account_pii, _reverse_noop),
    ]
