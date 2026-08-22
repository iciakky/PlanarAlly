"""Map reference endpoints for live pointing feature."""

import math

from aiohttp import web
from peewee import DoesNotExist

from ...db.db import db
from ...db.models.floor import Floor
from ...db.models.layer import Layer
from ...db.models.location import Location
from ...db.models.player_room import PlayerRoom
from ...db.models.rest_ext.map_ref import MapRef
from ...db.models.rest_ext.reference_marker import ReferenceMarker
from ...db.models.shape import Shape
from ...db.models.user import User
from ...models.role import Role
from .helpers import error, ok, require_role
from .revision import next_revision


def _compute_grid(x: float, y: float, location: Location) -> str | None:
    """Compute grid coordinates from pixel coordinates.

    Uses the location's unit_size (defaults to 50px per grid cell).
    Returns a string like "8,6" (column, row from origin).
    """
    # Default grid size in pixels (PA uses 50px per grid cell by default)
    grid_size = 50.0

    col = int(math.floor(x / grid_size))
    row = int(math.floor(y / grid_size))

    return f"{col},{row}"


def _compute_bounds(location: Location, is_dm: bool = False):
    """Compute scene bounds from player-visible map-layer shapes.

    Returns (min_x, min_y, max_x, max_y) or None if no map shapes exist.
    Filters out non-player-visible floors/layers unless requester is DM.
    """
    min_x = float("inf")
    min_y = float("inf")
    max_x = float("-inf")
    max_y = float("-inf")
    found = False

    for floor in location.floors:
        for layer in floor.layers:
            if layer.name != "map":
                continue
            if not is_dm and not layer.player_visible:
                continue
            for shape in layer.shapes:
                found = True
                # Get shape bounds
                sx, sy = shape.x, shape.y
                # Try to get width/height from subtype
                from ...db.utils import get_table

                subtype_table = get_table(shape.type_)
                sw, sh = 0.0, 0.0
                if subtype_table is not None:
                    sub = subtype_table.get_or_none(subtype_table.shape == shape)
                    if sub is not None:
                        if hasattr(sub, "width"):
                            sw = float(sub.width)
                        if hasattr(sub, "height"):
                            sh = float(sub.height)

                min_x = min(min_x, sx)
                min_y = min(min_y, sy)
                max_x = max(max_x, sx + sw)
                max_y = max(max_y, sy + sh)

    if not found:
        return None

    return min_x, min_y, max_x, max_y


def _compute_direction(x: float, y: float, bounds) -> str:
    """Compute direction from bounds center to the point."""
    min_x, min_y, max_x, max_y = bounds
    cx = (min_x + max_x) / 2
    cy = (min_y + max_y) / 2

    dx = x - cx
    dy = y - cy

    # Determine cardinal direction
    if abs(dx) > abs(dy):
        return "E" if dx > 0 else "W"
    else:
        return "S" if dy > 0 else "N"


def _is_inside_bounds(x: float, y: float, bounds) -> bool:
    """Check if a point is inside the given bounds."""
    min_x, min_y, max_x, max_y = bounds
    return min_x <= x <= max_x and min_y <= y <= max_y


def _ref_to_dict(ref: MapRef) -> dict:
    """Serialize a MapRef to a dict for API response."""
    result = {
        "id": ref.id,
        "player": ref.player.name,
        "x": ref.x,
        "y": ref.y,
        "grid": ref.grid,
        "inside_scene": ref.inside_scene,
        "created_at": str(ref.created_at),
    }
    if ref.scene_bounds_source is not None:
        result["scene_bounds_source"] = ref.scene_bounds_source
    if ref.direction_from_bounds is not None:
        result["direction_from_bounds"] = ref.direction_from_bounds
    if ref.marker_id is not None:
        result["marker_id"] = ref.marker_id
    if ref.comment is not None:
        result["comment"] = ref.comment
    if ref.revision is not None:
        result["revision"] = ref.revision
    return result


@require_role("dm", "player")
async def create_map_ref(request: web.Request) -> web.Response:
    """POST /api/v1/scenes/{scene_id}/map-refs — Create a map reference."""
    api_key = request["api_key"]
    user = api_key.user

    try:
        scene_id = int(request.match_info["scene_id"])
    except (ValueError, TypeError):
        return error("Invalid scene ID", code="VALIDATION_ERROR", status=400)

    try:
        data = await request.json()
    except Exception:
        return error("Invalid JSON", code="VALIDATION_ERROR", status=400)

    try:
        location = Location.get_by_id(scene_id)
    except DoesNotExist:
        return error("Scene not found", code="NOT_FOUND", status=404)

    # Check access
    room = location.room
    if room.creator.id != user.id:
        pr = PlayerRoom.get_or_none(room=room, player=user)
        if not pr:
            return error("Access denied", code="FORBIDDEN", status=403)

    x = data.get("x")
    y = data.get("y")
    if x is None or y is None:
        return error("Missing required fields: x, y", code="VALIDATION_ERROR", status=400)

    x = float(x)
    y = float(y)

    # Determine player for the ref
    player_name = data.get("player", user.name)
    if player_name != user.name:
        # Only DMs can create refs on behalf of other players
        is_dm = room.creator.id == user.id
        if not is_dm:
            pr = PlayerRoom.get_or_none(room=room, player=user)
            if not pr or pr.role != Role.DM:
                return error("Only DM can create refs for other players", code="FORBIDDEN", status=403)

    player_user = User.get_or_none(User.name == player_name)
    if not player_user:
        return error(f"User not found: {player_name}", code="NOT_FOUND", status=404)

    # Compute grid
    grid = _compute_grid(x, y, location)

    # Determine DM status for bounds computation
    is_dm = room.creator.id == user.id
    if not is_dm:
        pr_dm = PlayerRoom.get_or_none(room=room, player=user)
        if pr_dm and pr_dm.role == Role.DM:
            is_dm = True

    # Compute inside_scene from player-visible map-layer shape bounds
    bounds = _compute_bounds(location, is_dm=is_dm)
    inside_scene = None
    scene_bounds_source = None
    direction_from_bounds = None

    if bounds is not None:
        inside_scene = _is_inside_bounds(x, y, bounds)
        scene_bounds_source = "map-layer"
        if not inside_scene:
            direction_from_bounds = _compute_direction(x, y, bounds)

    # Handle marker_id
    marker_id = data.get("marker_id")
    comment = data.get("comment")

    # If marker_id given, find linked marker's comment
    if marker_id:
        # Look for a marker with this label belonging to the player
        linked_marker = ReferenceMarker.get_or_none(
            ReferenceMarker.location == location,
            ReferenceMarker.label == marker_id,
            ReferenceMarker.owner == player_user,
        )
        if linked_marker and linked_marker.comment:
            comment = linked_marker.comment

    rev = next_revision()

    with db.atomic():
        ref = MapRef.create(
            location=location,
            player=player_user,
            x=x,
            y=y,
            grid=grid,
            inside_scene=inside_scene,
            scene_bounds_source=scene_bounds_source,
            direction_from_bounds=direction_from_bounds,
            marker_id=marker_id,
            comment=comment,
            revision=rev,
        )

    result = _ref_to_dict(ref)
    return ok(result, status=201)


@require_role("dm", "player")
async def query_map_refs(request: web.Request) -> web.Response:
    """GET /api/v1/scenes/{scene_id}/map-refs — Query map references."""
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

    # Check access
    room = location.room
    if room.creator.id != user.id:
        pr = PlayerRoom.get_or_none(room=room, player=user)
        if not pr:
            return error("Access denied", code="FORBIDDEN", status=403)

    # Determine DM status
    is_dm = room.creator.id == user.id
    if not is_dm:
        pr_dm = PlayerRoom.get_or_none(room=room, player=user)
        if pr_dm and pr_dm.role == Role.DM:
            is_dm = True

    # Query params
    since_revision = request.query.get("since_revision")
    player_filter = request.query.get("player")

    query = MapRef.select().where(MapRef.location == location)

    # Non-DM players can only see their own refs
    if not is_dm:
        if player_filter and player_filter != user.name:
            return error("Only DM can query other players' map refs", code="FORBIDDEN", status=403)
        query = query.where(MapRef.player == user)
    elif player_filter:
        target_user = User.get_or_none(User.name == player_filter)
        if target_user:
            query = query.where(MapRef.player == target_user)
        else:
            return ok({"refs": []})

    if since_revision is not None:
        try:
            since_rev = int(since_revision)
            query = query.where(MapRef.revision > since_rev)
        except ValueError:
            pass

    refs = [_ref_to_dict(ref) for ref in query.order_by(MapRef.created_at.desc())]

    return ok({"refs": refs})
