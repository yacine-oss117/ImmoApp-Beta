"""Shared typing aliases for API client calls."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import IO, TypeAlias

ParamValue: TypeAlias = str | bytes | int | float | Iterable[str | bytes | int | float] | None
RequestParams: TypeAlias = Mapping[str, ParamValue]
ParamsDict: TypeAlias = dict[str, ParamValue]

FileName: TypeAlias = str | None
FileContent: TypeAlias = IO[str | bytes] | str | bytes
FileContentType: TypeAlias = str
FileHeaders: TypeAlias = Mapping[str, str]
FileSpec: TypeAlias = (
    FileContent
    | tuple[FileName, FileContent]
    | tuple[FileName, FileContent, FileContentType]
    | tuple[FileName, FileContent, FileContentType, FileHeaders]
)
RequestFiles: TypeAlias = Mapping[str, FileSpec] | Iterable[tuple[str, FileSpec]]

__all__ = [
    "ParamValue",
    "RequestParams",
    "ParamsDict",
    "FileName",
    "FileContent",
    "FileContentType",
    "FileHeaders",
    "FileSpec",
    "RequestFiles",
]
