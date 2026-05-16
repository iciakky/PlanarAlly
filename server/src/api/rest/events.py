"""
Event log query and manual note endpoints.

Provides audit trail for all game actions with filtering and pagination.
"""

import asyncio
import json
from datetime import datetime, timezone
from typing import Any

from aiohttp import web

from ...db.models.rest_ext.event_log import EventLog
from .helpers import error, ok, require_role, log_event, serialize_datetime, HTTP_BAD_REQUEST, HTTP_INTERNAL_ERROR


# SSE subscriber management
# Global dictionary mapping connection_id -> (queue, subscriber_info)
# subscriber_info: {"role": str, "accessible_scene_ids": set[int]}
_sse_subscribers: dict[str, tuple[asyncio.Queue, dict]] = {}


@require_role("dm", "player")
async def query_events(request: web.Request) -> web.Response:
    """
    GET /api/v1/events - Query event log with filters and pagination.

    Query parameters:
        - scene_id (optional): Filter by scene UUID (Location ID)
        - actor_id (optional): Filter by actor UUID (Shape UUID)
        - combat_id (optional): Filter by combat UUID
        - action_id (optional): Filter by action UUID
        - type (optional): Filter by event type (e.g., "token_created", "hp_changed")
        - after (optional): ISO timestamp - events after this time
        - before (optional): ISO timestamp - events before this time
        - limit (optional): Max results to return (default 50, max 500)
        - offset (optional): Number of results to skip for pagination (default 0)

    Returns:
        200: List of events with pagination metadata
        400: Invalid query parameters
    """
    try:
        # Import models for filtering
        from ...db.models.shape import Shape
        from ...db.models.rest_ext.combat_ext import CombatExt
        from ...db.models.rest_ext.action_declaration import ActionDeclaration

        # Parse query parameters
        scene_id = request.query.get("scene_id")
        actor_id = request.query.get("actor_id")
        combat_id = request.query.get("combat_id")
        action_id = request.query.get("action_id")
        event_type = request.query.get("type")
        after_str = request.query.get("after")
        before_str = request.query.get("before")
        limit = min(int(request.query.get("limit", "50")), 500)
        offset = int(request.query.get("offset", "0"))

        # Build query
        query = EventLog.select().order_by(EventLog.created_at.desc())

        # Apply filters
        if scene_id:
            query = query.where(EventLog.scene == int(scene_id))
        if actor_id:
            actor = Shape.get_or_none(Shape.uuid == actor_id)
            if actor is None:
                return ok({"events": [], "total_count": 0, "limit": limit, "offset": offset, "has_more": False})
            query = query.where(EventLog.actor == actor)
        if combat_id:
            combat = CombatExt.get_or_none(CombatExt.uuid == combat_id)
            if combat is None:
                return ok({"events": [], "total_count": 0, "limit": limit, "offset": offset, "has_more": False})
            query = query.where(EventLog.combat == combat)
        if action_id:
            action = ActionDeclaration.get_or_none(ActionDeclaration.uuid == action_id)
            if action is None:
                return ok({"events": [], "total_count": 0, "limit": limit, "offset": offset, "has_more": False})
            query = query.where(EventLog.action == action)
        if event_type:
            query = query.where(EventLog.event_type == event_type)

        # Parse and apply time filters
        if after_str:
            try:
                after_dt = datetime.fromisoformat(after_str.replace("Z", "+00:00"))
                query = query.where(EventLog.created_at >= after_dt)
            except ValueError:
                return error(
                    f"Invalid 'after' timestamp format: {after_str}. Use ISO format (e.g., 2026-02-11T10:00:00Z)",
                    code="VALIDATION_ERROR",
                    status=HTTP_BAD_REQUEST,
                )

        if before_str:
            try:
                before_dt = datetime.fromisoformat(before_str.replace("Z", "+00:00"))
                query = query.where(EventLog.created_at <= before_dt)
            except ValueError:
                return error(
                    f"Invalid 'before' timestamp format: {before_str}. Use ISO format (e.g., 2026-02-11T10:00:00Z)",
                    code="VALIDATION_ERROR",
                    status=HTTP_BAD_REQUEST,
                )

        # Get total count before pagination
        total_count = query.count()

        # Apply pagination
        events = list(query.limit(limit).offset(offset))

        # Serialize events
        event_list = []
        for event in events:
            event_data = {
                "uuid": event.uuid,
                "event_type": event.event_type,
                "scene_id": event.scene.id if event.scene else None,
                "actor_id": event.actor.uuid if event.actor else None,
                "combat_id": event.combat.uuid if event.combat else None,
                "action_id": event.action.uuid if event.action else None,
                "payload": event.get_payload(),
                "created_at": serialize_datetime(event.created_at),
                "sequence_id": event.sequence_id,
            }
            event_list.append(event_data)

        return ok({
            "events": event_list,
            "total_count": total_count,
            "limit": limit,
            "offset": offset,
            "has_more": (offset + len(event_list)) < total_count,
        })

    except ValueError as e:
        return error(
            f"Invalid query parameter: {str(e)}",
            code="VALIDATION_ERROR",
            status=HTTP_BAD_REQUEST,
        )
    except Exception as e:
        return error(
            f"Failed to query events: {str(e)}",
            code="INTERNAL_ERROR",
            status=HTTP_INTERNAL_ERROR,
        )


@require_role("dm")
async def create_dm_note(request: web.Request) -> web.Response:
    """
    POST /api/v1/events/note - Create a manual DM note in the event log.

    Request body:
        {
            "note": "string (required)",
            "scene_id": "integer (optional)",
            "actor_id": "string (optional)"
        }

    Returns:
        201: Note created successfully
        400: Missing or invalid request data
    """
    try:
        # Parse request body
        data = await request.json()

        # Validate required fields
        note = data.get("note")
        if not note or not isinstance(note, str):
            return error(
                "Missing or invalid 'note' field (must be non-empty string)",
                code="VALIDATION_ERROR",
                status=HTTP_BAD_REQUEST,
            )

        scene_id = data.get("scene_id")
        actor_id = data.get("actor_id")

        # Create event log entry using log_event helper
        event = await log_event(
            event_type="dm_note",
            payload={"note": note},
            scene_id=str(scene_id) if scene_id else None,
            actor_id=actor_id,
        )

        return ok({
            "uuid": event.uuid,
            "event_type": event.event_type,
            "note": note,
            "scene_id": event.scene.id if event.scene else None,
            "actor_id": event.actor.uuid if event.actor else None,
            "combat_id": event.combat.uuid if event.combat else None,
            "action_id": event.action.uuid if event.action else None,
            "created_at": serialize_datetime(event.created_at),
            "sequence_id": event.sequence_id,
        }, status=201)

    except json.JSONDecodeError:
        return error(
            "Invalid JSON in request body",
            code="VALIDATION_ERROR",
            status=HTTP_BAD_REQUEST,
        )
    except Exception as e:
        return error(
            f"Failed to create DM note: {str(e)}",
            code="INTERNAL_ERROR",
            status=HTTP_INTERNAL_ERROR,
        )


async def _push_sse(event_data: dict[str, Any]) -> None:
    """
    Push an event to SSE subscribers, filtered by scene access.

    DM-role subscribers see all events. Player-role subscribers only see
    events from scenes (locations) in rooms they belong to.
    """
    sse_message = f"data: {json.dumps(event_data)}\n\n"
    event_scene_id = event_data.get("scene_id")

    dead_connections = []
    for conn_id, (queue, sub_info) in _sse_subscribers.items():
        if sub_info["role"] != "dm":
            if event_scene_id is None:
                continue
            if event_scene_id not in sub_info["accessible_scene_ids"]:
                continue

        try:
            await asyncio.wait_for(queue.put(sse_message), timeout=0.1)
        except asyncio.TimeoutError:
            dead_connections.append(conn_id)
        except Exception:
            dead_connections.append(conn_id)

    for conn_id in dead_connections:
        _sse_subscribers.pop(conn_id, None)


@require_role("dm", "player")
async def event_stream(request: web.Request) -> web.StreamResponse:
    """
    GET /api/v1/events/stream - Server-Sent Events (SSE) stream for real-time event monitoring.

    Headers:
        - X-API-Key: API key for authentication
        - Last-Event-ID (optional): For reconnection, provides last received sequence_id

    SSE message format:
        data: {"uuid": "...", "event_type": "...", "payload": {...}, ...}

    Returns:
        200: SSE stream (text/event-stream)
        401: Authentication required
    """
    import uuid as uuid_module
    from ...db.models.player_room import PlayerRoom
    from ...db.models.location import Location

    api_key = request["api_key"]

    # Create unique connection ID
    conn_id = str(uuid_module.uuid4())

    # Build subscriber info for access filtering
    accessible_scene_ids: set[int] = set()
    if api_key.role != "dm":
        for pr in PlayerRoom.select().where(PlayerRoom.player == api_key.user):
            for loc in pr.room.locations:
                accessible_scene_ids.add(loc.id)

    sub_info = {
        "role": api_key.role,
        "accessible_scene_ids": accessible_scene_ids,
    }

    # Create response with SSE headers
    response = web.StreamResponse(
        status=200,
        reason="OK",
        headers={
            "Content-Type": "text/event-stream",
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )

    # Prepare the response
    await response.prepare(request)

    # Create queue for this connection
    queue: asyncio.Queue = asyncio.Queue(maxsize=100)
    _sse_subscribers[conn_id] = (queue, sub_info)

    try:
        # Handle Last-Event-ID for reconnection
        last_event_id = request.headers.get("Last-Event-ID")
        if last_event_id:
            try:
                last_seq = int(last_event_id)
                # Send all events since last_seq
                missed_events = EventLog.select().where(
                    EventLog.sequence_id > last_seq
                ).order_by(EventLog.sequence_id.asc()).limit(100)

                for event in missed_events:
                    event_data = {
                        "uuid": event.uuid,
                        "event_type": event.event_type,
                        "scene_id": event.scene.id if event.scene else None,
                        "actor_id": event.actor.uuid if event.actor else None,
                        "combat_id": event.combat.uuid if event.combat else None,
                        "action_id": event.action.uuid if event.action else None,
                        "payload": event.get_payload(),
                        "created_at": serialize_datetime(event.created_at),
                        "sequence_id": event.sequence_id,
                    }
                    sse_message = f"id: {event.sequence_id}\ndata: {json.dumps(event_data)}\n\n"
                    await response.write(sse_message.encode("utf-8"))

            except (ValueError, EventLog.DoesNotExist):
                pass  # Invalid Last-Event-ID, ignore

        # Send keepalive comment immediately
        await response.write(b": keepalive\n\n")

        # Stream events from queue
        while True:
            try:
                # Wait for next event with timeout for keepalive
                message = await asyncio.wait_for(queue.get(), timeout=30.0)
                await response.write(message.encode("utf-8"))
            except asyncio.TimeoutError:
                # Send keepalive comment every 30 seconds
                await response.write(b": keepalive\n\n")
            except asyncio.CancelledError:
                # Connection closed by client
                break
            except Exception:
                # Other errors, close connection
                break

    finally:
        # Clean up subscriber
        _sse_subscribers.pop(conn_id, None)

    return response


def _empty_export_response(export_format: str) -> web.Response:
    """Return an empty file-download response in the requested export format."""
    export_timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    if export_format == "json":
        body = json.dumps({
            "exported_at": datetime.now(timezone.utc).isoformat(),
            "filters": {},
            "total_events": 0,
            "exported_events": 0,
            "events": [],
        }, indent=2)
        return web.Response(
            body=body,
            content_type="application/json",
            headers={
                "Content-Disposition": f'attachment; filename="events_{export_timestamp}.json"',
                "Cache-Control": "no-cache",
            },
        )
    else:  # txt
        body = "\n".join([
            "=" * 80,
            "PlanarAlly Event Log Export",
            "=" * 80,
            f"Generated: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')}",
            "",
            "No events found matching the specified filters.",
            "",
            "=" * 80,
            "Total Events: 0",
            "=" * 80,
        ])
        return web.Response(
            body=body,
            content_type="text/plain",
            headers={
                "Content-Disposition": f'attachment; filename="events_{export_timestamp}.txt"',
                "Cache-Control": "no-cache",
            },
        )


@require_role("dm", "player")
async def export_events(request: web.Request) -> web.Response:
    """
    GET /api/v1/events/export - Export event log in JSON or TXT format.

    Query parameters:
        - format (required): "json" | "txt"
        - scene_id (optional): Filter by scene UUID (Location ID)
        - actor_id (optional): Filter by actor UUID (Shape UUID)
        - combat_id (optional): Filter by combat UUID
        - action_id (optional): Filter by action UUID
        - type (optional): Filter by event type
        - after (optional): ISO timestamp - events after this time
        - before (optional): ISO timestamp - events before this time
        - limit (optional): Max events to export (default: all, max 10000)

    Returns:
        200: Exported file (JSON or TXT)
        400: Invalid query parameters
    """
    try:
        # Import models for filtering
        from ...db.models.shape import Shape
        from ...db.models.rest_ext.combat_ext import CombatExt
        from ...db.models.rest_ext.action_declaration import ActionDeclaration

        # Validate format parameter
        export_format = request.query.get("format", "").lower()
        if export_format not in ["json", "txt"]:
            return error(
                "Invalid 'format' parameter. Must be 'json' or 'txt'",
                code="VALIDATION_ERROR",
                status=HTTP_BAD_REQUEST,
            )

        # Parse query parameters (same as query_events)
        scene_id = request.query.get("scene_id")
        actor_id = request.query.get("actor_id")
        combat_id = request.query.get("combat_id")
        action_id = request.query.get("action_id")
        event_type = request.query.get("type")
        after_str = request.query.get("after")
        before_str = request.query.get("before")
        limit = min(int(request.query.get("limit", "10000")), 10000)

        # Build query (same filtering logic as query_events)
        query = EventLog.select().order_by(EventLog.created_at.asc())  # Ascending for export

        # Apply filters
        if scene_id:
            query = query.where(EventLog.scene == int(scene_id))
        if actor_id:
            actor = Shape.get_or_none(Shape.uuid == actor_id)
            if actor is None:
                return _empty_export_response(export_format)
            query = query.where(EventLog.actor == actor)
        if combat_id:
            combat = CombatExt.get_or_none(CombatExt.uuid == combat_id)
            if combat is None:
                return _empty_export_response(export_format)
            query = query.where(EventLog.combat == combat)
        if action_id:
            action = ActionDeclaration.get_or_none(ActionDeclaration.uuid == action_id)
            if action is None:
                return _empty_export_response(export_format)
            query = query.where(EventLog.action == action)
        if event_type:
            query = query.where(EventLog.event_type == event_type)

        # Parse and apply time filters
        if after_str:
            try:
                after_dt = datetime.fromisoformat(after_str.replace("Z", "+00:00"))
                query = query.where(EventLog.created_at >= after_dt)
            except ValueError:
                return error(
                    f"Invalid 'after' timestamp format: {after_str}. Use ISO format (e.g., 2026-02-11T10:00:00Z)",
                    code="VALIDATION_ERROR",
                    status=HTTP_BAD_REQUEST,
                )

        if before_str:
            try:
                before_dt = datetime.fromisoformat(before_str.replace("Z", "+00:00"))
                query = query.where(EventLog.created_at <= before_dt)
            except ValueError:
                return error(
                    f"Invalid 'before' timestamp format: {before_str}. Use ISO format (e.g., 2026-02-11T10:00:00Z)",
                    code="VALIDATION_ERROR",
                    status=HTTP_BAD_REQUEST,
                )

        # Get total count before limit
        total_count = query.count()

        # Apply limit
        events = list(query.limit(limit))

        # Serialize events
        event_list = []
        for event in events:
            event_data = {
                "uuid": event.uuid,
                "event_type": event.event_type,
                "scene_id": event.scene.id if event.scene else None,
                "actor_id": event.actor.uuid if event.actor else None,
                "combat_id": event.combat.uuid if event.combat else None,
                "action_id": event.action.uuid if event.action else None,
                "payload": event.get_payload(),
                "created_at": serialize_datetime(event.created_at),
                "sequence_id": event.sequence_id,
            }
            event_list.append(event_data)

        # Generate timestamp for filename
        export_timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")

        if export_format == "json":
            # JSON export format
            export_data = {
                "exported_at": datetime.now(timezone.utc).isoformat(),
                "filters": {
                    "scene_id": int(scene_id) if scene_id else None,
                    "actor_id": actor_id,
                    "combat_id": combat_id,
                    "action_id": action_id,
                    "event_type": event_type,
                    "after": after_str,
                    "before": before_str,
                },
                "total_events": total_count,
                "exported_events": len(event_list),
                "events": event_list,
            }

            return web.Response(
                body=json.dumps(export_data, indent=2),
                content_type="application/json",
                headers={
                    "Content-Disposition": f'attachment; filename="events_{export_timestamp}.json"',
                    "Cache-Control": "no-cache",
                },
            )

        else:  # txt format
            # TXT export format - human-readable
            lines = []
            lines.append("=" * 80)
            lines.append("PlanarAlly Event Log Export")
            lines.append("=" * 80)
            lines.append(f"Generated: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')}")
            lines.append("")

            # Filters section
            filters_applied = []
            if scene_id:
                filters_applied.append(f"scene_id={scene_id}")
            if actor_id:
                filters_applied.append(f"actor_id={actor_id}")
            if combat_id:
                filters_applied.append(f"combat_id={combat_id}")
            if action_id:
                filters_applied.append(f"action_id={action_id}")
            if event_type:
                filters_applied.append(f"type={event_type}")
            if after_str:
                filters_applied.append(f"after={after_str}")
            if before_str:
                filters_applied.append(f"before={before_str}")

            if filters_applied:
                lines.append(f"Filters: {', '.join(filters_applied)}")
            else:
                lines.append("Filters: None (all events)")

            lines.append(f"Total Events: {total_count}")
            lines.append(f"Exported Events: {len(event_list)}")
            if len(event_list) < total_count:
                lines.append(f"(Limited to {limit} events)")

            lines.append("")
            lines.append("=" * 80)
            lines.append("")

            # Events section
            for event_data in event_list:
                # Event header
                timestamp = event_data["created_at"]
                event_type_str = event_data["event_type"]
                seq = event_data["sequence_id"]
                lines.append(f"[{timestamp}] {event_type_str} (seq: {seq})")

                # Event details
                if event_data["scene_id"]:
                    lines.append(f"  Scene: {event_data['scene_id']}")
                if event_data["actor_id"]:
                    lines.append(f"  Actor: {event_data['actor_id']}")
                if event_data["combat_id"]:
                    lines.append(f"  Combat: {event_data['combat_id']}")
                if event_data["action_id"]:
                    lines.append(f"  Action: {event_data['action_id']}")

                # Payload
                payload = event_data["payload"]
                if payload:
                    lines.append(f"  Payload: {json.dumps(payload, indent=4)}")

                lines.append("")  # Blank line between events

            # Footer
            lines.append("=" * 80)
            lines.append("End of Event Log Export")
            lines.append("=" * 80)

            return web.Response(
                body="\n".join(lines),
                content_type="text/plain",
                charset="utf-8",
                headers={
                    "Content-Disposition": f'attachment; filename="events_{export_timestamp}.txt"',
                    "Cache-Control": "no-cache",
                },
            )

    except ValueError as e:
        return error(
            f"Invalid query parameter: {str(e)}",
            code="VALIDATION_ERROR",
            status=HTTP_BAD_REQUEST,
        )
    except Exception as e:
        return error(
            f"Failed to export events: {str(e)}",
            code="INTERNAL_ERROR",
            status=HTTP_INTERNAL_ERROR,
        )
