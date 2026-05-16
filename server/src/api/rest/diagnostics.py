"""Scene diagnostics endpoint — invariant checker."""

from aiohttp import web
from peewee import DoesNotExist

from ...db.models.layer import Layer
from ...db.models.location import Location
from ...db.models.location_user_option import LocationUserOption
from ...db.models.player_room import PlayerRoom
from ...db.models.shape_owner import ShapeOwner
from .helpers import error, ok, require_role


@require_role("dm")
async def scene_diagnostics(request: web.Request) -> web.Response:
    """GET /api/v1/scenes/{id}/diagnostics — Check scene invariants."""
    api_key = request["api_key"]

    try:
        scene_id = int(request.match_info["uuid"])
    except (ValueError, TypeError):
        return error("Invalid scene ID", code="VALIDATION_ERROR", status=400)

    try:
        location = Location.get_by_id(scene_id)
    except DoesNotExist:
        return error("Scene not found", code="NOT_FOUND", status=404)

    room = location.room
    if room.creator.id != api_key.user.id:
        if not any(rp.player.id == api_key.user.id for rp in room.players):
            return error("Access denied to this scene", code="FORBIDDEN", status=403)

    issues = []

    player_rooms = list(PlayerRoom.select().where(PlayerRoom.room == room))
    for pr in player_rooms:
        luo = LocationUserOption.get_or_none(location=location, user=pr.player)
        if luo is None:
            issues.append({
                "severity": "error",
                "code": "MISSING_LOCATION_USER_OPTION",
                "message": f"{pr.player.name} has no LocationUserOption for this scene",
            })

    return ok({
        "ok": len([i for i in issues if i["severity"] == "error"]) == 0,
        "issues": issues,
    })
