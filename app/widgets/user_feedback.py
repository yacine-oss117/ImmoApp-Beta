from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from app.services.api_client import ApiError
from app.utils.i18n import tr_factory
from app.widgets.notice_banner import NoticeBanner

_TR = tr_factory("UserFeedback")


@dataclass(frozen=True)
class UserFacingMessage:
    title: str
    message: str
    severity: Literal["info", "success", "warning", "error"]
    action_hint: str | None = None
    technical_detail: str | None = None


@dataclass
class ActionFeedbackState:
    current: UserFacingMessage | None = None
    auto_dismiss_ms: int | None = None


def show_user_message(
    banner: NoticeBanner,
    message: UserFacingMessage,
    *,
    auto_dismiss_ms: int | None = None,
) -> None:
    body = message.message
    if message.action_hint:
        body = f"{body} {message.action_hint}".strip()
    banner.show_notice(
        state=message.severity,
        title=message.title,
        body=body,
        show_details=bool(message.technical_detail),
        auto_dismiss_ms=auto_dismiss_ms,
    )


def build_success_message(*, title: str, message: str) -> UserFacingMessage:
    return UserFacingMessage(title=title, message=message, severity="success")


def build_info_message(*, title: str, message: str) -> UserFacingMessage:
    return UserFacingMessage(title=title, message=message, severity="info")


def map_exception_to_user_message(exc: Exception, *, context: str) -> UserFacingMessage:
    detail = str(exc).strip() or None
    if isinstance(exc, ApiError):
        if exc.status_code in (400, 409):
            return _validation_message(context, detail or exc.message or None)
        if exc.status_code in (401, 403):
            return _permission_message(context, detail or exc.message or None)
        if exc.status_code >= 500:
            return _server_message(context, detail or exc.message or None)
        return _generic_action_message(context, detail or exc.message or None)
    if isinstance(exc, ValueError):
        return _validation_message(context, detail)
    if isinstance(exc, RuntimeError):
        return _server_message(context, detail)
    return _generic_action_message(context, detail)


def _validation_message(context: str, detail: str | None) -> UserFacingMessage:
    if context.startswith("match.action"):
        return UserFacingMessage(
            title=_TR("Action needs attention"),
            message=_TR("That client or property selection is no longer valid."),
            severity="warning",
            action_hint=_TR("Refresh the page and try again."),
            technical_detail=detail,
        )
    if context.startswith("crm.visits"):
        return UserFacingMessage(
            title=_TR("Visit needs attention"),
            message=_TR("We couldn't update this visit with the current details."),
            severity="warning",
            action_hint=_TR("Check the details and try again."),
            technical_detail=detail,
        )
    if context.startswith("crm.contracts"):
        return UserFacingMessage(
            title=_TR("Contract needs attention"),
            message=_TR("We couldn't update this contract with the current details."),
            severity="warning",
            action_hint=_TR("Refresh the page and try again."),
            technical_detail=detail,
        )
    return UserFacingMessage(
        title=_TR("Some details need attention"),
        message=_TR("We couldn't finish that action with the current information."),
        severity="warning",
        action_hint=_TR("Check the details and try again."),
        technical_detail=detail,
    )


def _permission_message(context: str, detail: str | None) -> UserFacingMessage:
    if context.startswith("match"):
        title = _TR("Match workspace needs a refresh")
    elif context.startswith("crm"):
        title = _TR("Follow-up workspace needs a refresh")
    else:
        title = _TR("Session needs attention")
    return UserFacingMessage(
        title=title,
        message=_TR("Your session or permissions changed while this page was open."),
        severity="warning",
        action_hint=_TR("Refresh and try again."),
        technical_detail=detail,
    )


def _server_message(context: str, detail: str | None) -> UserFacingMessage:
    if context.startswith("crm.visits.refresh"):
        title = _TR("Couldn't load visits")
        message = _TR("Visits are not available right now.")
    elif context.startswith("crm.visits"):
        title = _TR("We couldn't update this visit")
        message = _TR("The visit wasn't changed yet.")
    elif context.startswith("crm.contracts.refresh"):
        title = _TR("Couldn't load contracts")
        message = _TR("Contracts are not available right now.")
    elif context.startswith("crm.contracts"):
        title = _TR("We couldn't update this contract")
        message = _TR("The contract wasn't changed yet.")
    elif context.startswith("crm"):
        title = _TR("We couldn't finish this follow-up action")
        message = _TR("Nothing was updated yet.")
    elif context.startswith("match.run"):
        title = _TR("Match run didn't finish")
        message = _TR("We couldn't finish matching right now.")
    elif context.startswith("match"):
        title = _TR("We couldn't finish this match action")
        message = _TR("Nothing was changed yet.")
    else:
        title = _TR("We couldn't finish that action")
        message = _TR("Please try again.")
    return UserFacingMessage(
        title=title,
        message=message,
        severity="error",
        action_hint=_TR("Please try again in a moment."),
        technical_detail=detail,
    )


def _generic_action_message(context: str, detail: str | None) -> UserFacingMessage:
    if context.startswith("crm"):
        title = _TR("We couldn't update follow-up right now")
    elif context.startswith("match"):
        title = _TR("We couldn't finish that match action")
    else:
        title = _TR("We couldn't finish that action")
    return UserFacingMessage(
        title=title,
        message=_TR("Please try again."),
        severity="error",
        technical_detail=detail,
    )


__all__ = [
    "ActionFeedbackState",
    "UserFacingMessage",
    "build_info_message",
    "build_success_message",
    "map_exception_to_user_message",
    "show_user_message",
]
