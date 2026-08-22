"""Reference marker CRUD endpoints for live pointing feature."""

import json

from aiohttp import web
from peewee import DoesNotExist

from ...db.db import db
from ...db.models.location import Location
from ...db.models.player_room import PlayerRoom
from ...db.models.rest_ext.reference_marker import ReferenceMarker
from ...db.models.user import User
from ...models.role import Role
from ...state.game import game_state
from ..helpers import _send_game
from .helpers import error, ok, require_role
from .revision import broadcast_revision, next_revision


VALID_SHAPES = {"ring", "arrow", "label", "flag"}
VALID_SCOPES = {"player", "dm"}


def _marker_to_dict(marker: ReferenceMarker) -> dict:
    """Serialize a ReferenceMarker to a dict for API response."""
    result = {
        "external_id": marker.external_id,
        "x": marker.x,
        "y": marker.y,
        "shape": marker.shape,
        "label": marker.label,
        "scope": marker.scope,
        "owner": marker.owner.name,
        "render_above_fog": marker.render_above_fog,
        "record": marker.record,
    }
    if marker.target_x is not None:
        result["target_x"] = marker.target_x
    if marker.target_y is not None:
        result["target_y"] = marker.target_y
    if marker.text is not None:
        result["text"] = marker.text
    if marker.comment is not None:
        result["comment"] = marker.comment
    if marker.colour is not None:
        result["colour"] = marker.colour
    if marker.metadata is not None:
        result["metadata"] = marker.metadata

    # Parse visible_to from JSON
    try:
        visible_to = json.loads(marker.visible_to)
    except (json.JSONDecodeError, TypeError):
        visible_to = []
    result["visible_to"] = visible_to

    return result


def _get_authenticated_user(request: web.Request) -> User:
    """Get the authenticated user from the API key."""
    api_key = request["api_key"]
    return api_key.user


def _check_scene_access(location: Location, user: User, require_dm: bool = False):
    """Check user access to the scene. Returns (room, player_room, is_dm) or raises."""
    room = location.room
    if room.creator.id == user.id:
        return room, None, True

    pr = PlayerRoom.get_or_none(room=room, player=user)
    if not pr:
        return None, None, None

    is_dm = pr.role == Role.DM
    if require_dm and not is_dm:
        return None, None, None

    return room, pr, is_dm


@require_role("dm", "player")
async def upsert_marker(request: web.Request) -> web.Response:
    """PUT /api/v1/scenes/{scene_id}/markers/by-external-id/{external_id}"""
    api_key = request["api_key"]
    user = api_key.user

    try:
        scene_id = int(request.match_info["scene_id"])
    except (ValueError, TypeError):
        return error("Invalid scene ID", code="VALIDATION_ERROR", status=400)

    external_id = request.match_info["external_id"]

    try:
        data = await request.json()
    except Exception:
        return error("Invalid JSON", code="VALIDATION_ERROR", status=400)

    try:
        location = Location.get_by_id(scene_id)
    except DoesNotExist:
        return error("Scene not found", code="NOT_FOUND", status=404)

    # Check scene access
    room = location.room
    if room.creator.id != user.id:
        pr = PlayerRoom.get_or_none(room=room, player=user)
        if not pr:
            return error("Access denied", code="FORBIDDEN", status=403)

    # Check owner field — server-determined, cannot be spoofed
    if "owner" in data and data["owner"] != user.name:
        return error(
            "Field 'owner' cannot differ from authenticated user. "
            "Owner is server-determined from your API key.",
            code="VALIDATION_ERROR",
            status=400,
        )

    # Determine if user is DM
    is_dm = room.creator.id == user.id
    if not is_dm:
        pr_check = PlayerRoom.get_or_none(room=room, player=user)
        if pr_check and pr_check.role == Role.DM:
            is_dm = True

    # Check if marker already exists (upsert case)
    existing = ReferenceMarker.get_or_none(
        ReferenceMarker.location == location,
        ReferenceMarker.external_id == external_id,
    )

    if existing:
        # Ownership check: non-DM can only update their own markers
        if not is_dm and existing.owner_id != user.id:
            return error("Cannot modify another user's marker", code="FORBIDDEN", status=403)

        # Upsert: update existing marker. Omitted fields preserve existing values.
        if "x" in data:
            existing.x = float(data["x"])
        if "y" in data:
            existing.y = float(data["y"])
        if "shape" in data:
            shape = data["shape"]
            if shape not in VALID_SHAPES:
                return error(
                    f"Invalid shape: {shape}. Valid: {', '.join(sorted(VALID_SHAPES))}",
                    code="VALIDATION_ERROR",
                    status=400,
                )
            existing.shape = shape
        if "label" in data:
            existing.label = data["label"]
        if "text" in data:
            existing.text = data["text"]
        if "comment" in data:
            existing.comment = data["comment"]
        if "colour" in data:
            existing.colour = data["colour"]
        if "scope" in data:
            if data["scope"] not in VALID_SCOPES:
                return error(
                    f"Invalid scope: {data['scope']}. Valid: {', '.join(sorted(VALID_SCOPES))}",
                    code="VALIDATION_ERROR",
                    status=400,
                )
            if data["scope"] == "dm" and not is_dm:
                return error("Only DM can set scope='dm'", code="FORBIDDEN", status=403)
            existing.scope = data["scope"]
        if "visible_to" in data:
            existing.visible_to = json.dumps(data["visible_to"])
        if "render_above_fog" in data:
            existing.render_above_fog = data["render_above_fog"]
        if "record" in data:
            existing.record = data["record"]
        if "metadata" in data:
            existing.metadata = data["metadata"] if isinstance(data["metadata"], str) else json.dumps(data["metadata"])
        if "target_x" in data:
            existing.target_x = float(data["target_x"]) if data["target_x"] is not None else None
        if "target_y" in data:
            existing.target_y = float(data["target_y"]) if data["target_y"] is not None else None

        # Arrow validation for shape change
        effective_shape = existing.shape
        if effective_shape == "arrow":
            if existing.target_x is None or existing.target_y is None:
                return error(
                    "Arrow shape requires target_x and target_y",
                    code="VALIDATION_ERROR",
                    status=400,
                )

        # visible_to validation on update: scope=player requires non-empty visible_to
        if existing.scope == "player":
            try:
                vis_list = json.loads(existing.visible_to)
            except (json.JSONDecodeError, TypeError):
                vis_list = []
            if not vis_list:
                return error(
                    "Field 'visible_to' must be non-empty when scope='player'.",
                    code="VALIDATION_ERROR",
                    status=400,
                )

        with db.atomic():
            existing.save()

        rev = next_revision()
        await broadcast_revision(rev, location.get_path())

        # Broadcast to connected clients
        marker_data = _marker_to_dict(existing)
        await _broadcast_marker_add(marker_data, location, room)

        result = _marker_to_dict(existing)
        result["revision"] = rev
        return ok(result)

    else:
        # Create new marker
        shape = data.get("shape")
        if not shape or shape not in VALID_SHAPES:
            return error(
                f"Invalid or missing shape. Valid: {', '.join(sorted(VALID_SHAPES))}",
                code="VALIDATION_ERROR",
                status=400,
            )

        scope = data.get("scope", "player")
        if scope not in VALID_SCOPES:
            return error(
                f"Invalid scope: {scope}. Valid: {', '.join(sorted(VALID_SCOPES))}",
                code="VALIDATION_ERROR",
                status=400,
            )

        # scope=player requires visible_to
        if scope == "player":
            visible_to = data.get("visible_to")
            if visible_to is None:
                return error(
                    "Field 'visible_to' is required when scope='player'. "
                    "Specify which players can see this marker.",
                    code="VALIDATION_ERROR",
                    status=400,
                )
            if not isinstance(visible_to, list) or len(visible_to) == 0:
                return error(
                    "Field 'visible_to' must be a non-empty list of usernames when scope='player'.",
                    code="VALIDATION_ERROR",
                    status=400,
                )
        else:
            visible_to = data.get("visible_to", [])

        # Arrow requires target_x and target_y
        if shape == "arrow":
            if "target_x" not in data or "target_y" not in data:
                return error(
                    "Arrow shape requires target_x and target_y fields.",
                    code="VALIDATION_ERROR",
                    status=400,
                )

        if "x" not in data or "y" not in data:
            return error("Missing required fields: x, y", code="VALIDATION_ERROR", status=400)

        label = data.get("label", "")

        with db.atomic():
            marker = ReferenceMarker.create(
                external_id=external_id,
                location=location,
                owner=user,
                x=float(data["x"]),
                y=float(data["y"]),
                target_x=float(data["target_x"]) if data.get("target_x") is not None else None,
                target_y=float(data["target_y"]) if data.get("target_y") is not None else None,
                shape=shape,
                label=label,
                text=data.get("text"),
                comment=data.get("comment"),
                colour=data.get("colour"),
                scope=scope,
                visible_to=json.dumps(visible_to),
                render_above_fog=data.get("render_above_fog", True),
                record=data.get("record", True),
                metadata=data.get("metadata") if isinstance(data.get("metadata"), str) else (
                    json.dumps(data["metadata"]) if data.get("metadata") is not None else None
                ),
            )

        rev = next_revision()
        await broadcast_revision(rev, location.get_path())

        # Broadcast to connected clients
        marker_data = _marker_to_dict(marker)
        await _broadcast_marker_add(marker_data, location, room)

        result = _marker_to_dict(marker)
        result["revision"] = rev
        return ok(result, status=201)


@require_role("dm", "player")
async def delete_marker(request: web.Request) -> web.Response:
    """DELETE /api/v1/scenes/{scene_id}/markers/by-external-id/{external_id}"""
    api_key = request["api_key"]
    user = api_key.user

    try:
        scene_id = int(request.match_info["scene_id"])
    except (ValueError, TypeError):
        return error("Invalid scene ID", code="VALIDATION_ERROR", status=400)

    external_id = request.match_info["external_id"]

    try:
        location = Location.get_by_id(scene_id)
    except DoesNotExist:
        return error("Scene not found", code="NOT_FOUND", status=404)

    # Check scene access
    room = location.room
    if room.creator.id != user.id:
        pr = PlayerRoom.get_or_none(room=room, player=user)
        if not pr:
            return error("Access denied", code="FORBIDDEN", status=403)

    marker = ReferenceMarker.get_or_none(
        ReferenceMarker.location == location,
        ReferenceMarker.external_id == external_id,
    )
    if not marker:
        return error("Marker not found", code="NOT_FOUND", status=404)

    # Ownership check: non-DM can only delete their own markers
    is_dm = room.creator.id == user.id
    if not is_dm:
        pr_check = PlayerRoom.get_or_none(room=room, player=user)
        if pr_check and pr_check.role == Role.DM:
            is_dm = True
    if not is_dm and marker.owner_id != user.id:
        return error("Cannot delete another user's marker", code="FORBIDDEN", status=403)

    # Capture scope before deletion for broadcast scoping
    marker_scope = marker.scope
    marker_visible_to = marker.visible_to

    with db.atomic():
        marker.delete_instance()

    rev = next_revision()
    await broadcast_revision(rev, location.get_path())

    # Broadcast removal (respect scope)
    await _broadcast_marker_remove(external_id, marker_scope, marker_visible_to, location, room)

    return ok({"external_id": external_id, "revision": rev})


@require_role("dm", "player")
async def batch_delete_markers(request: web.Request) -> web.Response:
    """DELETE /api/v1/scenes/{scene_id}/markers — Batch delete markers."""
    api_key = request["api_key"]
    user = api_key.user

    try:
        scene_id = int(request.match_info["scene_id"])
    except (ValueError, TypeError):
        return error("Invalid scene ID", code="VALIDATION_ERROR", status=400)

    try:
        location = Location.get_by_id(scene_id)
    except DoesNotExist:
        return error("Scene not found", code="NOT_FOUND", status=404)

    # Check scene access
    room = location.room
    if room.creator.id != user.id:
        pr = PlayerRoom.get_or_none(room=room, player=user)
        if not pr:
            return error("Access denied", code="FORBIDDEN", status=403)

    # Query params
    prefix = request.query.get("prefix")
    scope = request.query.get("scope")
    owner_param = request.query.get("owner")

    # owner filter: must equal authenticated user (cannot target others' markers)
    if owner_param and owner_param != user.name:
        return error(
            "Cannot delete another user's markers. Batch delete is always scoped to your own markers.",
            code="FORBIDDEN",
            status=403,
        )

    # Build query — always scoped to requesting user's own markers
    query = ReferenceMarker.select().where(
        ReferenceMarker.location == location,
        ReferenceMarker.owner == user,
    )

    if prefix:
        query = query.where(ReferenceMarker.external_id.startswith(prefix))
    if scope:
        query = query.where(ReferenceMarker.scope == scope)

    # Collect marker info before delete for broadcast (inside atomic for consistency)
    with db.atomic():
        deleted_markers = [(m.external_id, m.scope, m.visible_to) for m in query]
        ReferenceMarker.delete().where(
            ReferenceMarker.location == location,
            ReferenceMarker.owner == user,
            ReferenceMarker.external_id.in_([eid for eid, _, _ in deleted_markers]),
        ).execute()

    rev = next_revision()
    await broadcast_revision(rev, location.get_path())

    # Broadcast removals respecting scope
    for eid, m_scope, m_visible_to in deleted_markers:
        await _broadcast_marker_remove(eid, m_scope, m_visible_to, location, room)

    return ok({"deleted": len(deleted_markers), "revision": rev})


@require_role("dm", "player")
async def list_markers(request: web.Request) -> web.Response:
    """GET /api/v1/scenes/{scene_id}/markers — List markers."""
    api_key = request["api_key"]
    user = api_key.user

    try:
        scene_id = int(request.match_info["scene_id"])
    except (ValueError, TypeError):
        return error("Invalid scene ID", code="VALIDATION_ERROR", status=400)

    try:
        location = Location.get_by_id(scene_id)
    except DoesNotExist:
        return error("Scene not found", code="NOT_FOUND", status=404)

    # Check scene access
    room = location.room
    if room.creator.id != user.id:
        pr = PlayerRoom.get_or_none(room=room, player=user)
        if not pr:
            return error("Access denied", code="FORBIDDEN", status=403)

    # Determine if user is DM
    is_dm = room.creator.id == user.id
    if not is_dm:
        pr = PlayerRoom.get_or_none(room=room, player=user)
        if pr and pr.role == Role.DM:
            is_dm = True

    # Query params
    scope_filter = request.query.get("scope")
    record_filter = request.query.get("record")

    query = ReferenceMarker.select().where(ReferenceMarker.location == location)

    if scope_filter:
        query = query.where(ReferenceMarker.scope == scope_filter)

    if record_filter is not None:
        if record_filter.lower() == "true":
            query = query.where(ReferenceMarker.record == True)
        elif record_filter.lower() == "false":
            query = query.where(ReferenceMarker.record == False)

    markers = []
    for marker in query:
        # Access control: player can only see markers they're in visible_to, or their own
        if not is_dm:
            if marker.scope == "dm":
                continue
            try:
                visible_to = json.loads(marker.visible_to)
            except (json.JSONDecodeError, TypeError):
                visible_to = []
            # Player can see markers: if they are in visible_to OR own the marker
            if user.name not in visible_to and marker.owner_id != user.id:
                continue

        markers.append(_marker_to_dict(marker))

    return ok({"markers": markers})


async def _broadcast_marker_add(marker_data: dict, location, room):
    """Broadcast marker add to connected clients based on scope/visibility."""
    scope = marker_data.get("scope", "player")
    visible_to = marker_data.get("visible_to", [])

    if scope == "dm":
        # Send only to DMs
        for room_player in room.players:
            if room_player.role == Role.DM:
                for psid in game_state.get_sids(player=room_player.player, active_location=location):
                    await _send_game("ReferenceMarker.Add", marker_data, room=psid)
        # Also send to room creator if connected
        for psid in game_state.get_sids(player=room.creator, active_location=location):
            await _send_game("ReferenceMarker.Add", marker_data, room=psid)
    else:
        # Send to visible_to players
        for username in visible_to:
            target_user = User.get_or_none(User.name == username)
            if target_user:
                for psid in game_state.get_sids(player=target_user, active_location=location):
                    await _send_game("ReferenceMarker.Add", marker_data, room=psid)
        # Also send to DMs
        for room_player in room.players:
            if room_player.role == Role.DM:
                for psid in game_state.get_sids(player=room_player.player, active_location=location):
                    await _send_game("ReferenceMarker.Add", marker_data, room=psid)
        for psid in game_state.get_sids(player=room.creator, active_location=location):
            await _send_game("ReferenceMarker.Add", marker_data, room=psid)


async def _broadcast_marker_remove(external_id: str, scope: str, visible_to_json: str, location, room):
    """Broadcast marker removal respecting scope/visibility."""
    try:
        visible_to = json.loads(visible_to_json)
    except (json.JSONDecodeError, TypeError):
        visible_to = []

    payload = {"external_id": external_id}

    if scope == "dm":
        for room_player in room.players:
            if room_player.role == Role.DM:
                for psid in game_state.get_sids(player=room_player.player, active_location=location):
                    await _send_game("ReferenceMarker.Remove", payload, room=psid)
        for psid in game_state.get_sids(player=room.creator, active_location=location):
            await _send_game("ReferenceMarker.Remove", payload, room=psid)
    else:
        for username in visible_to:
            target_user = User.get_or_none(User.name == username)
            if target_user:
                for psid in game_state.get_sids(player=target_user, active_location=location):
                    await _send_game("ReferenceMarker.Remove", payload, room=psid)
        for room_player in room.players:
            if room_player.role == Role.DM:
                for psid in game_state.get_sids(player=room_player.player, active_location=location):
                    await _send_game("ReferenceMarker.Remove", payload, room=psid)
        for psid in game_state.get_sids(player=room.creator, active_location=location):
            await _send_game("ReferenceMarker.Remove", payload, room=psid)
