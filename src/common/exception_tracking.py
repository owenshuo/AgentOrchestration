"""Sanitized exception event helpers for task error tracking."""

from collections.abc import Mapping, Sequence
from typing import Any, Dict, Optional

SAFE_FIELD_NAMES = {
    "agent_id",
    "component",
    "error_class",
    "error_type",
    "execution_id",
    "id",
    "phase",
    "request_id",
    "task_id",
    "target_agent",
}

SENSITIVE_FIELD_NAMES = {
    "api_key",
    "args",
    "authorization",
    "body",
    "config",
    "context",
    "cookie",
    "headers",
    "kwargs",
    "local_variables",
    "locals",
    "password",
    "payload",
    "raw",
    "raw_body",
    "raw_payload",
    "request",
    "response",
    "secret",
    "secrets",
    "token",
    "variables",
}

REDACTED = "[redacted]"


def _normalize_key(key: Any) -> str:
    return str(key).lower().replace("-", "_")


def _safe_scalar(value: Any) -> bool:
    return value is None or isinstance(value, (str, int, float, bool))


def _first_present(*values: Any) -> Any:
    for value in values:
        if value:
            return value
    return None


def sanitize_exception_context(
    context: Optional[Mapping[str, Any]],
) -> Dict[str, Any]:
    """Return an allowlisted exception context without raw payload data."""
    if not context:
        return {}
    sanitized = _sanitize_mapping(context)
    return sanitized if isinstance(sanitized, dict) else {}


def build_exception_event(
    error: BaseException,
    *,
    task: Optional[Mapping[str, Any]] = None,
    context: Optional[Mapping[str, Any]] = None,
) -> Dict[str, Any]:
    """Build the safe event used by logs, executor results, and hooks."""
    event: Dict[str, Any] = {"error_class": error.__class__.__name__}

    task = task or {}
    context = context or {}
    task_id = _first_present(
        task.get("id"),
        task.get("task_id"),
        context.get("task_id"),
        context.get("id"),
    )
    if task_id is not None:
        event["task_id"] = task_id

    agent_id = _first_present(
        task.get("agent_id"),
        task.get("target_agent"),
        context.get("agent_id"),
    )
    if agent_id is not None:
        event["agent_id"] = agent_id

    execution_id = context.get("execution_id")
    if execution_id is not None:
        event["execution_id"] = execution_id

    sanitized_context = sanitize_exception_context(context)
    if sanitized_context:
        event["context"] = sanitized_context

    return event


def _sanitize_mapping(value: Mapping[str, Any]) -> Dict[str, Any]:
    sanitized: Dict[str, Any] = {}
    for key, child in value.items():
        normalized_key = _normalize_key(key)
        output_key = str(key)

        if normalized_key in SENSITIVE_FIELD_NAMES:
            sanitized[output_key] = REDACTED
            continue

        if normalized_key in SAFE_FIELD_NAMES:
            sanitized_child = _sanitize_value(child)
            if sanitized_child is not None:
                sanitized[output_key] = sanitized_child
            continue

        if isinstance(child, Mapping):
            nested = _sanitize_mapping(child)
            if nested:
                sanitized[output_key] = nested
            continue

        if isinstance(child, Sequence) and not isinstance(
            child,
            (str, bytes, bytearray),
        ):
            nested_items = [_sanitize_value(item) for item in child]
            nested_items = [item for item in nested_items if item is not None]
            if nested_items:
                sanitized[output_key] = nested_items

    return sanitized


def _sanitize_value(value: Any) -> Any:
    if _safe_scalar(value):
        return value
    if isinstance(value, Mapping):
        return _sanitize_mapping(value)
    if isinstance(value, Sequence) and not isinstance(
        value,
        (str, bytes, bytearray),
    ):
        sanitized = [_sanitize_value(item) for item in value]
        return [item for item in sanitized if item is not None]
    return None
