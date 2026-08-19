"""User service input types."""

from __future__ import annotations

from typing import TypedDict


class UserCreateInput(TypedDict, total=False):
    username: str
    password: str
    role: str
    is_owner: bool
    manager_id: int | None
    email: str
    first_name: str
    last_name: str
    is_active: bool
    can_import: bool
    can_hard_delete: bool
    agency_id: int | None


class UserUpdateInput(TypedDict, total=False):
    password: str
    role: str
    is_owner: bool
    manager_id: int | None
    email: str
    first_name: str
    last_name: str
    is_active: bool
    can_import: bool
    can_hard_delete: bool
    agency_id: int | None


__all__ = ["UserCreateInput", "UserUpdateInput"]
