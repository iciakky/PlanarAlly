"""REST API handlers for scene (Location) management."""

import json
import uuid
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from aiohttp import web
from peewee import DoesNotExist, fn

from ...api.common.shapes import create_shape
from ...api.helpers import _send_game
from ...api.models.shape import ApiCircularTokenShape
from ...api.models.shape.owner import ApiShapeOwner
from ...api.models.shape.subtypes import ApiPolygonShape, ApiRectShape
from ...db.create.floor import create_floor
from ...db.db import db
from ...db.models.aura import Aura
from ...db.models.floor import Floor
from ...db.models.layer import Layer
from ...db.models.location import Location
from ...db.models.location_options import LocationOptions
from ...db.models.player_room import PlayerRoom
from ...db.models.rest_ext.scene_snapshot import SceneSnapshot
from ...db.models.rest_ext.token_ext import TokenExt
from ...db.models.room import Room
from ...db.models.shape import Shape
from ...db.models.tracker import Tracker
from ...models.role import Role
from ...state.game import game_state
from ...transform.to_api.shape import transform_shape
from .helpers import error, log_event, ok, require_role


@require_role("dm")
async def list_scenes(request: web.Request) -> web.Response:
    """GET /api/v1/scenes - List all scenes."""
    api_key = request["api_key"]
    user = api_key.user

    # Get all rooms owned by this user
    rooms = Room.select().where(Room.creator == user)

    scenes = []
    for room in rooms:
        for location in room.locations:
            scenes.append(
                {
                    "uuid": str(location.id),
                    "room_id": str(room.id),
                    "room_name": room.name,
                    "name": location.name,
                    "index": location.index,
                    "archived": location.archived,
                }
            )

    return ok({"scenes": scenes})


@require_role("dm")
async def create_scene(request: web.Request) -> web.Response:
    """POST /api/v1/scenes - Create a new scene."""
    api_key = request["api_key"]
    user = api_key.user

    try:
        data = await request.json()
    except Exception:
        return error("Invalid JSON", code="VALIDATION_ERROR", status=400)

    room_id = data.get("room_id")
    name = data.get("name")

    if not room_id or not name:
        return error("Missing required fields: room_id, name", code="VALIDATION_ERROR", status=400)

    # Verify room exists and is owned by user
    try:
        room = Room.get_by_id(room_id)
    except DoesNotExist:
        return error(f"Room not found: {room_id}", code="NOT_FOUND", status=404)

    if room.creator.id != user.id:
        return error("You do not own this room", code="FORBIDDEN", status=403)

    # Check for duplicate name in this room
    if Location.get_or_none(room=room, name=name):
        return error(f"Location already exists with name: {name}", code="CONFLICT", status=409)

    # Create location with floor and layers (same pattern as PA's create_room)
    with db.atomic():
        # Find next index
        max_index = Location.select(fn.Max(Location.index)).where(Location.room == room).scalar()
        next_index = (max_index or 0) + 1

        # Create location options
        options = LocationOptions.create()
        location = Location.create(room=room, name=name, index=next_index, options=options)

        # Create default floor with all standard layers
        create_floor(location, "ground")

    # Log event
    await log_event(
        event_type="scene_created",
        payload={"scene_id": location.id, "scene_name": name, "room_id": room_id},
        scene_id=location.id,
    )

    return ok(
        {
            "uuid": str(location.id),
            "room_id": str(room_id),
            "name": name,
            "index": next_index,
            "archived": False,
        },
        status=201,
    )


@require_role("dm", "player")
async def get_scene(request: web.Request) -> web.Response:
    """GET /api/v1/scenes/{uuid} - Get scene metadata."""
    api_key = request["api_key"]
    scene_uuid = request.match_info.get("uuid")

    if not scene_uuid:
        return error("Missing scene UUID", code="VALIDATION_ERROR", status=400)

    try:
        location = Location.get_by_id(scene_uuid)
    except DoesNotExist:
        return error(f"Scene not found: {scene_uuid}", code="NOT_FOUND", status=404)

    room = location.room
    if room.creator.id != api_key.user.id:
        if not any(rp.player.id == api_key.user.id for rp in room.players):
            return error("Access denied to this scene", code="FORBIDDEN", status=403)

    return ok(
        {
            "uuid": str(location.id),
            "room_id": str(location.room.id),
            "room_name": location.room.name,
            "name": location.name,
            "index": location.index,
            "archived": location.archived,
        }
    )


@require_role("dm")
async def update_scene(request: web.Request) -> web.Response:
    """PUT /api/v1/scenes/{uuid} - Update scene settings."""
    api_key = request["api_key"]
    scene_uuid = request.match_info.get("uuid")

    if not scene_uuid:
        return error("Missing scene UUID", code="VALIDATION_ERROR", status=400)

    try:
        location = Location.get_by_id(scene_uuid)
    except DoesNotExist:
        return error(f"Scene not found: {scene_uuid}", code="NOT_FOUND", status=404)

    room = location.room
    if room.creator.id != api_key.user.id:
        return error("Access denied to this scene", code="FORBIDDEN", status=403)

    try:
        data = await request.json()
    except Exception:
        return error("Invalid JSON", code="VALIDATION_ERROR", status=400)

    # Update allowed fields
    updated = False
    if "name" in data:
        # Check for duplicate name in this room
        existing = Location.get_or_none(room=location.room, name=data["name"])
        if existing and existing.id != location.id:
            return error(f"Location already exists with name: {data['name']}", code="CONFLICT", status=409)
        location.name = data["name"]
        updated = True

    if "archived" in data:
        location.archived = bool(data["archived"])
        updated = True

    if updated:
        location.save()
        await log_event(
            event_type="scene_updated",
            payload={"scene_id": location.id, "updates": data},
            scene_id=location.id,
        )

    return ok(
        {
            "uuid": str(location.id),
            "room_id": str(location.room.id),
            "room_name": location.room.name,
            "name": location.name,
            "index": location.index,
            "archived": location.archived,
        }
    )


@require_role("dm")
async def delete_scene(request: web.Request) -> web.Response:
    """DELETE /api/v1/scenes/{uuid} - Delete a scene."""
    api_key = request["api_key"]
    scene_uuid = request.match_info.get("uuid")

    if not scene_uuid:
        return error("Missing scene UUID", code="VALIDATION_ERROR", status=400)

    try:
        location = Location.get_by_id(scene_uuid)
    except DoesNotExist:
        return error(f"Scene not found: {scene_uuid}", code="NOT_FOUND", status=404)

    room = location.room
    if room.creator.id != api_key.user.id:
        return error("Access denied to this scene", code="FORBIDDEN", status=403)

    # Store name for logging before deletion
    scene_name = location.name
    room_id = location.room.id

    # Peewee cascades will handle deletion of floors, layers, shapes, etc.
    location.delete_instance()

    await log_event(
        event_type="scene_deleted",
        payload={"scene_id": scene_uuid, "scene_name": scene_name, "room_id": str(room_id)},
    )

    return ok({"message": f"Scene '{scene_name}' deleted successfully"})


@require_role("dm", "player")
async def get_scene_state(request: web.Request) -> web.Response:
    """GET /api/v1/scenes/{uuid}/state - Get complete scene state snapshot."""
    api_key = request["api_key"]
    scene_uuid = request.match_info.get("uuid")

    if not scene_uuid:
        return error("Missing scene UUID", code="VALIDATION_ERROR", status=400)

    try:
        location = Location.get_by_id(scene_uuid)
    except DoesNotExist:
        return error(f"Scene not found: {scene_uuid}", code="NOT_FOUND", status=404)

    room = location.room
    if room.creator.id != api_key.user.id:
        if not any(rp.player.id == api_key.user.id for rp in room.players):
            return error("Access denied to this scene", code="FORBIDDEN", status=403)

    # Collect all tokens (shapes) in this location
    tokens = []
    for floor in location.floors:
        for layer in floor.layers:
            for shape in layer.shapes:
                # Get associated token extension data if exists
                token_ext = TokenExt.get_or_none(shape=shape)

                # Get trackers (HP, AC, etc.)
                trackers = []
                for tracker in Tracker.select().where(Tracker.shape == shape):
                    trackers.append(
                        {
                            "uuid": str(tracker.uuid),
                            "name": tracker.name,
                            "value": tracker.value,
                            "maxvalue": tracker.maxvalue,
                            "visible": tracker.visible,
                        }
                    )

                token_data: dict[str, Any] = {
                    "uuid": str(shape.uuid),
                    "name": shape.name,
                    "x": shape.x,
                    "y": shape.y,
                    "floor": floor.name,
                    "layer": layer.name,
                    "type": shape.type_,
                    "trackers": trackers,
                }

                # Add extended data if exists
                if token_ext:
                    token_data["faction"] = token_ext.faction
                    token_data["conditions"] = token_ext.get_conditions()
                    token_data["custom"] = token_ext.get_custom()

                tokens.append(token_data)

    state = {
        "scene": {
            "uuid": str(location.id),
            "name": location.name,
            "room_id": str(location.room.id),
        },
        "tokens": tokens,
        # TODO Phase 10: Add active combat
        # TODO Phase 11: Add pending actions
        # TODO Phase 12: Add fog state
    }

    return ok(state)


def _serialize_scene_state(location: Location) -> dict[str, Any]:
    """Serialize the current scene state for snapshot storage."""
    from ...db.models.polygon import Polygon
    from ...db.models.rect import Rect

    tokens = []
    fog_shapes = []

    for floor in location.floors:
        for layer in floor.layers:
            for shape in layer.shapes:
                if layer.name == "tokens":
                    # Serialize token data
                    trackers = list(Tracker.select().where(Tracker.shape == shape))
                    tracker_dict = {t.name: {"value": t.value, "maxvalue": t.maxvalue,
                                             "uuid": t.uuid, "visible": t.visible,
                                             "draw": t.draw, "primary_color": t.primary_color,
                                             "secondary_color": t.secondary_color}
                                    for t in trackers}

                    token_ext = TokenExt.get_or_none(TokenExt.shape == shape)

                    # Get CircularToken radius
                    try:
                        from ...db.models.circle import Circle
                        circle = Circle.get_or_none(Circle.shape == shape)
                        size = (circle.radius * 2) if circle else 50.0
                    except Exception:
                        size = 50.0

                    token_data = {
                        "name": shape.name,
                        "x": shape.x,
                        "y": shape.y,
                        "floor": floor.name,
                        "size": size,
                        "hp_current": tracker_dict.get("HP", {}).get("value", 0),
                        "hp_max": tracker_dict.get("HP", {}).get("maxvalue", 0),
                        "ac": tracker_dict.get("AC", {}).get("value", 0),
                        "faction": token_ext.faction if token_ext else "",
                        "conditions": token_ext.get_conditions() if token_ext else [],
                        "custom": token_ext.get_custom() if token_ext else {},
                    }
                    tokens.append(token_data)

                elif layer.name in ("fow", "fow-players"):
                    # Serialize fog control shapes (options stored as JSON string)
                    try:
                        options = json.loads(shape.options) if shape.options else {}
                    except (json.JSONDecodeError, TypeError):
                        options = {}
                    if not options.get("preFogShape"):
                        continue

                    fog_data: dict[str, Any] = {
                        "type": shape.type_,
                        "layer": layer.name,
                        "floor": floor.name,
                    }

                    if shape.type_ == "polygon":
                        polygon = Polygon.get_or_none(Polygon.shape == shape)
                        if polygon:
                            fog_data["vertices"] = polygon.vertices
                    elif shape.type_ == "rect":
                        rect = Rect.get_or_none(Rect.shape == shape)
                        if rect:
                            fog_data["x"] = shape.x
                            fog_data["y"] = shape.y
                            fog_data["width"] = rect.width
                            fog_data["height"] = rect.height

                    fog_shapes.append(fog_data)

    return {
        "version": 1,
        "captured_at": datetime.now(tz=timezone.utc).isoformat(),
        "tokens": tokens,
        "fog_shapes": fog_shapes,
    }


@require_role("dm")
async def create_snapshot(request: web.Request) -> web.Response:
    """POST /api/v1/scenes/{uuid}/snapshot - Save current scene state as snapshot."""
    scene_uuid = request.match_info.get("uuid")
    api_key = request["api_key"]

    if not scene_uuid:
        return error("Missing scene UUID", code="VALIDATION_ERROR", status=400)

    try:
        location = Location.get_by_id(scene_uuid)
    except DoesNotExist:
        return error(f"Scene not found: {scene_uuid}", code="NOT_FOUND", status=404)

    room = location.room
    if room.creator.id != api_key.user.id:
        return error("Access denied to this scene", code="FORBIDDEN", status=403)

    try:
        data = await request.json()
    except Exception:
        data = {}

    name = data.get("name", f"Snapshot {datetime.now(tz=timezone.utc).strftime('%Y-%m-%d %H:%M')}")

    # Serialize current scene state
    snapshot_data = _serialize_scene_state(location)

    # Store in database
    snap_uuid = str(uuid4())
    snapshot = SceneSnapshot.create(
        uuid=snap_uuid,
        location=location,
        name=name,
        snapshot_data=json.dumps(snapshot_data),
    )

    await log_event(
        event_type="snapshot_created",
        payload={
            "snapshot_id": snap_uuid,
            "snapshot_name": name,
            "token_count": len(snapshot_data["tokens"]),
            "fog_shape_count": len(snapshot_data["fog_shapes"]),
        },
        scene_id=location.id,
    )

    return ok(
        {
            "uuid": snap_uuid,
            "name": name,
            "scene_id": str(location.id),
            "token_count": len(snapshot_data["tokens"]),
            "fog_shape_count": len(snapshot_data["fog_shapes"]),
            "created_at": snapshot.created_at.isoformat(),
        },
        status=201,
    )


@require_role("dm", "player")
async def list_snapshots(request: web.Request) -> web.Response:
    """GET /api/v1/scenes/{uuid}/snapshots - List all snapshots for a scene."""
    api_key = request["api_key"]
    scene_uuid = request.match_info.get("uuid")

    if not scene_uuid:
        return error("Missing scene UUID", code="VALIDATION_ERROR", status=400)

    try:
        location = Location.get_by_id(scene_uuid)
    except DoesNotExist:
        return error(f"Scene not found: {scene_uuid}", code="NOT_FOUND", status=404)

    room = location.room
    if room.creator.id != api_key.user.id:
        if not any(rp.player.id == api_key.user.id for rp in room.players):
            return error("Access denied to this scene", code="FORBIDDEN", status=403)

    snapshots = (
        SceneSnapshot.select()
        .where(SceneSnapshot.location == location)
        .order_by(SceneSnapshot.created_at.desc())
    )

    result = []
    for snap in snapshots:
        snap_data = snap.get_snapshot_data()
        result.append(
            {
                "uuid": snap.uuid,
                "name": snap.name,
                "scene_id": str(location.id),
                "token_count": len(snap_data.get("tokens", [])),
                "fog_shape_count": len(snap_data.get("fog_shapes", [])),
                "created_at": snap.created_at.isoformat(),
            }
        )

    return ok({"snapshots": result, "count": len(result)})


@require_role("dm")
async def restore_snapshot(request: web.Request) -> web.Response:
    """POST /api/v1/scenes/{uuid}/restore/{snap_id} - Restore scene from snapshot."""
    scene_uuid = request.match_info.get("uuid")
    snap_id = request.match_info.get("snap_id")
    api_key = request["api_key"]

    if not scene_uuid or not snap_id:
        return error("Missing scene UUID or snapshot ID", code="VALIDATION_ERROR", status=400)

    try:
        location = Location.get_by_id(scene_uuid)
    except DoesNotExist:
        return error(f"Scene not found: {scene_uuid}", code="NOT_FOUND", status=404)

    room = location.room
    if room.creator.id != api_key.user.id:
        return error("Access denied to this scene", code="FORBIDDEN", status=403)

    try:
        snapshot = SceneSnapshot.get_by_id(snap_id)
    except DoesNotExist:
        return error(f"Snapshot not found: {snap_id}", code="NOT_FOUND", status=404)

    if snapshot.location.id != location.id:
        return error("Snapshot does not belong to this scene", code="FORBIDDEN", status=403)

    snap_data = snapshot.get_snapshot_data()

    # Get all players in this room for socket emission
    # (room already fetched above for access control check)

    # Build list of all socket sessions in this location for broadcasting
    all_sids: list[str] = []
    for room_player in room.players:
        for psid in game_state.get_sids(player=room_player.player, active_location=location):
            all_sids.append(psid)

    with db.atomic():
        # Step 1: Delete all current tokens from "tokens" layer
        deleted_uuids: list[str] = []
        for floor in location.floors:
            token_layer = floor.layers.where(Layer.name == "tokens").first()
            if not token_layer:
                continue
            for shape in list(token_layer.shapes):
                deleted_uuids.append(shape.uuid)
                shape.delete_instance(recursive=True)

        # Step 2: Delete current fog shapes from fow layers
        deleted_fog_uuids: list[str] = []
        for floor in location.floors:
            for fow_layer_name in ("fow", "fow-players"):
                fow_layer = floor.layers.where(Layer.name == fow_layer_name).first()
                if not fow_layer:
                    continue
                for shape in list(fow_layer.shapes):
                    try:
                        options = json.loads(shape.options) if shape.options else {}
                    except (json.JSONDecodeError, TypeError):
                        options = {}
                    if options.get("preFogShape"):
                        deleted_fog_uuids.append(shape.uuid)
                        shape.delete_instance(recursive=True)

    # Step 3-5: Recreate all shapes in a single transaction (atomicity guarantee)
    created_tokens = []
    created_fogs = []
    errors = []

    with db.atomic():
        # Step 3: Recreate tokens from snapshot
        for token_data in snap_data.get("tokens", []):
            floor_name = token_data.get("floor", "ground")
            floor = location.floors.where(Floor.name == floor_name).first()
            if not floor:
                errors.append(f"Floor not found: {floor_name}")
                continue

            token_layer = floor.layers.where(Layer.name == "tokens").first()
            if not token_layer:
                errors.append(f"Tokens layer not found on floor: {floor_name}")
                continue

            token_uuid = str(uuid4())
            name = token_data.get("name", "Unknown")
            x = float(token_data.get("x", 0))
            y = float(token_data.get("y", 0))
            hp_current = token_data.get("hp_current", 0)
            hp_max = token_data.get("hp_max", 0)
            ac = token_data.get("ac", 0)
            faction = token_data.get("faction", "")
            conditions = token_data.get("conditions", [])
            custom = token_data.get("custom", {})
            size = token_data.get("size", 50.0)

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
                errors.append(f"Failed to create shape for token: {name}")
                continue

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

            TokenExt.create(
                uuid=str(uuid4()),
                shape=shape,
                faction=faction,
                conditions=json.dumps(conditions),
                custom=json.dumps(custom),
            )

            created_tokens.append((shape, floor, token_layer))

        # Step 4: Recreate fog shapes from snapshot
        for fog_data in snap_data.get("fog_shapes", []):
            floor_name = fog_data.get("floor", "ground")
            layer_name = fog_data.get("layer", "fow")
            floor = location.floors.where(Floor.name == floor_name).first()
            if not floor:
                errors.append(f"Floor not found for fog: {floor_name}")
                continue

            fow_layer = floor.layers.where(Layer.name == layer_name).first()
            if not fow_layer:
                errors.append(f"FOW layer not found: {layer_name}")
                continue

            fog_uuid = str(uuid4())
            fog_type = fog_data.get("type", "polygon")

            fog_defaults = dict(
                name="fog_restore",
                name_visible=False,
                fill_colour="rgba(0, 0, 0, 0)",
                stroke_colour="rgba(0, 0, 0, 0)",
                stroke_width=0,
                vision_obstruction=0,
                movement_obstruction=False,
                draw_operator="source-over",
                options=json.dumps({"preFogShape": True}),
                badge=1,
                show_badge=False,
                default_edit_access=False,
                default_vision_access=False,
                default_movement_access=False,
                is_invisible=False,
                is_defeated=False,
                is_locked=False,
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
                owners=[],
                trackers=[],
                auras=[],
            )

            if fog_type == "polygon":
                raw_vertices = fog_data.get("vertices", "[]")
                if isinstance(raw_vertices, list):
                    raw_vertices = json.dumps(raw_vertices)
                api_fog = ApiPolygonShape(
                    uuid=fog_uuid,
                    type_="polygon",
                    x=0,
                    y=0,
                    vertices=raw_vertices,
                    open_polygon=False,
                    line_width=0,
                    **fog_defaults,
                )
            else:
                api_fog = ApiRectShape(
                    uuid=fog_uuid,
                    type_="rect",
                    x=fog_data.get("x", 0),
                    y=fog_data.get("y", 0),
                    width=fog_data.get("width", 100),
                    height=fog_data.get("height", 100),
                    **fog_defaults,
                )

            fog_shape = create_shape(api_fog, layer=fow_layer)
            if not fog_shape:
                errors.append(f"Failed to create fog shape: {fog_uuid}")
                continue

            created_fogs.append((fog_shape, floor, fow_layer, layer_name))

    created_token_count = len(created_tokens)
    created_fog_count = len(created_fogs)

    # Emit socket events after transaction commits
    all_deleted = deleted_uuids + deleted_fog_uuids
    if all_deleted:
        for psid in all_sids:
            await _send_game("Shapes.Remove", all_deleted, room=psid)

    for shape, floor, token_layer in created_tokens:
        for room_player in room.players:
            is_dm = room_player.role == Role.DM
            for psid in game_state.get_sids(player=room_player.player, active_location=location):
                if not is_dm and not token_layer.player_visible:
                    continue
                api_shape_data = transform_shape(shape, room_player)
                await _send_game(
                    "Shape.Add",
                    {"shape": api_shape_data, "floor": floor.name, "layer": "tokens", "temporary": False},
                    room=psid,
                )

    for fog_shape, floor, fow_layer, layer_name in created_fogs:
        for room_player in room.players:
            for psid in game_state.get_sids(player=room_player.player, active_location=location):
                api_shape_data = transform_shape(fog_shape, room_player)
                await _send_game(
                    "Shape.Add",
                    {"shape": api_shape_data, "floor": floor.name, "layer": layer_name, "temporary": False},
                    room=psid,
                )

    await log_event(
        event_type="snapshot_restored",
        payload={
            "snapshot_id": snap_id,
            "snapshot_name": snapshot.name,
            "tokens_restored": created_token_count,
            "fog_shapes_restored": created_fog_count,
        },
        scene_id=location.id,
    )

    result = {
        "message": f"Scene restored from snapshot '{snapshot.name}'",
        "tokens_restored": created_token_count,
        "fog_shapes_restored": created_fog_count,
        "snapshot": {
            "uuid": snapshot.uuid,
            "name": snapshot.name,
            "created_at": snapshot.created_at.isoformat(),
        },
    }
    if errors:
        result["warnings"] = errors

    return ok(result)
