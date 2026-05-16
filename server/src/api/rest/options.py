"""Scene (Location) options endpoint."""

from aiohttp import web
from peewee import DoesNotExist

from ...db.models.location import Location
from ...db.models.location_options import LocationOptions
from ...state.game import game_state
from ..helpers import _send_game
from .helpers import error, ok, require_role
from .revision import next_revision, broadcast_revision

OPTION_FIELD_MAP = {
    "full_fow": "full_fow",
    "fowLos": "fow_los",
    "fowOpacity": "fow_opacity",
    "unitSize": "unit_size",
    "unitSizeUnit": "unit_size_unit",
    "visionMode": "vision_mode",
    "ambientLight": "ambient_light",
    "gridType": "grid_type",
}


@require_role("dm")
async def update_scene_options(request: web.Request) -> web.Response:
    """PATCH /api/v1/scenes/{id}/options — Set location options."""
    api_key = request["api_key"]

    try:
        scene_id = int(request.match_info["uuid"])
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

    room = location.room
    if room.creator.id != api_key.user.id:
        return error("Only room creator can modify scene options", code="FORBIDDEN", status=403)

    options = location.options
    if options is None:
        options = LocationOptions.create_empty()
        location.options = options
        location.save()

    updated_fields = []
    for api_name, db_name in OPTION_FIELD_MAP.items():
        if api_name in data:
            setattr(options, db_name, data[api_name])
            updated_fields.append(api_name)

    options.save()

    effective = {}
    for api_name, db_name in OPTION_FIELD_MAP.items():
        effective[api_name] = getattr(options, db_name)

    try:
        await _send_game(
            "Location.Options.Set",
            {"options": options.as_pydantic(False), "location": location.id},
            room=location.get_path(),
        )
    except Exception:
        pass

    rev = next_revision()
    await broadcast_revision(rev, location.get_path())

    return ok({"effective_options": effective, "updated_fields": updated_fields, "revision": rev})
