"""User management service facade."""

from __future__ import annotations

from .users_mutations import create_user, deactivate_user, update_user
from .users_queries import (
    get_user_detail,
    get_users_surface_generation,
    list_users,
    list_users_page,
)
from .users_types import UserCreateInput, UserUpdateInput

__all__ = [
    "UserCreateInput",
    "UserUpdateInput",
    "create_user",
    "deactivate_user",
    "get_user_detail",
    "get_users_surface_generation",
    "list_users",
    "list_users_page",
    "update_user",
]
