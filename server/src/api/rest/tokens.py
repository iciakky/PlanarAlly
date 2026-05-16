"""Token CRUD operations for REST API.

Tokens are PA shapes with additional metadata (HP, AC, conditions, faction).
This module handles token lifecycle and integrates with PA's shape system.
"""

import json
from typing import Any
from uuid import uuid4

from aiohttp import web
from peewee import DoesNotExist

from ...app import sio
from ...db.db import db
from ...db.models.aura import Aura
from ...db.models.floor import Floor
from ...db.models.layer import Layer
from ...db.models.location import Location
from ...db.models.player_room import PlayerRoom
from ...db.models.rest_ext.token_ext import TokenExt
from ...db.models.shape import Shape
from ...db.models.tracker import Tracker
from ...db.models.user import User
from ...models.role import Role
from ...state.game import game_state
from ...transform.to_api.shape import transform_shape
from ..common.shapes import create_shape
from ..helpers import _send_game
from ..models.shape import ApiCircularTokenShape
from ..models.shape.owner import ApiShapeOwner
from .helpers import error, log_event, ok, require_role


@require_role("dm", "player")
async def list_tokens(request: web.Request) -> web.Response:
    """GET /api/v1/scenes/{uuid}/tokens - List all tokens in a scene."""
    api_key = request["api_key"]
    try:
        scene_id = int(request.match_info["uuid"])
    except (ValueError, TypeError):
        return error("Invalid scene UUID", code="VALIDATION_ERROR", status=400)

    try:
        location = Location.get_by_id(scene_id)
    except DoesNotExist:
        return error("Scene not found", code="NOT_FOUND", status=404)

    # Check access: user must be in this scene's room, or be the room creator
    room = location.room
    player_room = PlayerRoom.get_or_none(
        (PlayerRoom.room == room) & (PlayerRoom.player == api_key.user)
    )
    if not player_room and room.creator != api_key.user:
        return error("Access denied to this scene", code="FORBIDDEN", status=403)

    # Get all shapes in "tokens" layer across all floors
    tokens = []
    for floor in location.floors:
        token_layer = floor.layers.where(Layer.name == "tokens").first()
        if not token_layer:
            continue

        for shape in token_layer.shapes:
            # Get trackers (HP, AC)
            trackers = list(shape.trackers)
            tracker_dict = {t.name: {"value": t.value, "max": t.maxvalue} for t in trackers}

            # Get extended data
            token_ext = TokenExt.get_or_none(TokenExt.shape == shape)

            token_data = {
                "uuid": shape.uuid,
                "name": shape.name,
                "x": shape.x,
                "y": shape.y,
                "floor": floor.name,
                "hp": tracker_dict.get("HP", {"value": 0, "max": 0}),
                "ac": tracker_dict.get("AC", {"value": 0, "max": 0}),
                "faction": token_ext.faction if token_ext else None,
                "conditions": token_ext.get_conditions() if token_ext else [],
                "custom": token_ext.get_custom() if token_ext else {},
            }
            tokens.append(token_data)

    return ok({"tokens": tokens, "count": len(tokens)})


@require_role("dm")
async def create_token(request: web.Request) -> web.Response:
    """POST /api/v1/scenes/{uuid}/tokens - Create a new token."""
    api_key = request["api_key"]
    try:
        scene_id = int(request.match_info["uuid"])
    except (ValueError, TypeError):
        return error("Invalid scene UUID", code="VALIDATION_ERROR", status=400)

    try:
        data = await request.json()
    except Exception:
        return error("Invalid JSON", code="VALIDATION_ERROR", status=400)

    # Validate required fields
    required = ["name", "x", "y"]
    for field in required:
        if field not in data:
            return error(f"Missing required field: {field}", code="VALIDATION_ERROR", status=400)

    try:
        location = Location.get_by_id(scene_id)
    except DoesNotExist:
        return error("Scene not found", code="NOT_FOUND", status=404)

    # Check access: user must be DM in this room, or be the room creator
    room = location.room
    player_room = PlayerRoom.get_or_none(
        (PlayerRoom.room == room) & (PlayerRoom.player == api_key.user)
    )
    is_room_creator = room.creator == api_key.user
    if not is_room_creator and (not player_room or player_room.role != Role.DM):
        return error("Only DM can create tokens", code="FORBIDDEN", status=403)

    # Get floor and layer
    floor_name = data.get("floor", "ground")
    floor = location.floors.where(Floor.name == floor_name).first()
    if not floor:
        return error(f"Floor not found: {floor_name}", code="NOT_FOUND", status=404)

    token_layer = floor.layers.where(Layer.name == "tokens").first()
    if not token_layer:
        return error("Tokens layer not found", code="NOT_FOUND", status=404)

    # Extract token data
    name = data["name"]
    x = float(data["x"])
    y = float(data["y"])
    # Accept "hp" or "hp_current" for current HP
    hp_current = data.get("hp", data.get("hp_current", 0))
    hp_max = data.get("hp_max", 0)
    ac = data.get("ac", 0)
    faction = data.get("faction")
    conditions = data.get("conditions", [])
    custom = data.get("custom", {})
    size = data.get("size", 25.0)  # Default 5ft grid square (1 inch = 5ft)

    token_uuid = str(uuid4())

    # Create shape using PA's create_shape
    with db.atomic():
        # Build ApiCircularTokenShape with ALL required fields
        api_shape = ApiCircularTokenShape(
            # Core identification
            uuid=token_uuid,
            type_="circulartoken",
            # Position
            x=x,
            y=y,
            # Name
            name=name,
            name_visible=True,
            # Appearance
            fill_colour="rgba(255, 255, 255, 1)",
            stroke_colour="rgba(0, 0, 0, 1)",  # String, not list
            stroke_width=2,
            # CircleShape fields
            radius=size / 2,
            viewing_angle=None,
            # CircularToken fields
            text=name[:2].upper(),
            font="serif",
            # Visibility/state
            is_invisible=False,
            is_defeated=False,
            is_locked=False,
            # Vision/movement obstruction
            vision_obstruction=0,  # VisionBlock enum: 0 = none
            movement_obstruction=False,
            # Drawing
            draw_operator="source-over",
            options="{}",  # JSON string
            # Badge
            badge=1,
            show_badge=False,
            # Default access
            default_edit_access=False,
            default_vision_access=False,
            default_movement_access=False,
            # Angle/rotation
            angle=0.0,
            # Asset
            variants=None,
            # Group
            group=None,
            # Zoom behavior
            ignore_zoom_size=False,
            # Door/teleport
            is_door=False,
            is_teleport_zone=False,
            # Custom data
            custom_data=[],
            # Character
            character=None,
            # Hex grid
            odd_hex_orientation=False,
            size_x=1,
            size_y=1,
            show_cells=False,
            cell_fill_colour=None,
            cell_stroke_colour=None,
            cell_stroke_width=None,
            # Notes
            notes=[],
            # Owners
            owners=[
                ApiShapeOwner(
                    shape=token_uuid,  # Placeholder, overwritten by create_shape()
                    user=api_key.user.name,
                    edit_access=True,
                    movement_access=True,
                    vision_access=True,
                )
            ],
            # Trackers and auras (added separately after shape creation)
            trackers=[],
            auras=[],
        )

        # Create shape
        shape = create_shape(api_shape, layer=token_layer)
        if not shape:
            return error("Failed to create shape", code="INTERNAL_ERROR", status=500)

        # Create trackers (HP and AC)
        if hp_max > 0:
            Tracker.create(
                uuid=str(uuid4()),
                shape=shape,
                name="HP",
                value=hp_current,
                maxvalue=hp_max,
                visible=True,
                draw=True,
                primary_color="rgb(221, 0, 0)",
                secondary_color="rgb(0, 0, 0)",
            )

        if ac > 0:
            Tracker.create(
                uuid=str(uuid4()),
                shape=shape,
                name="AC",
                value=ac,
                maxvalue=ac,
                visible=True,
                draw=False,
                primary_color="rgb(68, 136, 255)",  # Blue for AC
                secondary_color="rgb(0, 0, 0)",
            )

        # Create TokenExt
        token_ext = TokenExt.create(
            uuid=str(uuid4()),
            shape=shape,  # FK to Shape model
            faction=faction or "",
            conditions=json.dumps(conditions),
            custom=json.dumps(custom),
        )

    # Emit socket event to all players in the location
    # Transform shape for each player based on their permissions
    for room_player in room.players:
        is_dm = room_player.role == Role.DM
        for psid in game_state.get_sids(player=room_player.player, active_location=location):
            # Skip DM-only layers for players
            if not is_dm and not token_layer.player_visible:
                continue

            # Transform shape with player's perspective
            api_shape_data = transform_shape(shape, room_player)

            # Send Shape.Add event
            await _send_game(
                "Shape.Add",
                {
                    "shape": api_shape_data,
                    "floor": floor_name,
                    "layer": "tokens",
                    "temporary": False,
                },
                room=psid,
            )

    # Log event
    await log_event(
        event_type="token_created",
        payload={
            "token_id": token_uuid,
            "name": name,
            "hp": {"current": hp_current, "max": hp_max},
            "ac": ac,
            "faction": faction,
        },
        scene_id=scene_id,
        actor_id=token_uuid,
    )

    return ok(
        {
            "uuid": token_uuid,
            "name": name,
            "x": x,
            "y": y,
            "hp": {"current": hp_current, "max": hp_max},
            "ac": ac,
            "faction": faction,
            "conditions": conditions,
            "custom": custom,
        },
        status=201,
    )


@require_role("dm", "player")
async def get_token(request: web.Request) -> web.Response:
    """GET /api/v1/tokens/{uuid} - Get a single token by UUID."""
    token_uuid = request.match_info["uuid"]
    api_key = request["api_key"]

    try:
        shape = Shape.get(Shape.uuid == token_uuid)
    except DoesNotExist:
        return error("Token not found", code="NOT_FOUND", status=404)

    # Check access: user must be in this room, or be the room creator
    location = shape.layer.floor.location
    room = location.room
    player_room = PlayerRoom.get_or_none(
        (PlayerRoom.room == room) & (PlayerRoom.player == api_key.user)
    )
    if not player_room and room.creator != api_key.user:
        return error("Access denied to this token", code="FORBIDDEN", status=403)

    # Get trackers
    trackers = list(shape.trackers)
    tracker_dict = {t.name: {"value": t.value, "max": t.maxvalue} for t in trackers}

    # Get extended data
    token_ext = TokenExt.get_or_none(TokenExt.shape == shape)

    return ok(
        {
            "uuid": shape.uuid,
            "name": shape.name,
            "x": shape.x,
            "y": shape.y,
            "floor": shape.layer.floor.name,
            "hp": tracker_dict.get("HP", {"value": 0, "max": 0}),
            "ac": tracker_dict.get("AC", {"value": 0, "max": 0}),
            "faction": token_ext.faction if token_ext else None,
            "conditions": token_ext.get_conditions() if token_ext else [],
            "custom": token_ext.get_custom() if token_ext else {},
        }
    )


@require_role("dm")
async def update_token(request: web.Request) -> web.Response:
    """PATCH /api/v1/tokens/{uuid} - Update a token."""
    token_uuid = request.match_info["uuid"]
    api_key = request["api_key"]

    try:
        data = await request.json()
    except Exception:
        return error("Invalid JSON", code="VALIDATION_ERROR", status=400)

    try:
        shape = Shape.get(Shape.uuid == token_uuid)
    except DoesNotExist:
        return error("Token not found", code="NOT_FOUND", status=404)

    # Check access: user must be DM in this room, or be the room creator
    location = shape.layer.floor.location
    room = location.room
    player_room = PlayerRoom.get_or_none(
        (PlayerRoom.room == room) & (PlayerRoom.player == api_key.user)
    )
    is_room_creator = room.creator == api_key.user
    if not is_room_creator and (not player_room or player_room.role != Role.DM):
        return error("Only DM can update tokens", code="FORBIDDEN", status=403)

    changes = {}

    with db.atomic():
        # Update name
        if "name" in data:
            shape.name = data["name"]
            changes["name"] = data["name"]

        # Update position
        if "x" in data:
            shape.x = float(data["x"])
            changes["x"] = data["x"]
        if "y" in data:
            shape.y = float(data["y"])
            changes["y"] = data["y"]

        shape.save()

        # Update HP (accept "hp" or "hp_current" as aliases)
        hp_val = data.get("hp", data.get("hp_current"))
        if hp_val is not None or "hp_max" in data:
            hp_tracker = Tracker.get_or_none((Tracker.shape == shape) & (Tracker.name == "HP"))
            if hp_tracker:
                if hp_val is not None:
                    hp_tracker.value = int(hp_val)
                    changes["hp"] = int(hp_val)
                if "hp_max" in data:
                    hp_tracker.maxvalue = data["hp_max"]
                    changes["hp_max"] = data["hp_max"]
                hp_tracker.save()

                # Emit tracker update to all players
                for room_player in room.players:
                    for psid in game_state.get_sids(player=room_player.player, active_location=location):
                        await _send_game(
                            "Shape.Options.Tracker.Update",
                            {
                                "shape": token_uuid,
                                "uuid": hp_tracker.uuid,
                                "value": hp_tracker.value,
                                "maxvalue": hp_tracker.maxvalue,
                            },
                            room=psid,
                        )

        # Update AC
        if "ac" in data:
            ac_tracker = Tracker.get_or_none((Tracker.shape == shape) & (Tracker.name == "AC"))
            if ac_tracker:
                ac_tracker.value = data["ac"]
                ac_tracker.maxvalue = data["ac"]
                ac_tracker.save()
                changes["ac"] = data["ac"]

                # Emit tracker update to all players
                for room_player in room.players:
                    for psid in game_state.get_sids(player=room_player.player, active_location=location):
                        await _send_game(
                            "Shape.Options.Tracker.Update",
                            {
                                "shape": token_uuid,
                                "uuid": ac_tracker.uuid,
                                "value": ac_tracker.value,
                                "maxvalue": ac_tracker.maxvalue,
                            },
                            room=psid,
                        )

        # Update TokenExt
        token_ext = TokenExt.get_or_none(TokenExt.shape == shape)
        if not token_ext:
            token_ext = TokenExt.create(
                uuid=str(uuid4()),
                shape=shape,
                faction="",
                conditions=json.dumps([]),
                custom=json.dumps({}),
            )

        if "faction" in data:
            token_ext.faction = data["faction"]
            changes["faction"] = data["faction"]

        if "conditions" in data:
            token_ext.set_conditions(data["conditions"])
            changes["conditions"] = data["conditions"]

        if "custom" in data:
            token_ext.set_custom(data["custom"])
            changes["custom"] = data["custom"]

        token_ext.save()

        # Emit position update if changed
        if "x" in changes or "y" in changes:
            for room_player in room.players:
                for psid in game_state.get_sids(player=room_player.player, active_location=location):
                    await _send_game(
                        "Shapes.Position.Update",
                        [{"uuid": token_uuid, "position": {"x": shape.x, "y": shape.y}}],
                        room=psid,
                    )

        # Emit name update if changed
        if "name" in changes:
            for room_player in room.players:
                for psid in game_state.get_sids(player=room_player.player, active_location=location):
                    await _send_game(
                        "Shape.Options.Name.Set",
                        {"shape": token_uuid, "value": shape.name},
                        room=psid,
                    )

    # Log event
    await log_event(
        event_type="token_updated",
        payload={"token_id": token_uuid, "changes": changes},
        scene_id=location.id,
        actor_id=token_uuid,
    )

    return ok({"updated": changes})


@require_role("dm")
async def delete_token(request: web.Request) -> web.Response:
    """DELETE /api/v1/tokens/{uuid} - Delete a token."""
    token_uuid = request.match_info["uuid"]
    api_key = request["api_key"]

    try:
        shape = Shape.get(Shape.uuid == token_uuid)
    except DoesNotExist:
        return error("Token not found", code="NOT_FOUND", status=404)

    # Check access: user must be DM in this room, or be the room creator
    location = shape.layer.floor.location
    room = location.room
    player_room = PlayerRoom.get_or_none(
        (PlayerRoom.room == room) & (PlayerRoom.player == api_key.user)
    )
    if room.creator != api_key.user and (not player_room or player_room.role != Role.DM):
        return error("Only DM can delete tokens", code="FORBIDDEN", status=403)

    with db.atomic():
        # Delete related records (cascades should handle this, but be explicit)
        Tracker.delete().where(Tracker.shape == shape).execute()
        Aura.delete().where(Aura.shape == shape).execute()
        TokenExt.delete().where(TokenExt.shape == shape).execute()

        # Delete shape
        shape.delete_instance()

    # Emit socket event
    for room_player in room.players:
        for psid in game_state.get_sids(player=room_player.player, active_location=location):
            await _send_game(
                "Shapes.Remove",
                [token_uuid],
                room=psid,
            )

    # Log event
    await log_event(
        event_type="token_deleted",
        payload={"token_id": token_uuid},
        scene_id=location.id,
        actor_id=token_uuid,
    )

    return ok({"deleted": True})


@require_role("dm")
async def update_token_vision(request: web.Request) -> web.Response:
    """PATCH /api/v1/tokens/{uuid}/vision - Update token vision/darkvision.

    Request body:
    {
        "has_vision": true,
        "range": 60,           # Vision range in feet (default: 0)
        "dim": 0,              # Dim light range (default: 0)
        "colour": "rgba(255, 244, 210, 0.10)",  # Vision color (default: warm transparent)
        "angle": 360,          # Vision cone angle (default: 360 = full circle)
        "direction": 0         # Vision cone direction in degrees (default: 0)
    }
    """
    token_uuid = request.match_info["uuid"]
    api_key = request["api_key"]

    try:
        data = await request.json()
    except Exception:
        return error("Invalid JSON", code="VALIDATION_ERROR", status=400)

    # Validate has_vision
    if "has_vision" not in data:
        return error("Missing required field: has_vision", code="VALIDATION_ERROR", status=400)

    has_vision = data.get("has_vision", False)

    try:
        shape = Shape.get(Shape.uuid == token_uuid)
    except DoesNotExist:
        return error("Token not found", code="NOT_FOUND", status=404)

    # Check access: user must be DM in this room, or be the room creator
    location = shape.layer.floor.location
    room = location.room
    player_room = PlayerRoom.get_or_none(
        (PlayerRoom.room == room) & (PlayerRoom.player == api_key.user)
    )
    if room.creator != api_key.user and (not player_room or player_room.role != Role.DM):
        return error("Only DM can update token vision", code="FORBIDDEN", status=403)

    with db.atomic():
        # Find existing vision aura (vision_source=True)
        vision_aura = Aura.get_or_none((Aura.shape == shape) & (Aura.vision_source == True))

        if not has_vision:
            # Remove vision if it exists
            if vision_aura:
                aura_uuid = vision_aura.uuid
                vision_aura.delete_instance()

                # Emit aura removal to all players
                for room_player in room.players:
                    for psid in game_state.get_sids(player=room_player.player, active_location=location):
                        await _send_game(
                            "Shape.Options.Aura.Remove",
                            {"shape": token_uuid, "value": aura_uuid},
                            room=psid,
                        )

                # Log event
                await log_event(
                    event_type="vision_removed",
                    payload={"token_id": token_uuid},
                    scene_id=location.id,
                    actor_id=token_uuid,
                )

                return ok({"vision_removed": True})
            else:
                return ok({"message": "Token already has no vision"})

        # has_vision == True: Create or update vision aura
        vision_range = data.get("range", 60)
        dim_range = data.get("dim", 0)
        colour = data.get("colour", "rgba(255, 244, 210, 0.10)")
        angle = data.get("angle", 360)
        direction = data.get("direction", 0)

        if vision_aura:
            # Update existing aura
            vision_aura.value = vision_range
            vision_aura.dim = dim_range
            vision_aura.colour = colour
            vision_aura.angle = angle
            vision_aura.direction = direction
            vision_aura.save()

            aura_data = vision_aura.as_pydantic().model_dump()

            # Emit aura update to all players
            for room_player in room.players:
                for psid in game_state.get_sids(player=room_player.player, active_location=location):
                    await _send_game(
                        "Shape.Options.Aura.Update",
                        aura_data,
                        room=psid,
                    )

            # Log event
            await log_event(
                event_type="vision_updated",
                payload={
                    "token_id": token_uuid,
                    "range": vision_range,
                    "dim": dim_range,
                    "colour": colour,
                    "angle": angle,
                    "direction": direction,
                },
                scene_id=location.id,
                actor_id=token_uuid,
            )

            return ok({"vision_updated": True, "aura_id": vision_aura.uuid, "colour": colour})
        else:
            # Create new vision aura
            aura_uuid = str(uuid4())
            vision_aura = Aura.create(
                uuid=aura_uuid,
                shape=shape,
                vision_source=True,
                visible=True,
                name="Vision",
                value=vision_range,
                dim=dim_range,
                colour=colour,
                active=True,
                border_colour="rgba(0, 0, 0, 0)",
                angle=angle,
                direction=direction,
            )

            aura_data = vision_aura.as_pydantic().model_dump()

            # Emit aura creation to all players
            for room_player in room.players:
                for psid in game_state.get_sids(player=room_player.player, active_location=location):
                    await _send_game(
                        "Shape.Options.Aura.Create",
                        aura_data,
                        room=psid,
                    )

            # Log event
            await log_event(
                event_type="vision_created",
                payload={
                    "token_id": token_uuid,
                    "range": vision_range,
                    "dim": dim_range,
                    "colour": colour,
                    "angle": angle,
                    "direction": direction,
                },
                scene_id=location.id,
                actor_id=token_uuid,
            )

            return ok({"vision_created": True, "aura_id": aura_uuid, "colour": colour})


@require_role("dm")
async def batch_tokens(request: web.Request) -> web.Response:
    """POST /api/v1/scenes/{uuid}/tokens/batch - Batch create/update/delete tokens.

    Request body:
    {
        "operations": [
            {"op": "create", "data": {"name": "Goblin", "x": 100, "y": 100, "hp": 7, "hp_max": 7}},
            {"op": "update", "id": "uuid", "data": {"hp_current": 3}},
            {"op": "delete", "id": "uuid"}
        ],
        "dry_run": false  // If true, validate only, return preview without executing
    }

    Response:
    {
        "results": [
            {"op": "create", "status": "ok", "id": "new-uuid"},
            {"op": "update", "status": "ok", "id": "uuid"},
            {"op": "delete", "status": "error", "error": "token not found"}
        ],
        "dry_run": false,
        "success_count": 2,
        "error_count": 1
    }
    """
    api_key = request["api_key"]
    try:
        scene_id = int(request.match_info["uuid"])
    except (ValueError, TypeError):
        return error("Invalid scene UUID", code="VALIDATION_ERROR", status=400)

    try:
        body = await request.json()
    except Exception:
        return error("Invalid JSON", code="VALIDATION_ERROR", status=400)

    operations = body.get("operations", [])
    dry_run = body.get("dry_run", False)

    if not operations:
        return error("No operations provided", code="VALIDATION_ERROR", status=400)

    if not isinstance(operations, list):
        return error("operations must be an array", code="VALIDATION_ERROR", status=400)

    # Validate scene exists
    try:
        location = Location.get_by_id(scene_id)
    except DoesNotExist:
        return error("Scene not found", code="NOT_FOUND", status=404)

    # Check access: user must be DM in this room, or be the room creator
    room = location.room
    player_room = PlayerRoom.get_or_none(
        (PlayerRoom.room == room) & (PlayerRoom.player == api_key.user)
    )
    if room.creator != api_key.user and (not player_room or player_room.role != Role.DM):
        return error("Only DM can perform batch operations", code="FORBIDDEN", status=403)

    # Get floor and layer
    floor = location.floors.first()
    if not floor:
        return error("No floor found in scene", code="NOT_FOUND", status=404)

    token_layer = floor.layers.where(Layer.name == "tokens").first()
    if not token_layer:
        return error("Tokens layer not found", code="NOT_FOUND", status=404)

    results = []
    success_count = 0
    error_count = 0

    # Process each operation
    for i, op in enumerate(operations):
        if not isinstance(op, dict):
            results.append({"index": i, "op": "unknown", "status": "error", "error": "Invalid operation format"})
            error_count += 1
            continue

        op_type = op.get("op")
        op_id = op.get("id")
        op_data = op.get("data", {})

        if op_type == "create":
            result = await _batch_create_token(
                location, room, token_layer, floor, op_data, api_key, dry_run
            )
        elif op_type == "update":
            if not op_id:
                result = {"op": "update", "status": "error", "error": "Missing id for update operation"}
            else:
                result = await _batch_update_token(
                    location, room, op_id, op_data, api_key, dry_run
                )
        elif op_type == "delete":
            if not op_id:
                result = {"op": "delete", "status": "error", "error": "Missing id for delete operation"}
            else:
                result = await _batch_delete_token(
                    location, room, op_id, api_key, dry_run
                )
        else:
            result = {"op": op_type, "status": "error", "error": f"Unknown operation: {op_type}"}

        result["index"] = i
        results.append(result)

        if result["status"] == "ok":
            success_count += 1
        else:
            error_count += 1

    return ok({
        "results": results,
        "dry_run": dry_run,
        "success_count": success_count,
        "error_count": error_count,
        "total_operations": len(operations),
    })


async def _batch_create_token(
    location: Location,
    room: Any,
    token_layer: Layer,
    floor: Floor,
    data: dict,
    api_key: Any,
    dry_run: bool,
) -> dict:
    """Helper function for batch create operation."""
    # Validate required fields
    required = ["name", "x", "y"]
    for field in required:
        if field not in data:
            return {"op": "create", "status": "error", "error": f"Missing required field: {field}"}

    name = data["name"]
    x = float(data["x"])
    y = float(data["y"])
    hp_current = data.get("hp_current", data.get("hp", 0))
    hp_max = data.get("hp_max", 0)
    ac = data.get("ac", 0)
    faction = data.get("faction")
    conditions = data.get("conditions", [])
    custom = data.get("custom", {})
    size = data.get("size", 25.0)

    # Dry run: just validate, don't create
    if dry_run:
        return {
            "op": "create",
            "status": "ok",
            "preview": {
                "name": name,
                "x": x,
                "y": y,
                "hp": {"current": hp_current, "max": hp_max},
                "ac": ac,
                "faction": faction,
            },
        }

    token_uuid = str(uuid4())

    # Create shape using PA's create_shape
    with db.atomic():
        api_shape = ApiCircularTokenShape(
            uuid=token_uuid,
            type_="circulartoken",
            x=x,
            y=y,
            name=name,
            name_visible=True,
            fill_colour="rgba(255, 255, 255, 1)",
            stroke_colour="rgba(0, 0, 0, 1)",
            stroke_width=2,
            radius=size / 2,
            viewing_angle=None,
            text=name[:2].upper(),
            font="serif",
            is_invisible=False,
            is_defeated=False,
            is_locked=False,
            vision_obstruction=0,
            movement_obstruction=False,
            draw_operator="source-over",
            options="{}",
            badge=1,
            show_badge=False,
            default_edit_access=False,
            default_vision_access=False,
            default_movement_access=False,
            angle=0.0,
            variants=None,
            group=None,
            ignore_zoom_size=False,
            is_door=False,
            is_teleport_zone=False,
            custom_data=[],
            character=None,
            odd_hex_orientation=False,
            size_x=1,
            size_y=1,
            show_cells=False,
            cell_fill_colour=None,
            cell_stroke_colour=None,
            cell_stroke_width=None,
            notes=[],
            owners=[
                ApiShapeOwner(
                    shape=token_uuid,
                    user=api_key.user.name,
                    edit_access=True,
                    movement_access=True,
                    vision_access=True,
                )
            ],
            trackers=[],
            auras=[],
        )

        shape = create_shape(api_shape, layer=token_layer)
        if not shape:
            return {"op": "create", "status": "error", "error": "Failed to create shape"}

        # Create trackers
        if hp_max > 0:
            Tracker.create(
                uuid=str(uuid4()),
                shape=shape,
                name="HP",
                value=hp_current,
                maxvalue=hp_max,
                visible=True,
                draw=True,
                primary_color="rgb(221, 0, 0)",
                secondary_color="rgb(0, 0, 0)",
            )

        if ac > 0:
            Tracker.create(
                uuid=str(uuid4()),
                shape=shape,
                name="AC",
                value=ac,
                maxvalue=ac,
                visible=True,
                draw=False,
                primary_color="rgb(68, 136, 255)",
                secondary_color="rgb(0, 0, 0)",
            )

        # Create TokenExt
        TokenExt.create(
            uuid=str(uuid4()),
            shape=shape,
            faction=faction or "",
            conditions=json.dumps(conditions),
            custom=json.dumps(custom),
        )

    # Emit socket event to all players
    for room_player in room.players:
        is_dm = room_player.role == Role.DM
        for psid in game_state.get_sids(player=room_player.player, active_location=location):
            if not is_dm and not token_layer.player_visible:
                continue
            api_shape_data = transform_shape(shape, room_player)
            await _send_game(
                "Shape.Add",
                {
                    "shape": api_shape_data,
                    "floor": floor.name,
                    "layer": "tokens",
                    "temporary": False,
                },
                room=psid,
            )

    # Log event
    await log_event(
        event_type="token_created",
        payload={
            "token_id": token_uuid,
            "name": name,
            "hp": {"current": hp_current, "max": hp_max},
            "ac": ac,
            "faction": faction,
            "batch": True,
        },
        scene_id=location.id,
        actor_id=token_uuid,
    )

    return {"op": "create", "status": "ok", "id": token_uuid}


async def _batch_update_token(
    location: Location,
    room: Any,
    token_uuid: str,
    data: dict,
    api_key: Any,
    dry_run: bool,
) -> dict:
    """Helper function for batch update operation."""
    try:
        shape = Shape.get(Shape.uuid == token_uuid)
    except DoesNotExist:
        return {"op": "update", "status": "error", "id": token_uuid, "error": "Token not found"}

    # Verify token is in the correct location
    if shape.layer.floor.location.id != location.id:
        return {"op": "update", "status": "error", "id": token_uuid, "error": "Token not in this scene"}

    # Dry run: validate and preview changes
    if dry_run:
        return {
            "op": "update",
            "status": "ok",
            "id": token_uuid,
            "preview": {"changes": list(data.keys())},
        }

    changes = {}

    with db.atomic():
        # Update name
        if "name" in data:
            shape.name = data["name"]
            changes["name"] = data["name"]

        # Update position
        if "x" in data:
            shape.x = float(data["x"])
            changes["x"] = data["x"]
        if "y" in data:
            shape.y = float(data["y"])
            changes["y"] = data["y"]

        shape.save()

        # Update HP
        if "hp_current" in data or "hp_max" in data or "hp" in data:
            hp_tracker = Tracker.get_or_none((Tracker.shape == shape) & (Tracker.name == "HP"))
            if hp_tracker:
                if "hp_current" in data:
                    hp_tracker.value = int(data["hp_current"])
                    changes["hp_current"] = int(data["hp_current"])
                elif "hp" in data:
                    hp_tracker.value = int(data["hp"])
                    changes["hp_current"] = int(data["hp"])
                if "hp_max" in data:
                    hp_tracker.maxvalue = data["hp_max"]
                    changes["hp_max"] = data["hp_max"]
                hp_tracker.save()

                # Emit tracker update to all players
                for room_player in room.players:
                    for psid in game_state.get_sids(player=room_player.player, active_location=location):
                        await _send_game(
                            "Shape.Options.Tracker.Update",
                            {
                                "shape": token_uuid,
                                "uuid": hp_tracker.uuid,
                                "value": hp_tracker.value,
                                "maxvalue": hp_tracker.maxvalue,
                            },
                            room=psid,
                        )

        # Update AC
        if "ac" in data:
            ac_tracker = Tracker.get_or_none((Tracker.shape == shape) & (Tracker.name == "AC"))
            if ac_tracker:
                ac_tracker.value = data["ac"]
                ac_tracker.maxvalue = data["ac"]
                ac_tracker.save()
                changes["ac"] = data["ac"]

                for room_player in room.players:
                    for psid in game_state.get_sids(player=room_player.player, active_location=location):
                        await _send_game(
                            "Shape.Options.Tracker.Update",
                            {
                                "shape": token_uuid,
                                "uuid": ac_tracker.uuid,
                                "value": ac_tracker.value,
                                "maxvalue": ac_tracker.maxvalue,
                            },
                            room=psid,
                        )

        # Update TokenExt
        token_ext = TokenExt.get_or_none(TokenExt.shape == shape)
        if token_ext:
            if "faction" in data:
                token_ext.faction = data["faction"]
                changes["faction"] = data["faction"]
            if "conditions" in data:
                token_ext.set_conditions(data["conditions"])
                changes["conditions"] = data["conditions"]
            if "custom" in data:
                token_ext.set_custom(data["custom"])
                changes["custom"] = data["custom"]
            token_ext.save()

        # Emit position update if changed
        if "x" in changes or "y" in changes:
            for room_player in room.players:
                for psid in game_state.get_sids(player=room_player.player, active_location=location):
                    await _send_game(
                        "Shapes.Position.Update",
                        [{"uuid": token_uuid, "position": {"x": shape.x, "y": shape.y}}],
                        room=psid,
                    )

        # Emit name update if changed
        if "name" in changes:
            for room_player in room.players:
                for psid in game_state.get_sids(player=room_player.player, active_location=location):
                    await _send_game(
                        "Shape.Options.Name.Set",
                        {"shape": token_uuid, "value": shape.name},
                        room=psid,
                    )

    # Log event
    await log_event(
        event_type="token_updated",
        payload={"token_id": token_uuid, "changes": changes, "batch": True},
        scene_id=location.id,
        actor_id=token_uuid,
    )

    return {"op": "update", "status": "ok", "id": token_uuid, "changes": changes}


async def _batch_delete_token(
    location: Location,
    room: Any,
    token_uuid: str,
    api_key: Any,
    dry_run: bool,
) -> dict:
    """Helper function for batch delete operation."""
    try:
        shape = Shape.get(Shape.uuid == token_uuid)
    except DoesNotExist:
        return {"op": "delete", "status": "error", "id": token_uuid, "error": "Token not found"}

    # Verify token is in the correct location
    if shape.layer.floor.location.id != location.id:
        return {"op": "delete", "status": "error", "id": token_uuid, "error": "Token not in this scene"}

    # Dry run: just validate
    if dry_run:
        return {
            "op": "delete",
            "status": "ok",
            "id": token_uuid,
            "preview": {"name": shape.name},
        }

    with db.atomic():
        # Delete related records
        Tracker.delete().where(Tracker.shape == shape).execute()
        Aura.delete().where(Aura.shape == shape).execute()
        TokenExt.delete().where(TokenExt.shape == shape).execute()

        # Delete shape
        shape.delete_instance()

    # Emit socket event
    for room_player in room.players:
        for psid in game_state.get_sids(player=room_player.player, active_location=location):
            await _send_game(
                "Shapes.Remove",
                [token_uuid],
                room=psid,
            )

    # Log event
    await log_event(
        event_type="token_deleted",
        payload={"token_id": token_uuid, "batch": True},
        scene_id=location.id,
        actor_id=token_uuid,
    )

    return {"op": "delete", "status": "ok", "id": token_uuid}
