"""Access-level visibility check endpoint."""

from aiohttp import web
from peewee import DoesNotExist

from ...db.models.layer import Layer
from ...db.models.location import Location
from ...db.models.player_room import PlayerRoom
from ...db.models.rest_ext.shape_external_id import ShapeExternalId
from ...db.models.shape import Shape
from ...db.models.shape_owner import ShapeOwner
from ...db.models.user import User
from .helpers import error, ok, require_role


@require_role("dm")
async def scene_visibility(request: web.Request) -> web.Response:
    """GET /api/v1/scenes/{id}/visibility?player=... — Access-level visibility check."""
    api_key = request["api_key"]

    try:
        scene_id = int(request.match_info["uuid"])
    except (ValueError, TypeError):
        return error("Invalid scene ID", code="VALIDATION_ERROR", status=400)

    player_name = request.query.get("player")
    if not player_name:
        return error("Missing query parameter: player", code="VALIDATION_ERROR", status=400)

    try:
        location = Location.get_by_id(scene_id)
    except DoesNotExist:
        return error("Scene not found", code="NOT_FOUND", status=404)

    room = location.room
    if room.creator.id != api_key.user.id:
        if not any(rp.player.id == api_key.user.id for rp in room.players):
            return error("Access denied to this scene", code="FORBIDDEN", status=403)

    player = User.get_or_none(User.name == player_name)
    if player is None:
        return error(f"Player not found: {player_name}", code="NOT_FOUND", status=404)

    pr = PlayerRoom.get_or_none(room=location.room, player=player)
    if pr is None:
        return error(f"Player not in room: {player_name}", code="NOT_FOUND", status=404)

    shapes_result = []

    for floor in location.floors:
        for layer in floor.layers:
            for shape in layer.shapes:
                ext_id_mapping = ShapeExternalId.get_or_none(ShapeExternalId.shape == shape)
                external_id = ext_id_mapping.external_id if ext_id_mapping else None

                if not layer.player_visible:
                    shapes_result.append({
                        "uuid": shape.uuid,
                        "external_id": external_id,
                        "layer": layer.name,
                        "sent_to_client": False,
                        "reason": "not_sent_to_client",
                    })
                    continue

                shapes_result.append({
                    "uuid": shape.uuid,
                    "external_id": external_id,
                    "layer": layer.name,
                    "sent_to_client": True,
                    "reason": "visible",
                })

    return ok({"player": player_name, "shapes": shapes_result})
