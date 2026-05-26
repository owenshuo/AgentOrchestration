"""Notification toast rendering helpers."""

from dataclasses import dataclass
from html import escape
from typing import Dict, Optional


TOAST_MESSAGES: Dict[str, str] = {
    "success": "completed",
    "failure": "failed",
    "info": "updated",
    "warning": "needs attention",
}


@dataclass(frozen=True)
class ToastMessage:
    variant: str
    task_name: str
    detail: Optional[str] = None

    def to_text(self) -> str:
        verb = _toast_verb(self.variant)
        message = f"Task {self.task_name} {verb}."
        if self.detail:
            message = f"{message} {self.detail}"
        return message

    def to_html(self) -> str:
        verb = _toast_verb(self.variant)
        safe_variant = escape(self.variant, quote=True)
        safe_name = escape(str(self.task_name), quote=True)
        detail = ""
        if self.detail:
            detail = (
                '<span class="toast__detail">'
                f"{escape(str(self.detail), quote=True)}"
                "</span>"
            )

        return (
            f'<div class="toast toast--{safe_variant}" role="status">'
            f'Task <strong>{safe_name}</strong> {verb}.'
            f"{detail}"
            "</div>"
        )


def render_task_toast(
    task_name: str,
    variant: str = "success",
    detail: Optional[str] = None,
) -> str:
    return ToastMessage(
        variant=variant,
        task_name=task_name,
        detail=detail,
    ).to_html()


def render_task_toast_text(
    task_name: str,
    variant: str = "success",
    detail: Optional[str] = None,
) -> str:
    return ToastMessage(
        variant=variant,
        task_name=task_name,
        detail=detail,
    ).to_text()


def _toast_verb(variant: str) -> str:
    try:
        return TOAST_MESSAGES[variant]
    except KeyError as error:
        raise ValueError("unsupported toast variant") from error
