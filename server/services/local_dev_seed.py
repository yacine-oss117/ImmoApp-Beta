from __future__ import annotations

from server.accounts.models import Agency, User


def _get_or_create_local_user(
    *,
    username: str,
    password: str,
    defaults: dict[str, object],
) -> tuple[User, bool]:
    try:
        return User.objects.get(username=username), False
    except User.DoesNotExist:
        user = User(username=username, **defaults)
        user.set_password(password)
        user.save(validate=False)
        return user, True


def seed_local_dev_identities() -> list[str]:
    messages: list[str] = []

    agency, agency_created = Agency.objects.update_or_create(
        agency_code="DEF001",
        defaults={
            "legal_name": "Default Agency",
            "display_name": "Default Agency",
            "is_active": True,
        },
    )
    if agency_created:
        messages.append("Created Agency 'DEF001'")
    else:
        messages.append("Agency 'DEF001' already exists")

    _admin_user, admin_created = _get_or_create_local_user(
        username="admin",
        password="admin",
        defaults={
            "email": "admin@example.com",
            "role": User.ROLE_SUPER_ADMIN,
            "is_owner": False,
            "is_staff": True,
            "is_superuser": True,
            "is_active": True,
        },
    )
    if admin_created:
        messages.append("Created super admin 'admin'")
    else:
        messages.append("Super admin 'admin' already exists")

    _owner, owner_created = _get_or_create_local_user(
        username="owner",
        password="admin",
        defaults={
            "email": "owner@example.com",
            "role": User.ROLE_MANAGER,
            "agency": agency,
            "access_scope": User.SCOPE_AGENCY,
            "is_owner": True,
            "can_import": True,
            "can_hard_delete": True,
            "is_staff": True,
            "is_active": True,
        },
    )
    if owner_created:
        messages.append("Created local owner 'owner'")
    else:
        messages.append("Local owner 'owner' already exists")

    return messages


__all__ = ["seed_local_dev_identities"]
