"""Shape access control endpoint."""

from aiohttp import web
from peewee import DoesNotExist

from ...db.db import db
from ...db.models.player_room import PlayerRoom
from ...db.models.shape import Shape
from ...db.models.shape_owner import ShapeOwner
from ...db.models.user import User
from ...models.role import Role
from ...state.game import game_state
from ..helpers import _send_game
from .helpers import error, ok, require_role
from .revision import next_revision, broadcast_revision


@require_role("dm")
async def update_shape_access(request: web.Request) -> web.Response:
    """PATCH /api/v1/shapes/{uuid}/access — Set per-player access on a shape."""
    api_key = request["api_key"]
    shape_uuid = request.match_info["uuid"]

    try:
        data = await request.json()
    except Exception:
        return error("Invalid JSON", code="VALIDATION_ERROR", status=400)

    try:
        shape = Shape.get(Shape.uuid == shape_uuid)
    except DoesNotExist:
        return error("Shape not found", code="NOT_FOUND", status=404)

    location = shape.layer.floor.location
    room = location.room
    if room.creator.id != api_key.user.id:
        pr = PlayerRoom.get_or_none(room=room, player=api_key.user)
        if not pr or pr.role != Role.DM:
            return error("Only DM can modify shape access", code="FORBIDDEN", status=403)

    with db.atomic():
        if "default_vision" in data:
            shape.default_vision_access = data["default_vision"]
        if "default_movement" in data:
            shape.default_movement_access = data["default_movement"]
        if "default_edit" in data:
            shape.default_edit_access = data["default_edit"]
        shape.save()

        players = data.get("players", {})
        for username, perms in players.items():
            user = User.get_or_none(User.name == username)
            if user is None:
                continue

            owner, created = ShapeOwner.get_or_create(
                shape=shape, user=user,
                defaults={
                    "edit_access": perms.get("edit", False),
                    "movement_access": perms.get("movement", False),
                    "vision_access": perms.get("vision", False),
                },
            )
            if not created:
                owner.edit_access = perms.get("edit", owner.edit_access)
                owner.movement_access = perms.get("movement", owner.movement_access)
                owner.vision_access = perms.get("vision", owner.vision_access)
                owner.save()

            for psid in game_state.get_sids(active_location=location):
                await _send_game(
                    "Shape.Owner.Add" if created else "Shape.Owner.Update",
                    owner.as_pydantic(),
                    room=psid,
                )

    rev = next_revision()
    await broadcast_revision(rev, location.get_path())

    return ok({"updated": True, "revision": rev})
