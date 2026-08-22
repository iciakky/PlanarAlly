"""Grid display options endpoint for live pointing feature."""

from aiohttp import web
from peewee import DoesNotExist

from ...db.db import db
from ...db.models.location import Location
from ...db.models.player_room import PlayerRoom
from ...db.models.rest_ext.grid_display_options import GridDisplayOptions
from ...models.role import Role
from .helpers import error, ok, require_role


@require_role("dm")
async def update_grid_options(request: web.Request) -> web.Response:
    """PATCH /api/v1/scenes/{scene_id}/grid-options — Update grid display settings."""
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

    # Check DM access
    room = location.room
    if room.creator.id != user.id:
        pr = PlayerRoom.get_or_none(room=room, player=user)
        if not pr or pr.role != Role.DM:
            return error("Only DM can update grid options", code="FORBIDDEN", status=403)

    # Get or create grid options for this location
    options = GridDisplayOptions.get_or_none(GridDisplayOptions.location == location)

    with db.atomic():
        if options is None:
            # Create with defaults, then apply data
            options = GridDisplayOptions.create(location=location)

        # Update fields from request
        if "show_coordinates" in data:
            options.show_coordinates = data["show_coordinates"]
        if "coordinate_mode" in data:
            options.coordinate_mode = data["coordinate_mode"]
        if "origin" in data:
            options.origin = data["origin"]
        if "toggleable" in data:
            options.toggleable = data["toggleable"]

        # Handle compass as nested object
        compass = data.get("compass")
        if compass and isinstance(compass, dict):
            if "enabled" in compass:
                options.compass_enabled = compass["enabled"]
            if "north_degrees" in compass:
                options.compass_north_degrees = float(compass["north_degrees"])

        # Also handle flat fields
        if "compass_enabled" in data:
            options.compass_enabled = data["compass_enabled"]
        if "compass_north_degrees" in data:
            options.compass_north_degrees = float(data["compass_north_degrees"])

        options.save()

    result = {
        "show_coordinates": options.show_coordinates,
        "coordinate_mode": options.coordinate_mode,
        "origin": options.origin,
        "toggleable": options.toggleable,
        "compass_enabled": options.compass_enabled,
        "compass_north_degrees": options.compass_north_degrees,
    }

    return ok(result)
