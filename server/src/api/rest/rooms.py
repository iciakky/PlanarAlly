"""Room and player management endpoints for REST API."""

from aiohttp import web
from peewee import DoesNotExist

from ...db.db import db
from ...db.models.location_user_option import LocationUserOption
from ...db.models.player_room import PlayerRoom
from ...db.models.room import Room
from ...db.models.user import User
from ...models.role import Role
from ..common.rooms.create import create_room
from .helpers import error, ok, require_role


@require_role("dm")
async def create_room_endpoint(request: web.Request) -> web.Response:
    """POST /api/v1/rooms — Create a new room."""
    api_key = request["api_key"]

    try:
        data = await request.json()
    except Exception:
        return error("Invalid JSON", code="VALIDATION_ERROR", status=400)

    name = data.get("name")
    if not name:
        return error("Missing required field: name", code="VALIDATION_ERROR", status=400)

    logo = data.get("logo", -1)

    room = create_room(name, api_key.user, logo)
    if room is None:
        return error(f"Room already exists: {name}", code="CONFLICT", status=409)

    default_loc = room.locations.first()
    pr = PlayerRoom.get_or_none(room=room, player=api_key.user)

    return ok({
        "room_id": room.id,
        "name": room.name,
        "default_location": {
            "id": default_loc.id,
            "name": default_loc.name,
        } if default_loc else None,
        "player_room_id": pr.id if pr else None,
    }, status=201)


@require_role("dm")
async def add_player_to_room(request: web.Request) -> web.Response:
    """POST /api/v1/rooms/{room_id}/players — Add a player to a room."""
    api_key = request["api_key"]

    try:
        room_id = int(request.match_info["room_id"])
    except (ValueError, TypeError):
        return error("Invalid room ID", code="VALIDATION_ERROR", status=400)

    try:
        data = await request.json()
    except Exception:
        return error("Invalid JSON", code="VALIDATION_ERROR", status=400)

    username = data.get("username")
    role_str = data.get("role", "player")

    if not username:
        return error("Missing required field: username", code="VALIDATION_ERROR", status=400)

    try:
        room = Room.get_by_id(room_id)
    except DoesNotExist:
        return error(f"Room not found: {room_id}", code="NOT_FOUND", status=404)

    if room.creator.id != api_key.user.id:
        return error("Only room creator can add players", code="FORBIDDEN", status=403)

    user = User.get_or_none(User.name == username)
    if user is None:
        return error(f"User not found: {username}", code="NOT_FOUND", status=404)

    existing = PlayerRoom.get_or_none(room=room, player=user)
    if existing:
        return error(f"Player already in room: {username}", code="CONFLICT", status=409)

    role = Role.DM if role_str == "dm" else Role.PLAYER
    active_loc = room.locations.first()
    if active_loc is None:
        return error("Room has no locations", code="INTERNAL_ERROR", status=500)

    pr = PlayerRoom.create(player=user, room=room, role=role, active_location=active_loc)

    from ...db.models.location import Location
    luo_ids = [
        luo.id for luo in
        LocationUserOption.select()
        .join(Location)
        .where(LocationUserOption.user == user, Location.room == room)
    ]

    return ok({
        "player_room_id": pr.id,
        "username": username,
        "role": role_str,
        "location_user_options_created": luo_ids,
    }, status=201)
