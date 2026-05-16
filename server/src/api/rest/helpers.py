"""
REST API helper functions for response building and error handling.
"""

import json
import uuid
from datetime import datetime, timezone
from functools import wraps
from typing import Any

from aiohttp import web
import peewee

from ...db.db import db
from ...db.models.rest_ext.event_log import EventLog


def serialize_datetime(dt: datetime | str) -> str:
    """
    Serialize datetime to ISO format string.

    Peewee with SQLite sometimes returns DateTimeField as string instead of datetime object.
    This helper handles both cases consistently.

    Args:
        dt: datetime object or ISO string

    Returns:
        ISO format string (with timezone if datetime had it)
    """
    if isinstance(dt, str):
        return dt
    return dt.isoformat()


# Standard HTTP status codes
HTTP_OK = 200
HTTP_CREATED = 201
HTTP_BAD_REQUEST = 400
HTTP_UNAUTHORIZED = 401
HTTP_FORBIDDEN = 403
HTTP_NOT_FOUND = 404
HTTP_CONFLICT = 409
HTTP_INTERNAL_ERROR = 500


def ok(data: Any = None, status: int = HTTP_OK) -> web.Response:
    """
    Build a successful JSON response.

    Args:
        data: Response payload (will be JSON serialized)
        status: HTTP status code (default 200)

    Returns:
        aiohttp Response with JSON content
    """
    payload = {"success": True}
    if data is not None:
        payload["data"] = data

    return web.json_response(payload, status=status)


def error(
    message: str,
    code: str = "ERROR",
    status: int = HTTP_BAD_REQUEST,
    details: Any = None,
) -> web.Response:
    """
    Build an error JSON response.

    Args:
        message: Human-readable error message
        code: Error code (e.g., "UNAUTHORIZED", "NOT_FOUND", "VALIDATION_ERROR")
        status: HTTP status code (default 400)
        details: Optional additional error details

    Returns:
        aiohttp Response with error JSON
    """
    payload = {
        "success": False,
        "error": {
            "message": message,
            "code": code,
        },
    }
    if details is not None:
        payload["error"]["details"] = details

    return web.json_response(payload, status=status)


def require_role(*allowed_roles: str):
    """
    Decorator to enforce role-based access control (RBAC).

    Usage:
        @require_role("dm")
        async def dm_only_endpoint(request):
            ...

        @require_role("dm", "player")
        async def all_users_endpoint(request):
            ...

    Args:
        allowed_roles: Variable number of allowed role names ("dm", "player")

    Returns:
        Decorated function that checks role before executing
    """
    def decorator(handler):
        @wraps(handler)
        async def wrapper(request: web.Request):
            # Get API key from request (set by middleware)
            api_key = request.get("api_key")
            if not api_key:
                return error(
                    "Authentication required",
                    code="UNAUTHORIZED",
                    status=HTTP_UNAUTHORIZED,
                )

            # Check role
            if api_key.role not in allowed_roles:
                return error(
                    f"Insufficient permissions. Required role: {', '.join(allowed_roles)}",
                    code="FORBIDDEN",
                    status=HTTP_FORBIDDEN,
                )

            # Role check passed, execute handler
            return await handler(request)

        return wrapper
    return decorator


async def log_event(
    event_type: str,
    payload: dict[str, Any],
    scene_id: str | None = None,
    actor_id: str | None = None,
    combat_id: str | None = None,
    action_id: str | None = None,
) -> EventLog:
    """
    Log an event to the event log (audit trail) and broadcast to SSE subscribers.

    Args:
        event_type: Event type (e.g., "token_created", "combat_started", "hp_changed")
        payload: Event data (will be JSON serialized)
        scene_id: Optional scene UUID
        actor_id: Optional actor (token/shape) UUID
        combat_id: Optional combat UUID
        action_id: Optional action UUID

    Returns:
        EventLog record created
    """
    # Import models
    from ...db.models.location import Location
    from ...db.models.shape import Shape
    from ...db.models.rest_ext.combat_ext import CombatExt
    from ...db.models.rest_ext.action_declaration import ActionDeclaration

    # Get scene (Location) if provided
    scene = None
    if scene_id:
        try:
            scene = Location.get_by_id(int(scene_id))
        except (ValueError, Location.DoesNotExist):
            pass

    # Get actor (Shape) if provided
    actor = None
    if actor_id:
        actor = Shape.get_or_none(Shape.uuid == actor_id)

    # Get combat if provided
    combat = None
    if combat_id:
        combat = CombatExt.get_or_none(CombatExt.uuid == combat_id)

    # Get action if provided
    action = None
    if action_id:
        action = ActionDeclaration.get_or_none(ActionDeclaration.uuid == action_id)

    # Get next sequence_id atomically using database transaction
    with db.atomic():
        # Lock the table and get max sequence_id
        max_seq = EventLog.select(peewee.fn.MAX(EventLog.sequence_id)).scalar() or 0
        next_seq = max_seq + 1

        event = EventLog.create(
            uuid=str(uuid.uuid4()),
            event_type=event_type,
            payload=json.dumps(payload),
            scene=scene,
            actor=actor,
            combat=combat,
            action=action,
            sequence_id=next_seq,
            created_at=datetime.now(timezone.utc),
        )

    # Broadcast to SSE subscribers
    # Import here to avoid circular dependency
    from .events import _push_sse

    event_data = {
        "uuid": event.uuid,
        "event_type": event.event_type,
        "scene_id": event.scene.id if event.scene else None,
        "actor_id": event.actor.uuid if event.actor else None,
        "combat_id": event.combat.uuid if event.combat else None,
        "action_id": event.action.uuid if event.action else None,
        "payload": json.loads(event.payload),
        "created_at": serialize_datetime(event.created_at),
        "sequence_id": event.sequence_id,
    }

    # Push to SSE subscribers (fire and forget, don't block)
    try:
        await _push_sse(event_data)
    except Exception:
        # Don't fail event logging if SSE broadcast fails
        pass

    return event
