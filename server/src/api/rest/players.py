"""
REST API handlers for player management.

Provides endpoints for:
- GET /api/v1/players - List all players (online status, role)
- GET /api/v1/players/{id}/tokens - Get tokens owned by a player
- POST /api/v1/players/{id}/message - Send a message to a player
"""

import uuid as uuid_lib
from aiohttp import web

from ...db.models.user import User
from ...db.models.player_room import PlayerRoom
from ...db.models.shape import Shape
from ...db.models.shape_owner import ShapeOwner
from ...state.game import game_state
from ..helpers import _send_game
from ..models.chat import ApiChatMessage
from .helpers import ok, error, require_role, log_event, HTTP_NOT_FOUND


@require_role("dm")
async def list_players(request: web.Request) -> web.Response:
    """
    List all players with online status.

    GET /api/v1/players

    Query params:
        online: "true" to filter only online players
        room_id: Filter by room ID (optional)

    Returns:
        {
            "success": true,
            "data": {
                "players": [
                    {
                        "id": 1,
                        "name": "player1",
                        "email": "player@example.com",
                        "online": true,
                        "current_room": "my-campaign/session1",
                        "current_location_id": 5,
                        "role": 0  # 0 = player, 1 = DM
                    }
                ],
                "total": 10,
                "online_count": 3
            }
        }
    """
    # Query params
    only_online = request.query.get("online", "").lower() == "true"
    room_id_filter = request.query.get("room_id")

    # Get all users who have joined at least one room
    all_players_query = (
        User.select(User, PlayerRoom)
        .join(PlayerRoom, on=(User.id == PlayerRoom.player))
        .distinct()
    )

    if room_id_filter:
        try:
            all_players_query = all_players_query.where(PlayerRoom.room == int(room_id_filter))
        except ValueError:
            pass

    # Build set of currently online user IDs with their session info
    online_users: dict[int, dict] = {}
    for sid, player_room in game_state._sid_map.items():
        user_id = player_room.player.id
        online_users[user_id] = {
            "room_path": player_room.room.get_path(),
            "location_id": player_room.active_location.id,
            "role": player_room.role,
        }

    players = []
    for user in all_players_query:
        user_id = user.id
        is_online = user_id in online_users

        if only_online and not is_online:
            continue

        player_data = {
            "id": user_id,
            "name": user.name,
            "email": user.email,
            "online": is_online,
        }

        if is_online:
            session_info = online_users[user_id]
            player_data["current_room"] = session_info["room_path"]
            player_data["current_location_id"] = session_info["location_id"]
            player_data["role"] = session_info["role"]

        players.append(player_data)

    return ok({
        "players": players,
        "total": len(players),
        "online_count": len(online_users),
    })


@require_role("dm", "player")
async def get_player_tokens(request: web.Request) -> web.Response:
    """
    Get all tokens owned by a player.

    GET /api/v1/players/{id}/tokens

    Query params:
        location_id: Filter by location/scene (optional)

    Returns:
        {
            "success": true,
            "data": {
                "tokens": [
                    {
                        "uuid": "...",
                        "name": "Fighter",
                        "x": 350,
                        "y": 500,
                        "location_id": 5,
                        "location_name": "Dungeon Level 1",
                        "edit_access": true,
                        "vision_access": true,
                        "movement_access": true
                    }
                ],
                "total": 5
            }
        }
    """
    # Get player ID from path
    try:
        player_id = int(request.match_info["id"])
    except (ValueError, KeyError):
        return error(
            "Invalid player ID",
            code="VALIDATION_ERROR",
            status=400,
        )

    # Get the user
    user = User.get_or_none(User.id == player_id)
    if not user:
        return error(
            f"Player with ID {player_id} not found",
            code="NOT_FOUND",
            status=HTTP_NOT_FOUND,
        )

    # Check access: Players can only see their own tokens
    api_key = request.get("api_key")
    if api_key.role != "dm" and api_key.user.id != player_id:
        return error(
            "You can only view your own tokens",
            code="FORBIDDEN",
            status=403,
        )

    # Query params
    location_id_filter = request.query.get("location_id")

    # Get all shapes owned by this user
    query = (
        ShapeOwner.select(ShapeOwner, Shape)
        .join(Shape)
        .where(ShapeOwner.user == user)
    )

    # Build list of tokens
    tokens = []
    for owner in query:
        shape = owner.shape

        # Filter by location if specified
        if location_id_filter:
            try:
                if shape.layer.floor.location.id != int(location_id_filter):
                    continue
            except (ValueError, AttributeError):
                continue

        location = shape.layer.floor.location

        tokens.append({
            "uuid": shape.uuid,
            "name": shape.name,
            "x": shape.x,
            "y": shape.y,
            "location_id": location.id,
            "location_name": location.name,
            "edit_access": owner.edit_access,
            "vision_access": owner.vision_access,
            "movement_access": owner.movement_access,
        })

    return ok({
        "tokens": tokens,
        "total": len(tokens),
    })


@require_role("dm")
async def send_message(request: web.Request) -> web.Response:
    """
    Send a message to a player via chat.

    POST /api/v1/players/{id}/message

    Body:
        {
            "text": "Your turn next!",
            "private": true  # Optional, default false
        }

    Returns:
        {
            "success": true,
            "data": {
                "delivered": true,
                "message_id": "...",
                "recipient": "player1"
            }
        }

    Notes:
        - If private=true, message is sent only to that player
        - If private=false (default), message is broadcast to the room
        - If player is offline, returns delivered=false
    """
    # Get player ID from path
    try:
        player_id = int(request.match_info["id"])
    except (ValueError, KeyError):
        return error(
            "Invalid player ID",
            code="VALIDATION_ERROR",
            status=400,
        )

    # Get the user
    user = User.get_or_none(User.id == player_id)
    if not user:
        return error(
            f"Player with ID {player_id} not found",
            code="NOT_FOUND",
            status=HTTP_NOT_FOUND,
        )

    # Parse body
    try:
        body = await request.json()
    except Exception:
        return error(
            "Invalid JSON body",
            code="VALIDATION_ERROR",
        )

    text = body.get("text", "")
    if not text:
        return error(
            "Message text is required",
            code="VALIDATION_ERROR",
        )

    is_private = body.get("private", False)

    # Find the player's session
    target_sid = None
    room_path = None
    for sid, player_room in game_state._sid_map.items():
        if player_room.player.id == player_id:
            target_sid = sid
            room_path = player_room.room.get_path()
            break

    if not target_sid:
        return ok({
            "delivered": False,
            "message_id": None,
            "recipient": user.name,
            "reason": "Player is offline",
        })

    # Get the DM's user info for the chat message
    api_key = request.get("api_key")
    dm_user = api_key.user

    # Create chat message
    message_id = str(uuid_lib.uuid4())
    chat_message = ApiChatMessage(
        id=message_id,
        author=dm_user.name,
        data=[text],
    )

    # Send the message
    if is_private:
        # Send only to the target player
        from ...app import sio
        from ..socket.constants import GAME_NS
        await sio.emit("Chat.Add", chat_message.model_dump(), namespace=GAME_NS, room=target_sid)
    else:
        # Broadcast to the room
        await _send_game("Chat.Add", chat_message, room=room_path)

    # Log event
    await log_event(
        event_type="message_sent",
        payload={
            "recipient_id": player_id,
            "recipient_name": user.name,
            "text": text if len(text) < 100 else text[:97] + "...",  # Truncate for log
            "private": is_private,
            "message_id": message_id,
        },
    )

    return ok({
        "delivered": True,
        "message_id": message_id,
        "recipient": user.name,
    })
